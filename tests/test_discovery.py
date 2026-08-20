from scraper import discovery
from tests.fake_site import FakeFetcher


def test_los_listados_dan_peliculas_sin_repetir_ni_colar_series():
    falso = FakeFetcher()
    encontradas = discovery.from_browse(falso, seeds=["/browse/movies_at_home/sort:popular"])
    assert encontradas == [
        "https://www.rottentomatoes.com/m/the_godfather",
        "https://www.rottentomatoes.com/m/goodfellas",
    ]


def test_los_sitemaps_bajan_al_hijo_y_filtran_lo_que_no_es_ficha():
    falso = FakeFetcher()
    encontradas = discovery.from_sitemaps(falso)
    assert set(encontradas) == {
        "https://www.rottentomatoes.com/m/the_godfather",
        "https://www.rottentomatoes.com/m/casablanca",
    }


def test_discover_junta_fuentes_sin_duplicar():
    falso = FakeFetcher()
    todas = discovery.discover(falso, ["browse", "sitemap"])
    assert todas[0] == "https://www.rottentomatoes.com/m/the_godfather"
    assert len(todas) == len(set(todas))


def test_los_slugs_salen_del_html_crudo():
    """Los listados pintan sus tarjetas desde un JSON, no desde etiquetas <a>."""
    crudo = '{"url":"/m/dune_part_two","otro":"/m/oppenheimer?cmp=x"} <a href="/m/barbie">'
    assert discovery._slugs_en(crudo) == ["dune_part_two", "oppenheimer", "barbie"]


def test_el_fetcher_lleva_la_cuenta_de_los_codigos_que_devuelve_el_origen(monkeypatch):
    """Un 'fallaron todas' sin codigos no es un diagnostico, es un misterio."""
    import requests

    from scraper.fetcher import Fetcher

    class RespuestaFalsa:
        def __init__(self, codigo):
            self.status_code = codigo
            self.headers = {}
            self.url = "https://www.rottentomatoes.com/m/x"
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
        assert fetcher.get("https://www.rottentomatoes.com/m/x") is None

    assert fetcher.stats["statuses"] == {"403": 1, "404": 1, "ConnectionError": 1}
