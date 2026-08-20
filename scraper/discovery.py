"""Encontrar fichas: datasets oficiales, listas publicas y sitemaps."""
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
MAX_SITEMAP_FILES = 60      # techo de ficheros de sitemap por ejecucion
TCONST_RE = re.compile(r"/title/(tt\d{7,10})")
NULO = "\\N"


def _expired(deadline: float | None) -> bool:
    return deadline is not None and time.monotonic() >= deadline


# --- datasets oficiales -------------------------------------------------

def _ratings(fetcher: Fetcher, min_votes: int, deadline: float | None) -> dict[str, int]:
    """``tconst -> numero de votos``, quedandose solo con lo que la gente ha visto.

    Es el filtro que hace manejable el catalogo: de los once millones de
    registros de IMDb, la inmensa mayoria no tiene una sola valoracion.
    """
    url = f"{config.DATASET_BASE_URL.rstrip('/')}/{config.DATASET_RATINGS}"
    votos: dict[str, int] = {}
    for numero, linea in enumerate(fetcher.stream_lines(url)):
        if numero == 0:
            continue                      # cabecera
        if numero % 200_000 == 0 and _expired(deadline):
            log.info("ratings: se corta por tiempo tras %s lineas", numero)
            break
        partes = linea.split("\t")
        if len(partes) < 3:
            continue
        try:
            cuantos = int(partes[2])
        except ValueError:
            continue
        if cuantos >= min_votes:
            votos[partes[0]] = cuantos
    log.info("ratings: %s titulos con %s votos o mas", len(votos), min_votes)
    return votos


def from_datasets(
    fetcher: Fetcher,
    types: tuple[str, ...] = config.DEFAULT_TYPES,
    min_votes: int = config.DEFAULT_MIN_VOTES,
    min_year: int = config.DEFAULT_MIN_YEAR,
    limit: int = 0,
    include_adult: bool = False,
    deadline: float | None = None,
) -> list[str]:
    """Catalogo a partir de los datasets publicos de IMDb, de mas visto a menos.

    Devolverlo ordenado por votos importa: una ejecucion que se queda sin
    tiempo habra guardado antes "El padrino" que un telefilme de 1974.
    """
    votos = _ratings(fetcher, min_votes, deadline)
    if not votos:
        log.warning("los datasets no devolvieron valoraciones; no hay catalogo que filtrar")
        return []

    url = f"{config.DATASET_BASE_URL.rstrip('/')}/{config.DATASET_BASICS}"
    tipos = set(types)
    elegidos: list[tuple[int, str]] = []

    for numero, linea in enumerate(fetcher.stream_lines(url)):
        if numero == 0:
            continue
        if numero % 200_000 == 0 and _expired(deadline):
            log.info("basics: se corta por tiempo tras %s lineas", numero)
            break
        partes = linea.split("\t")
        if len(partes) < 9:
            continue
        tconst, tipo, _titulo, _original, adulto, desde = partes[:6]
        if tipo not in tipos:
            continue
        cuantos = votos.get(tconst)
        if cuantos is None:
            continue
        if not include_adult and adulto == "1":
            continue
        if desde == NULO or not desde.isdigit() or int(desde) < min_year:
            continue
        elegidos.append((cuantos, tconst))

    elegidos.sort(reverse=True)
    if limit > 0:
        elegidos = elegidos[:limit]
    log.info("datasets: %s titulos seleccionados", len(elegidos))
    return [urlutil.title_url(tconst) for _, tconst in elegidos]


# --- listas publicas ----------------------------------------------------

def _tconsts_en_html(texto: str) -> list[str]:
    """Los ``tt...`` que aparecen en una pagina, en el orden en que salen.

    Se busca sobre el HTML crudo: IMDb pinta sus listas desde un JSON incrustado
    y a veces los enlaces no llegan a existir como ``<a>``.
    """
    vistos: dict[str, None] = {}
    for tconst in TCONST_RE.findall(texto):
        vistos.setdefault(tconst, None)
    return list(vistos)


def from_charts(
    fetcher: Fetcher, seeds: list[str] | None = None, deadline: float | None = None
) -> list[str]:
    """Top 250, lo mas popular de la semana, taquilla... el pulso del sitio."""
    encontrados: dict[str, None] = {}
    for ruta in seeds if seeds is not None else config.CHART_SEEDS:
        if _expired(deadline):
            log.info("listas: se corta por tiempo")
            break
        pagina = urljoin(config.BASE_URL, ruta)
        resp = fetcher.get(pagina)
        if resp is None:
            continue
        antes = len(encontrados)
        for tconst in _tconsts_en_html(resp.text):
            encontrados.setdefault(tconst, None)
        log.info("lista %s -> %s titulos nuevos", ruta, len(encontrados) - antes)
    log.info("listas: %s titulos", len(encontrados))
    return [urlutil.title_url(t) for t in encontrados]


# --- sitemaps -----------------------------------------------------------

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
        if urlutil.is_title_url(candidata):
            if candidata not in salida:
                nuevos += 1
            salida.setdefault(candidata, None)
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

    log.info("sitemaps: %s fichas", len(salida))
    return list(salida)


# --- orquestacion -------------------------------------------------------

def discover(
    fetcher: Fetcher,
    sources: list[str],
    types: tuple[str, ...] = config.DEFAULT_TYPES,
    min_votes: int = config.DEFAULT_MIN_VOTES,
    min_year: int = config.DEFAULT_MIN_YEAR,
    limit: int = 0,
    include_adult: bool = False,
    deadline: float | None = None,
) -> list[str]:
    """Lanza cada fuente pedida y junta el resultado sin perder la prioridad.

    Las listas van primero porque son cuatro peticiones y traen justo lo que la
    gente esta buscando hoy; el catalogo completo va detras.
    """
    encontrados: dict[str, None] = {}

    if "charts" in sources:
        for url in from_charts(fetcher, deadline=deadline):
            encontrados.setdefault(url, None)
    if "datasets" in sources:
        for url in from_datasets(
            fetcher,
            types=types,
            min_votes=min_votes,
            min_year=min_year,
            limit=limit,
            include_adult=include_adult,
            deadline=deadline,
        ):
            encontrados.setdefault(url, None)
    if "sitemap" in sources:
        for url in from_sitemaps(fetcher, deadline=deadline):
            encontrados.setdefault(url, None)

    log.info("descubrimiento: %s URLs unicas", len(encontrados))
    return list(encontrados)
