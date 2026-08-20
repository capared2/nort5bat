import json

from scraper.storage import RunState, TitleStore, tarjeta


def ficha(tconst, genero_principal="drama", generos=("Drama",), votos=1000, nota=7.0, anio=2000):
    return {
        "id": tconst,
        "url": f"https://www.imdb.com/title/{tconst}/",
        "category": genero_principal,
        "type": "movie",
        "title": f"Pelicula {tconst}",
        "original_title": f"Pelicula {tconst}",
        "genres": list(generos),
        "year": anio,
        "rating": nota,
        "votes": votos,
        "runtime_minutes": 100,
        "certificate": "PG",
        "poster": f"https://m.media-amazon.com/{tconst}.jpg",
        "plot": "Una sinopsis cualquiera.",
        "directors": [{"id": "nm1", "name": "Quien Sea"}],
        "scraped_at": "2026-08-20T10:00:00Z",
    }


def test_trocea_por_tamaño_y_guarda_en_la_carpeta_del_genero(tmp_path):
    almacen = TitleStore(tmp_path, shard_size=2)
    for numero in range(5):
        almacen.add(ficha(f"tt000000{numero}"))
    assert almacen.flush() == {"drama": 5}

    partes = sorted((tmp_path / "titulos" / "drama").glob("part-*.json"))
    assert [p.name for p in partes] == ["part-0001.json", "part-0002.json", "part-0003.json"]
    assert json.loads(partes[0].read_text())["count"] == 2


def test_una_ficha_ya_guardada_se_actualiza_en_su_sitio(tmp_path):
    almacen = TitleStore(tmp_path, shard_size=10)
    almacen.add(ficha("tt0000001", nota=7.0))
    almacen.flush()

    almacen.add(ficha("tt0000001", nota=8.4))
    assert almacen.flush() == {"drama": 0}      # no es nueva, se sustituye

    parte = json.loads((tmp_path / "titulos" / "drama" / "part-0001.json").read_text())
    assert parte["count"] == 1
    assert parte["titles"][0]["rating"] == 8.4


def test_los_indices_cubren_generos_principales_y_secundarios(tmp_path):
    almacen = TitleStore(tmp_path, shard_size=10)
    almacen.add(ficha("tt0000001", "horror", ("Horror", "Sci-Fi"), votos=500_000, nota=8.5))
    almacen.add(ficha("tt0000002", "drama", ("Drama",), votos=30_000, nota=9.1, anio=1975))
    almacen.flush()

    indice = almacen.rebuild_index()
    assert indice["total_titles"] == 2

    generos = {g["genre"]: g for g in indice["genres"]}
    assert generos["horror"]["titles"] == 1
    # Ciencia ficcion no gana como principal, pero tiene lista y sale en el menu.
    assert generos["sci-fi"]["titles"] == 0
    assert generos["sci-fi"]["tagged"] == 1

    sci = json.loads((tmp_path / "generos" / "sci-fi.json").read_text())
    assert [t["id"] for t in sci["titles"]] == ["tt0000001"]

    lookup = json.loads((tmp_path / "titulos" / "horror" / "lookup.json").read_text())
    assert lookup["parts"] == {"tt0000001": 1}


def test_la_portada_reune_los_carruseles(tmp_path):
    almacen = TitleStore(tmp_path, shard_size=10)
    almacen.add(ficha("tt0000001", votos=500_000, nota=7.9, anio=2024))
    almacen.add(ficha("tt0000002", votos=40_000, nota=9.1, anio=1975))
    almacen.add(ficha("tt0000003", votos=100, nota=9.9, anio=2001))     # sin aval
    almacen.flush()
    almacen.rebuild_index()

    portada = json.loads((tmp_path / "portada.json").read_text())
    assert [t["id"] for t in portada["populares"]] == ["tt0000001", "tt0000002", "tt0000003"]
    # La de 9,9 con cien votos no entra en las mejor valoradas.
    assert [t["id"] for t in portada["mejor_valoradas"]] == ["tt0000002", "tt0000001"]
    assert portada["recientes"][0]["id"] == "tt0000001"
    assert [t["id"] for t in portada["clasicos"]] == ["tt0000002"]


def test_el_indice_de_busqueda_se_trocea_por_inicial(tmp_path):
    almacen = TitleStore(tmp_path, shard_size=10)
    matrix = ficha("tt0133093", "sci-fi", ("Sci-Fi",))
    matrix["title"] = "The Matrix"
    matrix["original_title"] = "Matrix"
    almacen.add(matrix)
    almacen.flush()
    almacen.rebuild_index()

    con_t = json.loads((tmp_path / "buscar" / "t.json").read_text())
    con_m = json.loads((tmp_path / "buscar" / "m.json").read_text())
    assert con_t["titles"] == [["tt0133093", "sci-fi", "The Matrix", 2000, 7.0]]
    assert con_m["titles"] == [["tt0133093", "sci-fi", "Matrix", 2000, 7.0]]
    assert json.loads((tmp_path / "buscar" / "index.json").read_text())["letters"] == ["m", "t"]


def test_no_se_reescribe_lo_que_no_ha_cambiado(tmp_path):
    almacen = TitleStore(tmp_path, shard_size=10)
    almacen.add(ficha("tt0000001"))
    almacen.flush()
    almacen.rebuild_index()

    parte = tmp_path / "titulos" / "drama" / "part-0001.json"
    antes = parte.stat().st_mtime_ns
    contenido = parte.read_text()

    almacen.add(ficha("tt0000001"))
    almacen.flush()
    almacen.rebuild_index()

    assert parte.read_text() == contenido
    assert parte.stat().st_mtime_ns == antes


def test_la_tarjeta_recorta_la_sinopsis():
    completa = ficha("tt0000001")
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
