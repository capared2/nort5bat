"""Un imdb.com de mentira para poder probar la tuberia sin salir a la red."""
from pathlib import Path

from scraper.fetcher import Response

TITLE_HTML = (Path(__file__).parent / "fixtures" / "title.html").read_text(encoding="utf-8")

SITEMAP_INDEX = """<?xml version="1.0" encoding="UTF-8"?>
<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <sitemap><loc>https://www.imdb.com/sitemap/titles-1.xml</loc></sitemap>
</sitemapindex>"""

SITEMAP_URLS = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://www.imdb.com/title/tt0111161/</loc></url>
  <url><loc>https://www.imdb.com/title/tt0068646/?ref_=sm</loc></url>
  <url><loc>https://www.imdb.com/title/tt0111161/fullcredits/</loc></url>
  <url><loc>https://www.imdb.com/name/nm0000209/</loc></url>
</urlset>"""

CHART_HTML = """<html><body>
  <a href="/title/tt0111161/?ref_=chttp_t_1">Cadena perpetua</a>
  <a href="/title/tt0068646/?ref_=chttp_t_2">El padrino</a>
  <a href="/title/tt0111161/?ref_=chttp_t_1">repetida</a>
  <a href="/name/nm0000209/">Tim Robbins</a>
</body></html>"""

RATINGS_TSV = [
    "tconst\taverageRating\tnumVotes",
    "tt0111161\t9.3\t2900000",
    "tt0068646\t9.2\t2000000",
    "tt9999999\t7.1\t12",          # no llega al minimo de votos
]

AKAS_TSV = [
    "titleId\tordering\ttitle\tregion\tlanguage\ttypes\tattributes\tisOriginalTitle",
    "tt0111161\t1\tCadena perpetua\tES\t\\N\timdbDisplay\t\\N\t0",
    "tt0111161\t2\tSuenos de fuga\tMX\t\\N\timdbDisplay\t\\N\t0",
    "tt0068646\t1\tEl padrino\t\\N\tes\timdbDisplay\t\\N\t0",
]

CREW_TSV = [
    "tconst\tdirectors\twriters",
    "tt0111161\tnm0001104\tnm0000175,nm0001104",
    "tt0068646\tnm0000338\tnm0000338",
]

PRINCIPALS_TSV = [
    "tconst\tordering\tnconst\tcategory\tjob\tcharacters",
    'tt0111161\t1\tnm0000209\tactor\t\\N\t["Andy Dufresne"]',
    'tt0111161\t2\tnm0000151\tactor\t\\N\t["Ellis Boyd \'Red\' Redding"]',
    "tt0111161\t3\tnm0001104\tdirector\t\\N\t\\N",
    'tt0068646\t1\tnm0000008\tactor\t\\N\t["Don Vito Corleone"]',
]

NAMES_TSV = [
    "nconst\tprimaryName\tbirthYear\tdeathYear\tprimaryProfession\tknownForTitles",
    "nm0000209\tTim Robbins\t1958\t\\N\tactor\ttt0111161",
    "nm0000151\tMorgan Freeman\t1937\t\\N\tactor\ttt0111161",
    "nm0001104\tFrank Darabont\t1959\t\\N\twriter\ttt0111161",
    "nm0000175\tStephen King\t1947\t\\N\twriter\ttt0111161",
    "nm0000338\tFrancis Ford Coppola\t1939\t\\N\tdirector\ttt0068646",
]

BASICS_TSV = [
    "tconst\ttitleType\tprimaryTitle\toriginalTitle\tisAdult\tstartYear\tendYear\truntimeMinutes\tgenres",
    "tt0111161\tmovie\tThe Shawshank Redemption\tThe Shawshank Redemption\t0\t1994\t\\N\t142\tDrama",
    "tt0068646\tmovie\tThe Godfather\tThe Godfather\t0\t1972\t\\N\t175\tCrime,Drama",
    "tt9999999\tmovie\tSin votos\tSin votos\t0\t2020\t\\N\t90\tDrama",
    "tt1111111\ttvEpisode\tUn capitulo\tUn capitulo\t0\t2015\t\\N\t45\tDrama",
    "tt2222222\tmovie\tMuy antigua\tMuy antigua\t0\t1899\t\\N\t10\tShort",
]


class FakeFetcher:
    """Implementa la superficie de Fetcher que usa la tuberia."""

    def __init__(self, fallos: set[str] | None = None):
        self.fallos = fallos or set()
        self.pedidas: list[str] = []
        self.stats = {"requests": 0, "errors": 0, "blocked": 0}
        self.limiter = None

    # -- helpers ----------------------------------------------------------
    def _respuesta(self, url: str, texto: str, tipo: str = "text/html") -> Response:
        return Response(url=url, status=200, text=texto, content_type=tipo)

    # -- superficie de Fetcher -------------------------------------------
    def sitemaps_from_robots(self, origin: str) -> list[str]:
        return ["https://www.imdb.com/sitemap/index.xml"]

    def get(self, url: str) -> Response | None:
        self.pedidas.append(url)
        self.stats["requests"] += 1
        if url in self.fallos:
            self.stats["errors"] += 1
            return None
        if "/chart/" in url:
            return self._respuesta(url, CHART_HTML)
        if "/title/" in url:
            return self._respuesta(url, TITLE_HTML)
        return None

    def get_xml(self, url: str) -> Response | None:
        self.pedidas.append(url)
        self.stats["requests"] += 1
        if url.endswith("index.xml"):
            return self._respuesta(url, SITEMAP_INDEX, "application/xml")
        if url.endswith("titles-1.xml"):
            return self._respuesta(url, SITEMAP_URLS, "application/xml")
        return None

    def stream_lines(self, url: str):
        self.pedidas.append(url)
        self.stats["requests"] += 1
        for marca, lineas in (
            ("ratings", RATINGS_TSV),
            ("akas", AKAS_TSV),
            ("crew", CREW_TSV),
            ("principals", PRINCIPALS_TSV),
            ("name.basics", NAMES_TSV),
            ("basics", BASICS_TSV),
        ):
            if marca in url:
                yield from lineas
                return

    def close(self) -> None:
        pass
