import re

from scraper.parser import duracion_minutos, fecha_iso, parse_title
from tests.fake_site import TITLE_HTML

URL = "https://www.imdb.com/title/tt0111161/"


def ficha():
    return parse_title(TITLE_HTML, URL)


def test_campos_basicos():
    datos = ficha()
    assert datos["id"] == "tt0111161"
    assert datos["url"] == URL
    assert datos["title"] == "The Shawshank Redemption"
    assert datos["year"] == 1994
    assert datos["release_date"] == "1994-10-14"
    assert datos["runtime_minutes"] == 142
    assert datos["certificate"] == "R"
    assert datos["type"] == "movie"


def test_nota_y_votos_salen_del_bloque_de_la_pagina():
    datos = ficha()
    assert datos["rating"] == 9.3
    assert datos["votes"] == 2934567       # el de __NEXT_DATA__, mas fino que el JSON-LD
    assert datos["metascore"] == 82


def test_generos_y_carpeta_de_destino():
    datos = ficha()
    assert datos["genres"] == ["Drama", "Crime"]
    assert datos["category"] == "crime"     # crimen manda sobre drama


def test_equipo_y_reparto():
    datos = ficha()
    assert [d["name"] for d in datos["directors"]] == ["Frank Darabont"]
    assert [g["name"] for g in datos["writers"]] == ["Stephen King", "Frank Darabont"]
    assert datos["cast"][0] == {
        "id": "nm0000209",
        "name": "Tim Robbins",
        "character": "Andy Dufresne",
        "image": "https://m.media-amazon.com/images/M/robbins.jpg",
    }
    assert len(datos["cast"]) == 3


def test_datos_de_produccion():
    datos = ficha()
    assert datos["countries"] == ["United States"]
    assert datos["languages"] == ["English"]
    assert datos["companies"] == ["Castle Rock Entertainment"]
    assert datos["budget"] == {"amount": 25000000, "currency": "USD"}
    assert datos["gross_worldwide"] == {"amount": 28884504, "currency": "USD"}


def test_sinopsis_etiquetas_y_parecidas():
    datos = ficha()
    assert datos["plot"].startswith("Over the course")
    assert datos["tagline"].startswith("Fear can hold you prisoner")
    assert "prison" in datos["keywords"]
    # El identificador que no es un tconst se descarta.
    assert datos["similar"] == ["tt0068646", "tt0071562"]


def test_imagenes_y_trailer():
    datos = ficha()
    assert datos["poster"].endswith("MV5Bposter._V1_.jpg")
    assert any("still1.jpg" in i["url"] for i in datos["images"])
    assert datos["trailer"] == "https://www.imdb.com/video/vi3877612057/"


def test_sin_next_data_se_apana_con_el_json_ld():
    recortado = re.sub(
        r'<script id="__NEXT_DATA__".*?</script>', "", TITLE_HTML, flags=re.S
    )
    datos = parse_title(recortado, URL)
    assert datos["title"] == "The Shawshank Redemption"
    assert datos["rating"] == 9.3
    assert datos["votes"] == 2900000
    assert datos["runtime_minutes"] == 142
    assert datos["genres"] == ["Drama"]
    assert [d["name"] for d in datos["directors"]] == ["Frank Darabont"]
    assert [a["name"] for a in datos["cast"]] == ["Tim Robbins", "Morgan Freeman"]
    # El JSON-LD mete a la productora entre los "creator": se queda sin nombre y
    # no debe colarse en el guion.
    assert [g["name"] for g in datos["writers"]] == ["Stephen King"]


def test_pagina_que_no_es_una_ficha():
    assert parse_title("<html><body><p>nada</p></body></html>", "https://www.imdb.com/chart/top/") is None


def test_duraciones():
    assert duracion_minutos("PT2H22M") == 142
    assert duracion_minutos("PT45M") == 45
    assert duracion_minutos(8520) == 142        # segundos
    assert duracion_minutos(142) == 142         # ya venia en minutos
    assert duracion_minutos(None) is None
    assert duracion_minutos("cualquier cosa") is None


def test_fechas():
    assert fecha_iso({"year": 1994, "month": 10, "day": 14}) == "1994-10-14"
    assert fecha_iso({"year": 1994}) == "1994-01-01"
    assert fecha_iso("1994-10-14T00:00:00Z") == "1994-10-14"
    assert fecha_iso("1994") == "1994-01-01"
    assert fecha_iso(None) is None
