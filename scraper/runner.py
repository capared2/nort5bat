"""Tuberia: descubrir titulos, descargar fichas y guardarlas por genero."""
from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field

from . import config, discovery, seo
from . import urls as urlutil
from .fetcher import Fetcher
from .parser import parse_title
from .storage import RunState, TitleStore

log = logging.getLogger(__name__)

FLUSH_EVERY = 120
BATCH_SIZE = 60
# Descubrir es el medio, no el fin: no puede comerse la ejecucion entera o el
# run acabaria sin guardar una sola ficha.
DISCOVERY_SHARE = 0.35


@dataclass
class Options:
    mode: str = "incremental"
    sources: list[str] = field(default_factory=lambda: ["charts"])
    max_titles: int = 0                # 0 = sin limite
    workers: int = config.DEFAULT_WORKERS
    delay: float = config.DEFAULT_DELAY
    timeout: int = config.DEFAULT_TIMEOUT
    retries: int = config.DEFAULT_RETRIES
    shard_size: int = config.DEFAULT_SHARD_SIZE
    time_budget: int = config.DEFAULT_TIME_BUDGET
    types: tuple[str, ...] = config.DEFAULT_TYPES
    min_votes: int = config.DEFAULT_MIN_VOTES
    min_year: int = config.DEFAULT_MIN_YEAR
    catalog_limit: int = 0             # tope de titulos que se sacan del catalogo
    include_adult: bool = False
    follow_similar: bool = True        # encolar los "titulos parecidos" de cada ficha
    refresh: int = 0                   # vuelve a pasar por las N fichas ya guardadas
    max_failures: int = 3
    site_url: str = config.SITE_URL
    discovery_share: float = DISCOVERY_SHARE
    data_dir: str = "data"
    state_dir: str = "state"
    user_agent: str = config.DEFAULT_USER_AGENT
    respect_robots: bool = True
    skip_discovery: bool = False


def _fetch_one(fetcher: Fetcher, url: str) -> tuple[str, dict | None]:
    resp = fetcher.get(url)
    if resp is None:
        return url, None
    if "html" not in resp.content_type.lower() and "<html" not in resp.text[:2000].lower():
        return url, None
    try:
        return url, parse_title(resp.text, resp.url)
    except Exception:  # una ficha rota no puede tumbar la ejecucion entera
        log.exception("fallo al parsear %s", url)
        return url, None


def _refrescar(state: RunState, cuantas: int) -> int:
    """Devuelve a la cola las fichas mas antiguas ya guardadas.

    Las notas y los votos de IMDb se mueven todos los dias; sin esto el dataset
    envejeceria aunque el scraper siguiera corriendo.
    """
    if cuantas <= 0 or not state.seen:
        return 0
    candidatas = sorted(state.seen)[:cuantas]
    state.forget(candidatas)
    state.requeue(candidatas)
    log.info("refresco: %s fichas vuelven a la cola", len(candidatas))
    return len(candidatas)


def run(options: Options) -> dict:
    empezado = time.monotonic()
    fetcher = Fetcher(
        user_agent=options.user_agent,
        delay=options.delay,
        timeout=options.timeout,
        retries=options.retries,
        respect_robots=options.respect_robots,
    )
    store = TitleStore(options.data_dir, options.shard_size)
    state = RunState(options.state_dir, max_failures=options.max_failures)

    resumen = {
        "mode": options.mode,
        "discovered": 0,
        "queued": 0,
        "refreshed": 0,
        "fetched": 0,
        "saved": 0,
        "failed": 0,
        "genres": {},
    }

    try:
        limite_tiempo = empezado + options.time_budget if options.time_budget else None
        limite_descubrir = (
            empezado + options.time_budget * options.discovery_share
            if options.time_budget
            else None
        )

        resumen["refreshed"] = _refrescar(state, options.refresh)

        if not options.skip_discovery:
            encontradas = discovery.discover(
                fetcher,
                options.sources,
                types=options.types,
                min_votes=options.min_votes,
                min_year=options.min_year,
                limit=options.catalog_limit,
                include_adult=options.include_adult,
                deadline=limite_descubrir,
            )
            resumen["discovered"] = len(encontradas)
            resumen["queued"] = state.enqueue(encontradas)
            log.info(
                "encoladas %s URLs nuevas (%s ya conocidas)",
                resumen["queued"], len(encontradas) - resumen["queued"],
            )

        tope = options.max_titles if options.max_titles > 0 else float("inf")
        desde_volcado = 0

        while state.pending and resumen["fetched"] < tope:
            if limite_tiempo is not None and time.monotonic() > limite_tiempo:
                log.info(
                    "agotado el presupuesto de %ss; quedan %s URLs en cola",
                    options.time_budget, len(state.pending),
                )
                break

            restantes = tope - resumen["fetched"]
            lote = state.take(int(min(BATCH_SIZE, restantes)))
            if not lote:
                break

            parecidos: list[str] = []
            with ThreadPoolExecutor(max_workers=options.workers) as pool:
                futuros = {pool.submit(_fetch_one, fetcher, url): url for url in lote}
                for futuro in as_completed(futuros):
                    url, ficha = futuro.result()
                    resumen["fetched"] += 1
                    if ficha is None:
                        resumen["failed"] += 1
                        state.mark_failed(url)
                        continue
                    store.add(ficha)
                    state.mark_seen(url)
                    state.mark_seen(ficha["url"])
                    resumen["saved"] += 1
                    desde_volcado += 1
                    if options.follow_similar:
                        parecidos.extend(urlutil.title_url(t) for t in ficha.get("similar", []))

            # Los "titulos parecidos" van al final de la cola: primero lo que se
            # pidio expresamente, y de propina el vecindario de cada pelicula.
            if parecidos:
                state.enqueue(parecidos)

            if desde_volcado >= FLUSH_EVERY:
                for genero, cuantas in store.flush().items():
                    resumen["genres"][genero] = resumen["genres"].get(genero, 0) + cuantas
                state.save()
                desde_volcado = 0
                log.info(
                    "progreso: %s guardadas, %s pendientes, %s peticiones",
                    resumen["saved"], len(state.pending), fetcher.stats["requests"],
                )

    finally:
        for genero, cuantas in store.flush().items():
            resumen["genres"][genero] = resumen["genres"].get(genero, 0) + cuantas
        indice = store.rebuild_index()
        resumen["seo"] = seo.construir(
            options.data_dir, options.site_url, store.sitemap_entries, indice["genres"]
        )
        resumen["total_titles"] = indice["total_titles"]
        resumen["total_genres"] = indice["total_genres"]
        resumen["duration_seconds"] = round(time.monotonic() - empezado, 1)
        resumen["http"] = dict(fetcher.stats)
        state.save({"last_run": resumen})
        fetcher.close()

    return resumen
