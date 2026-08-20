import json

from scraper.storage import RunState, TitleStore, tarjeta


def ficha(slug, genero_principal="drama", generos=("Drama",), votos=1000, nota=7.0, anio=2000):
    return {
        "id": slug,
        "url": f"https://www.rottentomatoes.com/m/{slug}",
        "category": genero_principal,
        "type": "movie",
        "title": f"Pelicula {slug}",
        "original_title": f"Pelicula {slug}",
        "genres": list(generos),
        "year": anio,
        "rating": nota,
        "votes": votos,
        "runtime_minutes": 100,
        "certificate": "PG",
        "poster": f"https://resizing.flixster.com/AAA=/300x450/v2/{slug}.jpg",
        "plot": "Una sinopsis cualquiera.",
        "directors": [{"id": "nm1", "name": "Quien Sea"}],
        "scraped_at": "2026-08-20T10:00:00Z",
    }


def test_trocea_por_tamaño_y_guarda_en_la_carpeta_del_genero(tmp_path):
    almacen = TitleStore(tmp_path, shard_size=2)
    for numero in range(5):
        almacen.add(ficha(f"pelicula-{numero}"))
    assert almacen.flush() == {"drama": 5}

    partes = sorted((tmp_path / "titulos" / "drama").glob("part-*.json"))
    assert [p.name for p in partes] == ["part-0001.json", "part-0002.json", "part-0003.json"]
    assert json.loads(partes[0].read_text())["count"] == 2


def test_una_ficha_ya_guardada_se_actualiza_en_su_sitio(tmp_path):
    almacen = TitleStore(tmp_path, shard_size=10)
    almacen.add(ficha("una-cualquiera", nota=7.0))
    almacen.flush()

    almacen.add(ficha("una-cualquiera", nota=8.4))
    assert almacen.flush() == {"drama": 0}      # no es nueva, se sustituye

    parte = json.loads((tmp_path / "titulos" / "drama" / "part-0001.json").read_text())
    assert parte["count"] == 1
    assert parte["titles"][0]["rating"] == 8.4


def test_los_indices_cubren_generos_principales_y_secundarios(tmp_path):
    almacen = TitleStore(tmp_path, shard_size=10)
    almacen.add(ficha("alien", "terror", ("Terror", "Ciencia ficción"), votos=500_000, nota=8.5))
    almacen.add(ficha("network", "drama", ("Drama",), votos=30_000, nota=9.1, anio=1975))
    almacen.flush()

    indice = almacen.rebuild_index()
    assert indice["total_titles"] == 2

    generos = {g["genre"]: g for g in indice["genres"]}
    assert generos["terror"]["titles"] == 1
    # Ciencia ficcion no gana como principal, pero tiene lista y sale en el menu.
    assert generos["ciencia-ficcion"]["titles"] == 0
    assert generos["ciencia-ficcion"]["tagged"] == 1

    sci = json.loads((tmp_path / "generos" / "ciencia-ficcion.json").read_text())
    assert [t["id"] for t in sci["titles"]] == ["alien"]

    lookup = json.loads((tmp_path / "titulos" / "terror" / "lookup.json").read_text())
    assert lookup["parts"] == {"alien": 1}


def test_la_portada_reune_los_carruseles(tmp_path):
    almacen = TitleStore(tmp_path, shard_size=10)
    almacen.add(ficha("dune", votos=500_000, nota=7.9, anio=2024))
    almacen.add(ficha("network", votos=40_000, nota=9.1, anio=1975))
    almacen.add(ficha("rareza", votos=100, nota=9.9, anio=2001))     # sin aval
    almacen.flush()
    almacen.rebuild_index()

    portada = json.loads((tmp_path / "portada.json").read_text())
    assert [t["id"] for t in portada["populares"]] == ["dune", "network", "rareza"]
    # La de 9,9 con cien votos no entra en las mejor valoradas.
    assert [t["id"] for t in portada["mejor_valoradas"]] == ["network", "dune"]
    assert portada["recientes"][0]["id"] == "dune"
    assert [t["id"] for t in portada["clasicos"]] == ["network"]


def test_el_indice_de_busqueda_se_trocea_por_inicial(tmp_path):
    almacen = TitleStore(tmp_path, shard_size=10)
    matrix = ficha("the_matrix", "ciencia-ficcion", ("Ciencia ficción",))
    matrix["title"] = "The Matrix"
    matrix["original_title"] = "Matrix"
    almacen.add(matrix)
    almacen.flush()
    almacen.rebuild_index()

    con_t = json.loads((tmp_path / "buscar" / "t.json").read_text())
    con_m = json.loads((tmp_path / "buscar" / "m.json").read_text())
    assert con_t["titles"] == [["the_matrix", "ciencia-ficcion", "The Matrix", 2000, 7.0]]
    # "The Matrix" tambien vive bajo la eme, que es por donde se busca.
    assert sorted(fila[2] for fila in con_m["titles"]) == ["Matrix", "The Matrix"]
    assert json.loads((tmp_path / "buscar" / "index.json").read_text())["letters"] == ["m", "t"]


def test_una_pelicula_se_encuentra_por_cualquiera_de_sus_palabras(tmp_path):
    """Nadie busca «el padrino»: busca «padrino»."""
    almacen = TitleStore(tmp_path, shard_size=10)
    padrino = ficha("the_godfather", "crimen", ("Crimen",))
    padrino["title"] = "El padrino"
    padrino["original_title"] = "The Godfather"
    almacen.add(padrino)
    almacen.flush()
    almacen.rebuild_index()

    def titulos(letra):
        ruta = tmp_path / "buscar" / f"{letra}.json"
        return [fila[2] for fila in json.loads(ruta.read_text())["titles"]] if ruta.exists() else []

    assert "El padrino" in titulos("p")      # por la palabra que se teclea
    assert "El padrino" in titulos("e")      # y por la inicial del titulo
    assert "The Godfather" in titulos("g")   # el original, por su palabra fuerte
    # Los articulos no generan cubo propio si no encabezan el titulo.
    assert titulos("d") == []


def test_no_se_reescribe_lo_que_no_ha_cambiado(tmp_path):
    almacen = TitleStore(tmp_path, shard_size=10)
    almacen.add(ficha("una-cualquiera"))
    almacen.flush()
    almacen.rebuild_index()

    parte = tmp_path / "titulos" / "drama" / "part-0001.json"
    antes = parte.stat().st_mtime_ns
    contenido = parte.read_text()

    almacen.add(ficha("una-cualquiera"))
    almacen.flush()
    almacen.rebuild_index()

    assert parte.read_text() == contenido
    assert parte.stat().st_mtime_ns == antes


def test_la_tarjeta_recorta_la_sinopsis():
    completa = ficha("una-cualquiera")
    completa["plot"] = "palabra " * 100
    resumida = tarjeta(completa)
    assert len(resumida["plot"]) <= 205 and resumida["plot"].endswith("…")
    assert "body" not in resumida and resumida["directors"] == ["Quien Sea"]


def test_el_estado_encola_sin_repetir_y_olvida_para_refrescar(tmp_path):
    estado = RunState(tmp_path)
    assert estado.enqueue(["a", "b", "a"]) == 2
    assert estado.take(1) == ["a"]
    estado.mark_seen("a")
    assert estado.enqueue(["a", "c"]) == 1

    assert estado.forget(["a"]) == 1
    estado.requeue(["a"])
    assert estado.pending[0] == "a"


def test_una_url_que_falla_demasiado_deja_de_encolarse(tmp_path):
    estado = RunState(tmp_path, max_failures=2)
    for _ in range(2):
        estado.mark_failed("mala")
    assert estado.enqueue(["mala", "buena"]) == 1


def test_el_estado_sobrevive_a_la_ejecucion(tmp_path):
    estado = RunState(tmp_path)
    estado.enqueue(["a", "b"])
    estado.mark_seen("a")
    estado.save({"last_run": {"saved": 1}})

    recargado = RunState(tmp_path)
    assert recargado.seen == {"a"}
    assert recargado.pending == ["b"]


def test_las_rutas_resuelven_un_id_sin_saber_su_genero(tmp_path):
    almacen = TitleStore(tmp_path, shard_size=10)
    almacen.add(ficha("the_godfather", "crimen", ("Crimen", "Drama")))
    almacen.add(ficha("the_matrix", "ciencia-ficcion", ("Ciencia ficción",)))
    almacen.flush()
    almacen.rebuild_index()

    cubo = json.loads((tmp_path / "rutas" / "er.json").read_text())
    assert cubo["titles"] == {"the_godfather": ["crimen", 1]}
    otro = json.loads((tmp_path / "rutas" / "ix.json").read_text())
    assert otro["titles"] == {"the_matrix": ["ciencia-ficcion", 1]}


def test_una_variable_de_entorno_vacia_no_borra_el_valor_por_defecto(monkeypatch):
    """Actions pasa una variable de repositorio inexistente como cadena vacia."""
    import importlib

    from scraper import config

    monkeypatch.setenv("SITE_URL", "")
    recargado = importlib.reload(config)
    assert recargado.SITE_URL == "https://nort5.com"

    monkeypatch.setenv("SITE_URL", "https://otro.example")
    recargado = importlib.reload(config)
    assert recargado.SITE_URL == "https://otro.example"

    monkeypatch.delenv("SITE_URL")
    importlib.reload(config)


def test_la_tarjeta_lleva_los_porcentajes_que_enseña_la_parrilla():
    """Sin ellos, cada tarjeta pintaba un porcentaje vacio."""
    completa = ficha("una-cualquiera")
    completa.update({"tomatometer": 94, "audience_score": 93})
    resumida = tarjeta(completa)
    assert resumida["tomatometer"] == 94
    assert resumida["audience_score"] == 93


def test_el_refresco_recorre_el_archivo_entero_y_no_el_mismo_tramo(tmp_path):
    """Sin cursor se repasaban siempre las mismas fichas, alfabeticamente."""
    estado = RunState(tmp_path)
    todas = [f"https://www.rottentomatoes.com/m/p{n:02d}" for n in range(10)]
    for url in todas:
        estado.mark_seen(url)

    primero = estado.rotar(4)
    segundo = estado.rotar(4)
    tercero = estado.rotar(4)

    assert primero == todas[:4]
    assert segundo == todas[4:8]
    # Al llegar al final se da la vuelta.
    assert tercero == todas[8:10] + todas[:2]
    assert len(set(primero + segundo)) == 8


def test_el_cursor_del_refresco_sobrevive_a_la_ejecucion(tmp_path):
    estado = RunState(tmp_path)
    for n in range(10):
        estado.mark_seen(f"https://www.rottentomatoes.com/m/p{n:02d}")
    estado.rotar(4)
    estado.save()

    recargado = RunState(tmp_path)
    assert recargado.refresh_cursor == 4
    assert recargado.rotar(2) == [
        "https://www.rottentomatoes.com/m/p04",
        "https://www.rottentomatoes.com/m/p05",
    ]
