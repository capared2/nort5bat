"""Construye fichas a partir de los datasets publicos de IMDb.

IMDb responde 202 a cualquier cliente automatico que pida sus paginas, asi que
las fichas no se pueden recoger del HTML. Los datasets que la propia IMDb
publica si estan abiertos, y traen lo esencial de cada pelicula: titulo,
titulo traducido, año, duracion, generos, nota, votos, direccion, guion y
reparto con sus personajes.

Lo que no traen es la caratula, la sinopsis y el trailer. Esos campos quedan
vacios y el sitio los da por ausentes.

Los ficheros son enormes (el de reparto pasa de los dos gigas sin comprimir),
asi que se recorren en streaming y se cruza todo contra el conjunto de
titulos ya seleccionado, que cabe de sobra en memoria.
"""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone

from . import config
from . import urls as urlutil
from .fetcher import Fetcher

log = logging.getLogger(__name__)

NULO = "\\N"
MAX_REPARTO = 15
# Como se llaman en los datasets los papeles que nos interesan.
PAPELES_REPARTO = {"actor", "actress", "self"}

# Idiomas y regiones de los que se acepta el titulo traducido, en este orden.
REGIONES_ES = ("ES", "MX", "AR", "CO")


def _campos(linea: str, cuantos: int) -> list[str] | None:
    partes = linea.split("\t")
    return partes if len(partes) >= cuantos else None


def _entero(valor: str) -> int | None:
    return int(valor) if valor.isdigit() else None


def _url(nombre: str) -> str:
    return f"{config.DATASET_BASE_URL.rstrip('/')}/{nombre}"


def _seleccionar(
    fetcher: Fetcher,
    tipos: tuple[str, ...],
    min_votos: int,
    min_anio: int,
    limite: int,
    incluir_adulto: bool,
) -> dict[str, dict]:
    """Las peliculas que entran en el catalogo, ya con nota, votos y generos."""
    votos: dict[str, tuple[float, int]] = {}
    for numero, linea in enumerate(fetcher.stream_lines(_url(config.DATASET_RATINGS))):
        if numero == 0:
            continue
        partes = _campos(linea, 3)
        if not partes:
            continue
        try:
            cuantos = int(partes[2])
        except ValueError:
            continue
        if cuantos >= min_votos:
            try:
                votos[partes[0]] = (float(partes[1]), cuantos)
            except ValueError:
                continue
    log.info("ratings: %s titulos con %s votos o mas", len(votos), min_votos)

    candidatas: list[tuple[int, str, dict]] = []
    conjunto = set(tipos)
    for numero, linea in enumerate(fetcher.stream_lines(_url(config.DATASET_BASICS))):
        if numero == 0:
            continue
        partes = _campos(linea, 9)
        if not partes:
            continue
        tconst, tipo, titulo, original, adulto, desde, hasta, duracion, generos = partes[:9]
        if tipo not in conjunto or tconst not in votos:
            continue
        if not incluir_adulto and adulto == "1":
            continue
        anio = _entero(desde)
        if anio is None or anio < min_anio:
            continue

        nota, cuantos = votos[tconst]
        lista = [g for g in generos.split(",") if g and g != NULO]
        candidatas.append((
            cuantos,
            tconst,
            {
                "id": tconst,
                "url": urlutil.title_url(tconst),
                "category": urlutil.category_key(lista),
                "type": tipo,
                "title": titulo,
                "original_title": original if original != NULO else titulo,
                "genres": [g for g in lista if urlutil.genre_slug(g)],
                "year": anio,
                "end_year": _entero(hasta),
                "runtime_minutes": _entero(duracion),
                "rating": nota,
                "votes": cuantos,
            },
        ))

    candidatas.sort(key=lambda fila: -fila[0])
    if limite > 0:
        candidatas = candidatas[:limite]
    log.info("basics: %s titulos seleccionados", len(candidatas))
    return {tconst: ficha for _, tconst, ficha in candidatas}


def _titulos_traducidos(fetcher: Fetcher, elegidas: dict[str, dict]) -> None:
    """Pone el titulo en castellano cuando el dataset de alias lo tiene."""
    mejor: dict[str, tuple[int, str]] = {}
    for numero, linea in enumerate(fetcher.stream_lines(_url(config.DATASET_AKAS))):
        if numero == 0:
            continue
        partes = _campos(linea, 8)
        if not partes:
            continue
        tconst, _orden, titulo, region, idioma = partes[:5]
        if tconst not in elegidas or titulo == NULO:
            continue
        # Se prefiere España, luego el resto de regiones, y por ultimo
        # cualquier alias declarado en español.
        if region in REGIONES_ES:
            prioridad = REGIONES_ES.index(region)
        elif idioma == "es":
            prioridad = len(REGIONES_ES)
        else:
            continue
        actual = mejor.get(tconst)
        if actual is None or prioridad < actual[0]:
            mejor[tconst] = (prioridad, titulo)

    for tconst, (_prioridad, titulo) in mejor.items():
        elegidas[tconst]["title"] = titulo
    log.info("akas: %s titulos con nombre en castellano", len(mejor))


def _equipo_y_reparto(fetcher: Fetcher, elegidas: dict[str, dict]) -> set[str]:
    """Rellena direccion, guion y reparto. Devuelve los identificadores de persona."""
    necesarios: set[str] = set()

    for numero, linea in enumerate(fetcher.stream_lines(_url(config.DATASET_CREW))):
        if numero == 0:
            continue
        partes = _campos(linea, 3)
        if not partes or partes[0] not in elegidas:
            continue
        tconst, directores, guionistas = partes[:3]
        ficha = elegidas[tconst]
        ficha["_directores"] = [n for n in directores.split(",") if n and n != NULO][:4]
        ficha["_guionistas"] = [n for n in guionistas.split(",") if n and n != NULO][:4]
        necesarios.update(ficha["_directores"])
        necesarios.update(ficha["_guionistas"])
    log.info("crew: equipo de %s titulos", sum(1 for f in elegidas.values() if "_directores" in f))

    for numero, linea in enumerate(fetcher.stream_lines(_url(config.DATASET_PRINCIPALS))):
        if numero == 0:
            continue
        partes = _campos(linea, 6)
        if not partes or partes[0] not in elegidas:
            continue
        tconst, _orden, nconst, categoria, _trabajo, personajes = partes[:6]
        if categoria not in PAPELES_REPARTO:
            continue
        reparto = elegidas[tconst].setdefault("_reparto", [])
        if len(reparto) >= MAX_REPARTO:
            continue
        nombre_personaje = ""
        if personajes != NULO:
            try:
                lista = json.loads(personajes)
                nombre_personaje = lista[0] if lista else ""
            except (ValueError, TypeError):
                nombre_personaje = ""
        reparto.append({"id": nconst, "character": nombre_personaje})
        necesarios.add(nconst)
    log.info("principals: reparto de %s titulos", sum(1 for f in elegidas.values() if "_reparto" in f))

    return necesarios


def _nombres(fetcher: Fetcher, necesarios: set[str]) -> dict[str, str]:
    nombres: dict[str, str] = {}
    for numero, linea in enumerate(fetcher.stream_lines(_url(config.DATASET_NAMES))):
        if numero == 0:
            continue
        partes = _campos(linea, 2)
        if not partes or partes[0] not in necesarios:
            continue
        nombres[partes[0]] = partes[1]
    log.info("names: %s personas resueltas de %s", len(nombres), len(necesarios))
    return nombres


def _rematar(ficha: dict, nombres: dict[str, str]) -> dict:
    """Deja la ficha con la misma forma que produce el parseo del HTML."""
    def gente(claves) -> list[dict]:
        salida = []
        for clave in claves or []:
            nombre = nombres.get(clave)
            if nombre:
                salida.append({"id": clave, "name": nombre})
        return salida

    reparto = []
    for quien in ficha.pop("_reparto", []):
        nombre = nombres.get(quien["id"])
        if nombre:
            reparto.append(
                {"id": quien["id"], "name": nombre, "character": quien["character"], "image": None}
            )

    completa = dict(ficha)
    completa.update(
        {
            "directors": gente(ficha.pop("_directores", None)),
            "writers": gente(ficha.pop("_guionistas", None)),
            "cast": reparto,
            # Lo que los datasets no traen. El sitio los da por ausentes.
            "release_date": None,
            "certificate": None,
            "metascore": None,
            "plot": "",
            "tagline": "",
            "poster": None,
            "images": [],
            "trailer": None,
            "keywords": [],
            "countries": [],
            "languages": [],
            "companies": [],
            "budget": None,
            "gross_worldwide": None,
            "similar": [],
            "source": "imdb-datasets",
            "scraped_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        }
    )
    completa.pop("_directores", None)
    completa.pop("_guionistas", None)
    return completa


def construir(
    fetcher: Fetcher,
    tipos: tuple[str, ...] = config.DEFAULT_TYPES,
    min_votos: int = config.DEFAULT_MIN_VOTES,
    min_anio: int = config.DEFAULT_MIN_YEAR,
    limite: int = 0,
    incluir_adulto: bool = False,
    con_reparto: bool = True,
) -> list[dict]:
    """El catalogo entero, ya en forma de fichas listas para guardar."""
    elegidas = _seleccionar(fetcher, tipos, min_votos, min_anio, limite, incluir_adulto)
    if not elegidas:
        log.warning("los datasets no devolvieron ningun titulo")
        return []

    _titulos_traducidos(fetcher, elegidas)

    nombres: dict[str, str] = {}
    if con_reparto:
        necesarios = _equipo_y_reparto(fetcher, elegidas)
        if necesarios:
            nombres = _nombres(fetcher, necesarios)

    return [_rematar(ficha, nombres) for ficha in elegidas.values()]
