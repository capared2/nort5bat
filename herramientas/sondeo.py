"""Pregunta a un origen si nos deja entrar, y responde con hechos.

Construir un scraper para descubrir despues que el sitio contesta 202 cuesta
horas. Esto cuesta un minuto: usa el mismo cliente que el scraper —mismas
cabeceras, mismo trato con robots.txt— y dice, por cada URL, si robots la
permite, con que codigo responde y si la pagina trae los bloques de datos de
los que se puede sacar una ficha.

    python -m herramientas.sondeo https://www.rottentomatoes.com/m/the_godfather
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scraper.fetcher import Fetcher  # noqa: E402

CANDIDATAS = [
    "https://www.rottentomatoes.com/robots.txt",
    "https://www.rottentomatoes.com/m/the_godfather",
    "https://www.rottentomatoes.com/browse/movies_at_home/",
    "https://www.imdb.com/title/tt0068646/",
    "https://api.themoviedb.org/3/configuration",
]

# Señales de que una pagina trae datos estructurados aprovechables.
MARCADORES = {
    "json-ld": re.compile(r'type=["\']application/ld\+json', re.I),
    "__NEXT_DATA__": re.compile(r'id=["\']__NEXT_DATA__', re.I),
    "og:title": re.compile(r'property=["\']og:title', re.I),
    "score/rating": re.compile(r"(tomatometer|audienceScore|aggregateRating|ratingValue)", re.I),
    "muro anti-bot": re.compile(r"(captcha|are you a robot|access denied|unusual traffic|cf-browser)", re.I),
}


BLOQUES_JSON = re.compile(
    r'<script[^>]*id=["\']([^"\']+)["\'][^>]*type=["\']application/json["\'][^>]*>(.*?)</script>',
    re.I | re.S,
)
JSONLD = re.compile(r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', re.I | re.S)


def volcar(cuerpo: str, limite: int) -> None:
    """Enseña de que bloques de datos se puede sacar una ficha, y como son.

    Escribir un parser suponiendo la forma del HTML es lo que costo el ultimo
    intento; esto la enseña antes de escribir una linea.
    """
    for numero, crudo in enumerate(JSONLD.findall(cuerpo), start=1):
        print(f"\n--- JSON-LD #{numero} ({len(crudo)} b) ---")
        try:
            datos = json.loads(crudo.strip())
        except ValueError as exc:
            print(f"  ilegible: {exc}")
            continue
        print(json.dumps(datos, ensure_ascii=False, indent=2)[:limite])

    bloques = BLOQUES_JSON.findall(cuerpo)
    if bloques:
        print(f"\n--- otros bloques JSON incrustados: {len(bloques)} ---")
    for identificador, crudo in bloques:
        print(f"\n  [{identificador}] {len(crudo)} b")
        try:
            datos = json.loads(crudo.strip())
        except ValueError:
            continue
        if isinstance(datos, dict):
            print("    claves:", ", ".join(list(datos)[:20]))
        print("   ", json.dumps(datos, ensure_ascii=False)[:limite].replace("\n", " "))


def sondear(fetcher: Fetcher, url: str, mostrar: int = 0) -> dict:
    permitida = fetcher.allowed(url)
    informe = {"url": url, "robots_permite": permitida}

    # Se pide igualmente aunque robots diga que no: interesa saber las dos
    # cosas por separado, si nos prohibe y si ademas nos cierra la puerta.
    original = fetcher.respect_robots
    fetcher.respect_robots = False
    try:
        respuesta = fetcher.get(url)
    finally:
        fetcher.respect_robots = original

    if respuesta is None:
        informe["estado"] = fetcher.stats["statuses"]
        informe["resultado"] = "sin respuesta util"
        return informe

    cuerpo = respuesta.text
    if mostrar:
        volcar(cuerpo, mostrar)
    informe.update(
        {
            "estado": 200,
            "tipo": respuesta.content_type.split(";")[0],
            "bytes": len(cuerpo),
            "titulo": (re.search(r"<title[^>]*>([^<]{0,90})", cuerpo, re.I) or [None, ""])[1].strip(),
            "marcadores": sorted(n for n, patron in MARCADORES.items() if patron.search(cuerpo)),
        }
    )
    return informe


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="sondeo", description="Comprueba si un origen se deja recoger.")
    parser.add_argument("urls", nargs="*", default=[], help="URLs a sondear (por defecto, las candidatas)")
    parser.add_argument("--delay", type=float, default=1.0)
    parser.add_argument("--volcar", type=int, default=0, metavar="N",
                        help="enseña los bloques de datos de cada pagina, N caracteres de cada uno")
    args = parser.parse_args(argv)

    urls = args.urls or CANDIDATAS
    fetcher = Fetcher(delay=args.delay, retries=1)

    informes = []
    for url in urls:
        informe = sondear(fetcher, url, mostrar=args.volcar)
        informes.append(informe)
        origen = urlsplit(url).netloc
        estado = informe.get("estado")
        marcadores = ", ".join(informe.get("marcadores", [])) or "-"
        print(
            f"{origen:<26} robots={'si' if informe['robots_permite'] else 'NO':<3} "
            f"estado={str(estado):<28} {informe.get('bytes', 0):>8} b  {marcadores}"
        )
        if informe.get("titulo"):
            print(f"{'':<26} titulo: {informe['titulo']}")

    print("\n" + json.dumps(informes, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
