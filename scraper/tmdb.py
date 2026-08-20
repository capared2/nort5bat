"""Pone caratula, fondo y sinopsis a las fichas, preguntando a TMDB.

Los datasets de IMDb no traen una sola imagen, y las paginas de IMDb, que si
las tienen, responden 202 a cualquier cliente automatico. TMDB publica una API
gratuita que permite expresamente este uso y que, dado un identificador de
IMDb, devuelve la caratula, el fondo y la sinopsis en castellano.

Lo que se resuelve se guarda en ``state/tmdb.json``. El modo catalogo rehace
todas las fichas en cada ejecucion, asi que sin esa memoria cada run empezaria
de cero y el sitio no se llenaria nunca.
"""
from __future__ import annotations

import json
import logging
import threading
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import requests

from .fetcher import RateLimiter

log = logging.getLogger(__name__)

BASE = "https://api.themoviedb.org/3"
IMAGENES = "https://image.tmdb.org/t/p"
ANCHO_CARATULA = "w500"
ANCHO_FONDO = "w780"

# TMDB no publica un limite duro, pero pide un uso razonable. Veinte por
# segundo llena el catalogo en minutos sin apretar a nadie.
POR_SEGUNDO = 20
HILOS = 8


def _url_imagen(ruta: str | None, ancho: str) -> str | None:
    return f"{IMAGENES}/{ancho}{ruta}" if ruta else None


class Cache:
    """Lo ya resuelto en TMDB, para no volver a preguntarlo nunca."""

    def __init__(self, ruta: str | Path):
        self.ruta = Path(ruta)
        self.datos: dict[str, dict] = {}
        self._lock = threading.Lock()
        if self.ruta.exists():
            try:
                cargado = json.loads(self.ruta.read_text(encoding="utf-8"))
                if isinstance(cargado, dict):
                    self.datos = cargado
            except (OSError, ValueError) as exc:
                log.warning("cache de TMDB ilegible (%s); se empieza de cero", exc)

    def __contains__(self, tconst: str) -> bool:
        return tconst in self.datos

    def get(self, tconst: str) -> dict | None:
        return self.datos.get(tconst)

    def set(self, tconst: str, valor: dict) -> None:
        with self._lock:
            self.datos[tconst] = valor

    def guardar(self) -> None:
        self.ruta.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.ruta.with_suffix(".tmp")
        with self._lock:
            payload = dict(sorted(self.datos.items()))
        tmp.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        tmp.replace(self.ruta)

    @property
    def resueltos(self) -> int:
        return sum(1 for v in self.datos.values() if v.get("poster"))


def _consultar(sesion: requests.Session, freno: RateLimiter, clave: str, tconst: str) -> dict:
    """Lo que TMDB sabe de un identificador de IMDb. ``{}`` si no lo conoce."""
    freno.wait()
    try:
        respuesta = sesion.get(
            f"{BASE}/find/{tconst}",
            params={"external_source": "imdb_id", "language": "es-ES", "api_key": clave},
            timeout=20,
        )
    except requests.RequestException as exc:
        log.debug("TMDB no responde para %s: %s", tconst, exc)
        return {}

    if respuesta.status_code == 429:
        # Nos hemos pasado de ritmo: se espera lo que pidan y se deja para la
        # siguiente pasada, que la cache hara barata.
        time.sleep(float(respuesta.headers.get("Retry-After", 2)))
        return {}
    if respuesta.status_code != 200:
        log.debug("TMDB devuelve %s para %s", respuesta.status_code, tconst)
        return {}

    try:
        datos = respuesta.json()
    except ValueError:
        return {}

    for campo in ("movie_results", "tv_results"):
        resultados = datos.get(campo) or []
        if resultados:
            primero = resultados[0]
            return {
                "tmdb_id": primero.get("id"),
                "poster": _url_imagen(primero.get("poster_path"), ANCHO_CARATULA),
                "backdrop": _url_imagen(primero.get("backdrop_path"), ANCHO_FONDO),
                "plot": (primero.get("overview") or "").strip(),
            }
    # TMDB no lo conoce. Se recuerda igualmente para no volver a preguntar.
    return {"tmdb_id": None, "poster": None, "backdrop": None, "plot": ""}


def aplicar(ficha: dict, hallado: dict) -> None:
    """Vuelca sobre la ficha lo que haya traido TMDB, sin pisar lo que ya tenia."""
    if not hallado:
        return
    if hallado.get("poster") and not ficha.get("poster"):
        ficha["poster"] = hallado["poster"]
        imagenes = [{"url": hallado["poster"], "caption": ""}]
        if hallado.get("backdrop"):
            imagenes.append({"url": hallado["backdrop"], "caption": ""})
        ficha["images"] = imagenes
    if hallado.get("plot") and not ficha.get("plot"):
        ficha["plot"] = hallado["plot"]
    if hallado.get("tmdb_id"):
        ficha["tmdb_id"] = hallado["tmdb_id"]


def enriquecer(
    fichas: list[dict],
    clave: str,
    cache_path: str | Path,
    limite: int = 0,
    hilos: int = HILOS,
    por_segundo: int = POR_SEGUNDO,
    deadline: float | None = None,
) -> dict:
    """Pone imagenes a las fichas que no las tienen. Devuelve el recuento."""
    cache = Cache(cache_path)
    resumen = {"desde_cache": 0, "consultadas": 0, "con_caratula": 0, "sin_encontrar": 0}

    pendientes: list[dict] = []
    for ficha in fichas:
        guardado = cache.get(ficha["id"])
        if guardado is not None:
            aplicar(ficha, guardado)
            resumen["desde_cache"] += 1
        elif not ficha.get("poster"):
            pendientes.append(ficha)

    if limite > 0:
        # Las mas votadas primero: si el presupuesto no da para todas, que las
        # que se vean en portada sean las que tengan caratula.
        pendientes.sort(key=lambda f: -(f.get("votes") or 0))
        pendientes = pendientes[:limite]

    if pendientes:
        freno = RateLimiter(1 / max(1, por_segundo))
        sesion = requests.Session()
        sesion.headers.update({"Accept": "application/json"})
        try:
            with ThreadPoolExecutor(max_workers=hilos) as pool:
                futuros = {
                    pool.submit(_consultar, sesion, freno, clave, ficha["id"]): ficha
                    for ficha in pendientes
                }
                for futuro in as_completed(futuros):
                    ficha = futuros[futuro]
                    hallado = futuro.result()
                    resumen["consultadas"] += 1
                    if not hallado:
                        continue
                    cache.set(ficha["id"], hallado)
                    aplicar(ficha, hallado)
                    if hallado.get("poster"):
                        resumen["con_caratula"] += 1
                    else:
                        resumen["sin_encontrar"] += 1
                    if deadline is not None and time.monotonic() > deadline:
                        log.info("TMDB: se corta por tiempo tras %s consultas", resumen["consultadas"])
                        break
        finally:
            sesion.close()
            cache.guardar()

    resumen["en_cache"] = cache.resueltos
    log.info(
        "TMDB: %s desde cache, %s consultadas, %s con caratula, %s sin encontrar",
        resumen["desde_cache"], resumen["consultadas"],
        resumen["con_caratula"], resumen["sin_encontrar"],
    )
    return resumen
