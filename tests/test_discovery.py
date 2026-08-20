from scraper import discovery
from tests.fake_site import FakeFetcher


def test_listas_publicas_dan_fichas_sin_repetir():
    falso = FakeFetcher()
    encontradas = discovery.from_charts(falso, seeds=["/chart/top/"])
    assert encontradas == [
        "https://www.imdb.com/title/tt0111161/",
        "https://www.imdb.com/title/tt0068646/",
    ]


def test_sitemaps_bajan_al_hijo_y_filtran_lo_que_no_es_ficha():
    falso = FakeFetcher()
    encontradas = discovery.from_sitemaps(falso)
    assert set(encontradas) == {
        "https://www.imdb.com/title/tt0111161/",
        "https://www.imdb.com/title/tt0068646/",
    }


def test_el_catalogo_filtra_por_tipo_votos_y_año_y_ordena_por_popularidad():
    falso = FakeFetcher()
    encontradas = discovery.from_datasets(falso, min_votes=1000, min_year=1920)
    # tt9999999 no llega a los votos, tt1111111 es un episodio y tt2222222 es de 1899.
    assert encontradas == [
        "https://www.imdb.com/title/tt0111161/",   # 2,9 M de votos
        "https://www.imdb.com/title/tt0068646/",   # 2,0 M
    ]


def test_el_catalogo_respeta_el_tope():
    falso = FakeFetcher()
    assert discovery.from_datasets(falso, limit=1) == ["https://www.imdb.com/title/tt0111161/"]


def test_discover_junta_fuentes_conservando_la_prioridad():
    falso = FakeFetcher()
    todas = discovery.discover(falso, ["charts", "datasets", "sitemap"])
    assert todas[0] == "https://www.imdb.com/title/tt0111161/"
    assert len(todas) == len(set(todas))


def test_el_fetcher_lleva_la_cuenta_de_los_codigos_que_devuelve_el_origen(monkeypatch):
    """Un 'fallaron todas' sin codigos no es un diagnostico, es un misterio."""
    import requests

    from scraper.fetcher import Fetcher

    class RespuestaFalsa:
        def __init__(self, codigo):
            self.status_code = codigo
            self.headers = {}
            self.url = "https://www.imdb.com/title/tt0111161/"
            self.encoding = "utf-8"
            self.text = ""

        def close(self):
            pass

    fetcher = Fetcher(delay=0, retries=1, respect_robots=False)
    codigos = iter([403, 404, requests.ConnectionError("sin ruta")])

    def falsa(url, **kwargs):
        siguiente = next(codigos)
        if isinstance(siguiente, Exception):
            raise siguiente
        return RespuestaFalsa(siguiente)

    monkeypatch.setattr(fetcher.session, "get", falsa)

    for _ in range(3):
        assert fetcher.get("https://www.imdb.com/title/tt0111161/") is None

    assert fetcher.stats["statuses"] == {"403": 1, "404": 1, "ConnectionError": 1}
    assert fetcher.stats["errors"] == 3
