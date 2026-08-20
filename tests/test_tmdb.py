import json

import pytest

from scraper import tmdb


class RespuestaFalsa:
    def __init__(self, payload, codigo=200):
        self.payload = payload
        self.status_code = codigo
        self.headers = {}

    def json(self):
        return self.payload


class SesionFalsa:
    """Un TMDB de mentira: conoce dos peliculas y nada mas."""

    CONOCIDAS = {
        "tt0111161": {
            "movie_results": [
                {
                    "id": 278,
                    "poster_path": "/cartel.jpg",
                    "backdrop_path": "/fondo.jpg",
                    "overview": "Dos presos traban amistad a lo largo de los años.",
                }
            ]
        },
        "tt0068646": {"tv_results": [{"id": 999, "poster_path": "/otro.jpg", "overview": ""}]},
    }

    def __init__(self):
        self.pedidas = []
        self.headers = {}

    def get(self, url, params=None, timeout=None):
        tconst = url.rsplit("/", 1)[-1]
        self.pedidas.append(tconst)
        return RespuestaFalsa(self.CONOCIDAS.get(tconst, {"movie_results": [], "tv_results": []}))

    def close(self):
        pass


@pytest.fixture
def sesion(monkeypatch):
    doble = SesionFalsa()
    monkeypatch.setattr(tmdb.requests, "Session", lambda: doble)
    return doble


def ficha(tconst, votos=1000):
    return {"id": tconst, "title": f"Pelicula {tconst}", "poster": None, "plot": "", "votes": votos}


def test_pone_caratula_fondo_y_sinopsis(tmp_path, sesion):
    fichas = [ficha("tt0111161")]
    resumen = tmdb.enriquecer(fichas, "clave", tmp_path / "tmdb.json", por_segundo=1000)

    assert resumen["con_caratula"] == 1
    pelicula = fichas[0]
    assert pelicula["poster"] == "https://image.tmdb.org/t/p/w500/cartel.jpg"
    assert pelicula["images"] == [
        {"url": "https://image.tmdb.org/t/p/w500/cartel.jpg", "caption": ""},
        {"url": "https://image.tmdb.org/t/p/w780/fondo.jpg", "caption": ""},
    ]
    assert pelicula["plot"].startswith("Dos presos")
    assert pelicula["tmdb_id"] == 278


def test_tambien_mira_los_resultados_de_serie(tmp_path, sesion):
    fichas = [ficha("tt0068646")]
    tmdb.enriquecer(fichas, "clave", tmp_path / "tmdb.json", por_segundo=1000)
    assert fichas[0]["poster"] == "https://image.tmdb.org/t/p/w500/otro.jpg"


def test_lo_que_tmdb_no_conoce_tambien_se_recuerda(tmp_path, sesion):
    cache = tmp_path / "tmdb.json"
    fichas = [ficha("tt7777777")]
    resumen = tmdb.enriquecer(fichas, "clave", cache, por_segundo=1000)
    assert resumen["sin_encontrar"] == 1
    assert fichas[0]["poster"] is None

    # La segunda vez no se vuelve a preguntar: es la unica forma de que las
    # ejecuciones diarias no repitan siempre las mismas consultas en balde.
    sesion.pedidas.clear()
    resumen = tmdb.enriquecer([ficha("tt7777777")], "clave", cache, por_segundo=1000)
    assert sesion.pedidas == []
    assert resumen["desde_cache"] == 1


def test_la_cache_sobrevive_y_rellena_sin_preguntar(tmp_path, sesion):
    cache = tmp_path / "tmdb.json"
    tmdb.enriquecer([ficha("tt0111161")], "clave", cache, por_segundo=1000)
    assert json.loads(cache.read_text())["tt0111161"]["tmdb_id"] == 278

    sesion.pedidas.clear()
    fichas = [ficha("tt0111161")]
    tmdb.enriquecer(fichas, "clave", cache, por_segundo=1000)
    assert sesion.pedidas == []
    assert fichas[0]["poster"] == "https://image.tmdb.org/t/p/w500/cartel.jpg"


def test_el_tope_atiende_primero_a_las_mas_votadas(tmp_path, sesion):
    fichas = [ficha("tt0000001", votos=10), ficha("tt0111161", votos=900000)]
    tmdb.enriquecer(fichas, "clave", tmp_path / "tmdb.json", limite=1, por_segundo=1000)
    assert sesion.pedidas == ["tt0111161"]


def test_no_pisa_una_caratula_que_ya_estaba(tmp_path, sesion):
    pelicula = ficha("tt0111161")
    pelicula["poster"] = "https://m.media-amazon.com/ya-la-tenia.jpg"
    pelicula["plot"] = "Sinopsis que ya venia."
    tmdb.aplicar(pelicula, {"poster": "https://image.tmdb.org/t/p/w500/cartel.jpg", "plot": "otra"})
    assert pelicula["poster"] == "https://m.media-amazon.com/ya-la-tenia.jpg"
    assert pelicula["plot"] == "Sinopsis que ya venia."
