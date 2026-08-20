"""Un Rotten Tomatoes de mentira para probar la tuberia sin salir a la red."""
from pathlib import Path

from scraper.fetcher import Response

PELICULA_HTML = (Path(__file__).parent / "fixtures" / "pelicula.html").read_text(encoding="utf-8")

LISTADO_HTML = """<html><body>
  <a href="/m/the_godfather?cmp=rt_x">El padrino</a>
  <a href="/m/goodfellas">Uno de los nuestros</a>
  <a href="/m/the_godfather">repetida</a>
  <a href="/celebrity/al_pacino">Al Pacino</a>
  <a href="/tv/the_sopranos">Los Soprano</a>
</body></html>"""

SITEMAP_INDEX = """<?xml version="1.0" encoding="UTF-8"?>
<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <sitemap><loc>https://www.rottentomatoes.com/sitemaps/peliculas-1.xml</loc></sitemap>
</sitemapindex>"""

SITEMAP_URLS = """<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url><loc>https://www.rottentomatoes.com/m/the_godfather</loc></url>
  <url><loc>https://www.rottentomatoes.com/m/casablanca</loc></url>
  <url><loc>https://www.rottentomatoes.com/m/the_godfather/reviews</loc></url>
  <url><loc>https://www.rottentomatoes.com/celebrity/al_pacino</loc></url>
</urlset>"""


class FakeFetcher:
    """Implementa la superficie de Fetcher que usa la tuberia."""

    def __init__(self, fallos: set[str] | None = None):
        self.fallos = fallos or set()
        self.pedidas: list[str] = []
        self.stats = {"requests": 0, "errors": 0, "blocked": 0, "statuses": {}}
        self.limiter = None

    def _respuesta(self, url: str, texto: str, tipo: str = "text/html") -> Response:
        return Response(url=url, status=200, text=texto, content_type=tipo)

    def sitemaps_from_robots(self, origin: str) -> list[str]:
        return ["https://www.rottentomatoes.com/sitemaps/sitemap.xml"]

    def get(self, url: str) -> Response | None:
        self.pedidas.append(url)
        self.stats["requests"] += 1
        if url in self.fallos:
            self.stats["errors"] += 1
            return None
        if "/browse/" in url:
            return self._respuesta(url, LISTADO_HTML)
        if "/m/" in url:
            return self._respuesta(url, PELICULA_HTML)
        return None

    def get_xml(self, url: str) -> Response | None:
        self.pedidas.append(url)
        self.stats["requests"] += 1
        if url.endswith("sitemap.xml"):
            return self._respuesta(url, SITEMAP_INDEX, "application/xml")
        if url.endswith("peliculas-1.xml"):
            return self._respuesta(url, SITEMAP_URLS, "application/xml")
        return None

    def close(self) -> None:
        pass
