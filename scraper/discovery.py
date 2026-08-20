"""Encontrar peliculas: paginas de listado y sitemaps."""
from __future__ import annotations

import logging
import re
import time
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from . import config
from . import urls as urlutil
from .fetcher import Fetcher

log = logging.getLogger(__name__)

MAX_SITEMAP_DEPTH = 3
MAX_SITEMAP_FILES = 40
# Las paginas de listado pintan sus tarjetas desde un JSON incrustado, asi que
# los enlaces no siempre existen como <a>: se busca sobre el HTML crudo.
SLUG_RE = re.compile(r'/m/([a-z0-9][a-z0-9_\-]*)(?=["\'/?#])', re.I)


def _expired(deadline: float | None) -> bool:
    return deadline is not None and time.monotonic() >= deadline


def _slugs_en(texto: str) -> list[str]:
    """Los slugs de pelicula que aparecen, en el orden en que salen."""
    vistos: dict[str, None] = {}
    for slug in SLUG_RE.findall(texto):
        minusculas = slug.lower()
        # Las subpaginas dejan rastros como "the_godfather/reviews"; el regex ya
        # corta en la barra, pero conviene descartar lo que no es una ficha.
        if minusculas not in config.MOVIE_SUBPAGES:
            vistos.setdefault(minusculas, None)
    return list(vistos)


def from_browse(
    fetcher: Fetcher, seeds: list[str] | None = None, deadline: float | None = None
) -> list[str]:
    """Lo popular, lo taquillero, lo certificado: el pulso del sitio."""
    encontrados: dict[str, None] = {}
    for ruta in seeds if seeds is not None else config.BROWSE_SEEDS:
        if _expired(deadline):
            log.info("listados: se corta por tiempo")
            break
        resp = fetcher.get(urljoin(config.BASE_URL, ruta))
        if resp is None:
            continue
        antes = len(encontrados)
        for slug in _slugs_en(resp.text):
            encontrados.setdefault(slug, None)
        log.info("listado %s -> %s peliculas nuevas", ruta, len(encontrados) - antes)
    log.info("listados: %s peliculas", len(encontrados))
    return [urlutil.movie_url(slug) for slug in encontrados]


def _recorrer_sitemap(
    fetcher: Fetcher,
    url: str,
    vistos: set[str],
    profundidad: int,
    salida: dict[str, None],
    deadline: float | None,
) -> None:
    if profundidad > MAX_SITEMAP_DEPTH or url in vistos or _expired(deadline):
        return
    if len(vistos) >= MAX_SITEMAP_FILES:
        return
    vistos.add(url)
    resp = fetcher.get_xml(url)
    if resp is None:
        return

    soup = BeautifulSoup(resp.text, "xml")
    hijos = [loc.get_text(strip=True) for loc in soup.select("sitemapindex > sitemap > loc")]
    for hijo in hijos:
        _recorrer_sitemap(fetcher, hijo, vistos, profundidad + 1, salida, deadline)

    nuevos = 0
    for loc in soup.select("urlset > url > loc"):
        candidata = urlutil.normalize(loc.get_text(strip=True))
        if urlutil.is_movie_url(candidata) and candidata not in salida:
            salida[candidata] = None
            nuevos += 1
    if nuevos or hijos:
        log.info("sitemap %s -> %s fichas, %s sitemaps hijos", url, nuevos, len(hijos))


def from_sitemaps(
    fetcher: Fetcher, extra: list[str] | None = None, deadline: float | None = None
) -> list[str]:
    salida: dict[str, None] = {}
    vistos: set[str] = set()

    raices = list(fetcher.sitemaps_from_robots(config.BASE_URL))
    raices += [urljoin(config.BASE_URL, ruta) for ruta in config.SITEMAP_CANDIDATES]
    raices += list(extra or [])

    for raiz in dict.fromkeys(raices):
        _recorrer_sitemap(fetcher, raiz, vistos, 0, salida, deadline)

    log.info("sitemaps: %s peliculas", len(salida))
    return list(salida)


def from_related(
    fetcher: Fetcher, urls: list[str], deadline: float | None = None
) -> list[str]:
    """Las peliculas que enlaza una ficha: el archivo crece por vecindad."""
    encontrados: dict[str, None] = {}
    for url in urls:
        if _expired(deadline):
            break
        resp = fetcher.get(url)
        if resp is None:
            continue
        for slug in _slugs_en(resp.text):
            encontrados.setdefault(slug, None)
    return [urlutil.movie_url(slug) for slug in encontrados]


def discover(
    fetcher: Fetcher,
    sources: list[str],
    deadline: float | None = None,
) -> list[str]:
    """Lanza cada fuente pedida y junta el resultado sin perder la prioridad."""
    encontrados: dict[str, None] = {}

    if "browse" in sources:
        for url in from_browse(fetcher, deadline=deadline):
            encontrados.setdefault(url, None)
    if "sitemap" in sources:
        for url in from_sitemaps(fetcher, deadline=deadline):
            encontrados.setdefault(url, None)

    log.info("descubrimiento: %s URLs unicas", len(encontrados))
    return list(encontrados)
