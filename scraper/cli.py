"""Punto de entrada: ``python -m scraper``."""
from __future__ import annotations

import argparse
import json
import logging
import sys

from . import config
from .runner import Options, run

SOURCES = ("charts", "datasets", "sitemap")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="scraper",
        description="Scrapea fichas de imdb.com y las guarda en JSON por genero.",
    )
    parser.add_argument(
        "--mode",
        choices=("catalogo", "incremental", "full"),
        default="catalogo",
        help=(
            "catalogo: fichas desde los datasets publicos, sin pedir paginas "
            "(el unico modo que IMDb permite hoy). incremental y full recogen "
            "el HTML de las fichas, que IMDb responde con un 202."
        ),
    )
    parser.add_argument(
        "--sources",
        default="",
        help=f"fuentes separadas por coma: {','.join(SOURCES)} (por defecto segun --mode)",
    )
    parser.add_argument("--max-titles", type=int, default=0, help="0 = sin limite")
    parser.add_argument("--workers", type=int, default=config.DEFAULT_WORKERS)
    parser.add_argument("--delay", type=float, default=config.DEFAULT_DELAY,
                        help="segundos entre peticiones")
    parser.add_argument("--timeout", type=int, default=config.DEFAULT_TIMEOUT)
    parser.add_argument("--retries", type=int, default=config.DEFAULT_RETRIES)
    parser.add_argument("--shard-size", type=int, default=config.DEFAULT_SHARD_SIZE,
                        help="fichas por archivo JSON")
    parser.add_argument("--time-budget", type=int, default=config.DEFAULT_TIME_BUDGET,
                        help="segundos maximos de ejecucion (0 = sin limite)")
    parser.add_argument("--types", default=",".join(config.DEFAULT_TYPES),
                        help=f"tipos de titulo del catalogo: {','.join(config.KNOWN_TYPES)}")
    parser.add_argument("--min-votes", type=int, default=config.DEFAULT_MIN_VOTES,
                        help="votos minimos para entrar en el catalogo")
    parser.add_argument("--min-year", type=int, default=config.DEFAULT_MIN_YEAR,
                        help="descarta titulos anteriores a este año")
    parser.add_argument("--catalog-limit", type=int, default=0,
                        help="tope de titulos que se sacan del catalogo (0 = todos)")
    parser.add_argument("--include-adult", action="store_true",
                        help="incluye los titulos marcados como adultos")
    parser.add_argument("--tmdb-key", default=config.TMDB_API_KEY,
                        help="clave de TMDB, de donde salen las caratulas (o variable TMDB_API_KEY)")
    parser.add_argument("--tmdb-limit", type=int, default=4000,
                        help="consultas nuevas a TMDB por ejecucion (0 = sin tope)")
    parser.add_argument("--no-cast", action="store_true",
                        help="en modo catalogo, no bajar reparto ni equipo (dos ficheros menos)")
    parser.add_argument("--no-similar", action="store_true",
                        help="no encolar los titulos parecidos de cada ficha")
    parser.add_argument("--refresh", type=int, default=0,
                        help="vuelve a pasar por N fichas ya guardadas para actualizar notas")
    parser.add_argument("--max-failures", type=int, default=3,
                        help="intentos por URL antes de descartarla")
    parser.add_argument("--site-url", default=config.SITE_URL,
                        help="dominio publico del sitio, usado en los sitemaps")
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--state-dir", default="state")
    parser.add_argument("--user-agent", default=config.DEFAULT_USER_AGENT)
    parser.add_argument("--ignore-robots", action="store_true",
                        help="no recomendado: ignora robots.txt")
    parser.add_argument("--skip-discovery", action="store_true",
                        help="solo procesa la cola pendiente, sin buscar URLs nuevas")
    parser.add_argument("--summary-file", default=None,
                        help="escribe el resumen del run en este JSON")
    parser.add_argument("-v", "--verbose", action="store_true")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)

    logging.basicConfig(
        level=logging.DEBUG if args.verbose else logging.INFO,
        format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
        stream=sys.stdout,
    )

    if args.sources.strip():
        sources = [s.strip() for s in args.sources.split(",") if s.strip()]
        desconocidas = [s for s in sources if s not in SOURCES]
        if desconocidas:
            print(f"fuentes desconocidas: {', '.join(desconocidas)}", file=sys.stderr)
            return 2
    elif args.mode == "full":
        sources = ["charts", "datasets"]
    else:
        sources = ["charts"]

    tipos = tuple(t.strip() for t in args.types.split(",") if t.strip())
    desconocidos = [t for t in tipos if t not in config.KNOWN_TYPES]
    if desconocidos:
        print(f"tipos desconocidos: {', '.join(desconocidos)}", file=sys.stderr)
        return 2

    options = Options(
        mode=args.mode,
        sources=sources,
        max_titles=args.max_titles,
        workers=args.workers,
        delay=args.delay,
        timeout=args.timeout,
        retries=args.retries,
        shard_size=args.shard_size,
        time_budget=args.time_budget,
        types=tipos,
        min_votes=args.min_votes,
        min_year=args.min_year,
        catalog_limit=args.catalog_limit,
        include_adult=args.include_adult,
        with_cast=not args.no_cast,
        tmdb_key=args.tmdb_key,
        tmdb_limit=args.tmdb_limit,
        follow_similar=not args.no_similar,
        refresh=args.refresh,
        max_failures=args.max_failures,
        site_url=args.site_url,
        data_dir=args.data_dir,
        state_dir=args.state_dir,
        user_agent=args.user_agent,
        respect_robots=not args.ignore_robots,
        skip_discovery=args.skip_discovery,
    )

    resumen = run(options)
    rendido = json.dumps(resumen, ensure_ascii=False, indent=2)
    print("\n=== RESUMEN ===")
    print(rendido)

    if args.summary_file:
        with open(args.summary_file, "w", encoding="utf-8") as handle:
            handle.write(rendido + "\n")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
