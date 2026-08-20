import re

from scraper.parser import duracion_minutos, parse_movie
from tests.fake_site import PELICULA_HTML

URL = "https://www.rottentomatoes.com/m/the_godfather"


def ficha():
    return parse_movie(PELICULA_HTML, URL)


def test_campos_basicos():
    datos = ficha()
    assert datos["id"] == "the_godfather"
    assert datos["url"] == URL
    assert datos["title"] == "The Godfather"
    assert datos["type"] == "movie"
    assert datos["source"] == "rottentomatoes.com"


def test_las_propiedades_sueltas_se_reconocen_por_su_forma():
    """Llegan como ["R", "1972", "2h 57m"], sin etiquetar."""
    datos = ficha()
    assert datos["certificate"] == "R"
    assert datos["year"] == 1972
    assert datos["runtime_minutes"] == 177


def test_las_dos_notas_de_la_casa_y_la_de_diez():
    datos = ficha()
    assert datos["tomatometer"] == 97
    assert datos["tomatometer_count"] == 155
    assert datos["tomatometer_certified"] is True
    assert datos["audience_score"] == 98
    # La nota sobre diez es la media de los criticos, que es lo que entiende
    # el sitio; el porcentaje no sirve para pintar estrellas.
    assert datos["rating"] == 9.8
    # Un porcentaje no dice a cuanta gente le gusto: los votos, si.
    assert datos["votes"] == 166247 + 3849


def test_generos_normalizados_y_carpeta_de_destino():
    datos = ficha()
    assert datos["genres"] == ["Crime", "Drama"]
    assert datos["category"] == "crime"


def test_equipo_y_reparto_con_sus_fotos():
    datos = ficha()
    assert [d["name"] for d in datos["directors"]] == ["Francis Ford Coppola"]
    assert [c["name"] for c in datos["cast"]] == ["Marlon Brando", "Al Pacino", "James Caan"]
    assert datos["cast"][0]["id"] == "marlon_brando"
    assert "/120x150/" in datos["cast"][0]["image"]
    # Quien llega sin nombre no entra.
    assert all(c["name"] for c in datos["cast"])


def test_imagenes_sinopsis_y_donde_verla():
    datos = ficha()
    assert "/300x450/" in datos["poster"]
    assert datos["plot"].startswith("Mob drama")
    assert len(datos["images"]) == 4          # caratula, fondo y dos fotos
    assert datos["images"][0]["url"] == datos["poster"]
    assert [s["name"] for s in datos["streaming"]] == ["Stream", "Paramount+"]


def test_sin_los_bloques_json_se_apaña_con_el_resto():
    recortado = re.sub(r'<script id="media-hero-json".*?</script>', "", PELICULA_HTML, flags=re.S)
    datos = parse_movie(recortado, URL)
    # El titulo y el año salen del bloque de "donde verla".
    assert datos["title"] == "The Godfather"
    assert datos["year"] == 1972
    # Y la clasificacion, del JSON-LD.
    assert datos["certificate"] == "R"
    assert datos["poster"] is None


def test_una_pagina_que_no_es_una_ficha():
    assert parse_movie("<html><body><p>nada</p></body></html>", "https://www.rottentomatoes.com/") is None


def test_duraciones():
    assert duracion_minutos("2h 57m") == 177
    assert duracion_minutos("1h") == 60
    assert duracion_minutos("95m") == 95
    assert duracion_minutos("") is None
    assert duracion_minutos("cualquier cosa") is None


def test_el_trailer_trae_con_que_reproducirlo_sin_salir_del_sitio():
    """El identificador del video ya viene en la ficha: no hace falta otra peticion."""
    datos = ficha()
    trailer = datos["trailer"]
    assert trailer["id"] == "HBkn4j1fqMph"
    assert trailer["title"] == "The Godfather: Trailer 1"
    assert trailer["src"].endswith("/HBkn4j1fqMph?formats=M3U+none")
    assert trailer["seconds"] is None      # el fixture no trae duracion en segundos


def test_una_pelicula_sin_video_no_inventa_un_trailer():
    from scraper.parser import _trailer

    assert _trailer(None) is None
    assert _trailer({}) is None
    assert _trailer({"title": "sin identificador"}) is None
