"""Tuberia: descubrir peliculas, descargar fichas y guardarlas por genero."""
from __future__ import annotations

import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field

from . import config, discovery, seo
from . import urls as urlutil
from .fetcher import Fetcher
from .parser import parse_movie
from .storage import RunState, TitleStore

log = logging.getLogger(__name__)

FLUSH_EVERY = 120
BATCH_SIZE = 40
# Descubrir es el medio, no el fin: no puede comerse la ejecucion entera o el
# run acabaria sin guardar una sola ficha.
DISCOVERY_SHARE = 0.3


@dataclass
class Options:
    mode: str = "incremental"
    sources: list[str] = field(default_factory=lambda: ["browse"])
    max_titles: int = 0                # 0 = sin limite
    workers: int = config.DEFAULT_WORKERS
    delay: float = config.DEFAULT_DELAY
    timeout: int = config.DEFAULT_TIMEOUT
    retries: int = config.DEFAULT_RETRIES
    shard_size: int = config.DEFAULT_SHARD_SIZE
    time_budget: int = config.DEFAULT_TIME_BUDGET
    min_votes: int = config.DEFAULT_MIN_VOTES
    follow_related: bool = True        # encolar las peliculas que enlaza cada ficha
    refresh: int = 0                   # vuelve a pasar por las N fichas mas antiguas
    max_failures: int = 3
    site_url: str = config.SITE_URL
    discovery_share: float = DISCOVERY_SHARE
    data_dir: str = "data"
    state_dir: str = "state"
    user_agent: str = config.DEFAULT_USER_AGENT
    respect_robots: bool = True
    skip_discovery: bool = False


def _fetch_one(fetcher: Fetcher, url: str) -> tuple[str, dict | None, list[str]]:
    """Descarga y parsea una ficha, y de paso recoge a que peliculas enlaza.

    Los vecinos salen de la misma pagina que ya se ha pedido, asi que crecer
    por vecindad no cuesta ni una peticion mas.
    """
    resp = fetcher.get(url)
    if resp is None:
        return url, None, []
    if "html" not in resp.content_type.lower() and "<html" not in resp.text[:2000].lower():
        return url, None, []
    try:
        ficha = parse_movie(resp.text, resp.url)
    except Exception:  # una ficha rota no puede tumbar la ejecucion entera
        log.exception("fallo al parsear %s", url)
        return url, None, []
    vecinos = discovery._slugs_en(resp.text) if ficha else []
    return url, ficha, vecinos


def _refrescar(state: RunState, cuantas: int) -> int:
    """Devuelve a la cola el siguiente tramo del archivo, para releerlo.

    Las notas y los porcentajes de Rotten Tomatoes se mueven a diario. El tramo
    va rotando entre ejecuciones: repasar siempre el mismo dejaria el resto del
    archivo envejeciendo sin que nadie lo mirase.
    """
    candidatas = state.rotar(cuantas)
    if not candidatas:
        return 0
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
        "skipped_thin": 0,
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
            encontradas = discovery.discover(fetcher, options.sources, deadline=limite_descubrir)
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

            vecinos: list[str] = []
            with ThreadPoolExecutor(max_workers=options.workers) as pool:
                futuros = {pool.submit(_fetch_one, fetcher, url): url for url in lote}
                for futuro in as_completed(futuros):
                    url, ficha, cercanas = futuro.result()
                    resumen["fetched"] += 1
                    if ficha is None:
                        resumen["failed"] += 1
                        state.mark_failed(url)
                        continue
                    # Una pelicula sin publico ni nota no aporta nada a un
                    # agregador: se da por vista para no volver a pedirla.
                    if options.min_votes and (ficha.get("votes") or 0) < options.min_votes:
                        resumen["skipped_thin"] += 1
                        state.mark_seen(url)
                        continue
                    store.add(ficha)
                    state.mark_seen(url)
                    state.mark_seen(ficha["url"])
                    resumen["saved"] += 1
                    desde_volcado += 1
                    if options.follow_related:
                        vecinos.extend(cercanas)

            # Los vecinos van al final de la cola: primero lo que se pidio
            # expresamente, y de propina el barrio de cada pelicula.
            if vecinos:
                state.enqueue(urlutil.movie_url(slug) for slug in dict.fromkeys(vecinos))

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
