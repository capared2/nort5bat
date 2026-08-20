"""Convierte la ficha HTML de Rotten Tomatoes en un registro estructurado.

La pagina reparte sus datos en varios bloques JSON incrustados, cada uno con
una parte de la ficha; se leen todos y se juntan. El JSON-LD aporta el reparto
y la direccion, con foto de cada uno.
"""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone

from bs4 import BeautifulSoup

from . import config
from . import urls as urlutil

log = logging.getLogger(__name__)

MAX_REPARTO = 20
MAX_IMAGENES = 8

# "2h 57m" / "1h" / "95m"
DURACION_RE = re.compile(r"^(?:(\d+)\s*h)?\s*(?:(\d+)\s*m)?$", re.I)
ANIO_RE = re.compile(r"^(19|20)\d{2}$")


def _bloque(soup: BeautifulSoup, identificador: str) -> dict:
    """Uno de los bloques ``<script id=... type="application/json">``."""
    tag = soup.find("script", id=identificador)
    if not tag:
        return {}
    try:
        datos = json.loads(tag.string or tag.get_text() or "{}")
    except ValueError:
        log.debug("bloque %s ilegible", identificador)
        return {}
    return datos if isinstance(datos, dict) else {}


def _jsonld(soup: BeautifulSoup) -> dict:
    mejor: dict = {}
    for tag in soup.find_all("script", attrs={"type": re.compile(r"ld\+json", re.I)}):
        crudo = (tag.string or tag.get_text() or "").strip()
        if not crudo:
            continue
        try:
            datos = json.loads(crudo)
        except ValueError:
            continue
        pila = [datos]
        while pila:
            item = pila.pop()
            if isinstance(item, list):
                pila.extend(item)
            elif isinstance(item, dict):
                if "@graph" in item:
                    pila.append(item["@graph"])
                    continue
                tipo = str(item.get("@type", "")).lower()
                if tipo in ("movie", "tvseries", "creativework"):
                    if len(json.dumps(item, default=str)) > len(json.dumps(mejor, default=str)):
                        mejor = item
    return mejor


def duracion_minutos(texto: str) -> int | None:
    """"2h 57m" -> 177."""
    match = DURACION_RE.match((texto or "").strip())
    if not match or not any(match.groups()):
        return None
    horas, minutos = (int(g or 0) for g in match.groups())
    return horas * 60 + minutos or None


def _propiedades(props: list) -> dict:
    """Reparte ``["R", "1972", "2h 57m"]`` en clasificacion, año y duracion.

    Vienen en una lista sin etiquetar y no siempre estan las tres, asi que cada
    valor se reconoce por su forma.
    """
    salida: dict = {"certificate": None, "year": None, "runtime_minutes": None}
    for prop in props or []:
        texto = str(prop).strip()
        if not texto:
            continue
        if ANIO_RE.match(texto):
            salida["year"] = int(texto)
        elif duracion_minutos(texto):
            salida["runtime_minutes"] = duracion_minutos(texto)
        elif salida["certificate"] is None:
            salida["certificate"] = texto
    return salida


def _numero(valor) -> float | None:
    try:
        return float(str(valor).strip().rstrip("%"))
    except (TypeError, ValueError):
        return None


def _entero(valor) -> int | None:
    numero = _numero(valor)
    return int(numero) if numero is not None else None


def _personas(entradas, limite: int) -> list[dict]:
    salida = []
    for persona in (entradas or [])[:limite]:
        if not isinstance(persona, dict) or not persona.get("name"):
            continue
        salida.append(
            {
                "id": urlutil.person_id(persona.get("sameAs", "") or ""),
                "name": persona["name"].strip(),
                "image": urlutil.caratula(persona.get("image"), "120x150"),
            }
        )
    return salida


def _trailer(video) -> dict | None:
    """Lo que hace falta para reproducir el trailer en nuestra propia pagina.

    El identificador publico del video ya viene en la ficha, y la URL del medio
    se arma con el: no hace falta pedir la pagina de trailers, que seria una
    peticion mas por pelicula.
    """
    if not isinstance(video, dict):
        return None
    publico = video.get("publicId")
    if not publico:
        return None
    miniatura = (video.get("thumbnail") or {}).get("url") if isinstance(video.get("thumbnail"), dict) else None
    try:
        segundos = int(float(video.get("durationInSeconds") or 0)) or None
    except (TypeError, ValueError):
        segundos = None
    return {
        "id": str(publico),
        "title": (video.get("title") or "").strip(),
        "thumbnail": miniatura,
        "seconds": segundos,
        # Se pide en HLS y no en MP4: el MP4 que sirve la plataforma es el
        # master, casi un giga por trailer. El HLS son dos kilobytes de lista
        # y el reproductor va pidiendo solo los trozos que se ven.
        "src": f"{config.VIDEO_BASE_URL}/{publico}?formats=M3U+none",
    }


def parse_movie(html: str, url: str) -> dict | None:
    """Construye el registro de la pelicula. ``None`` si la pagina no es una ficha."""
    soup = BeautifulSoup(html, "lxml")

    slug = urlutil.movie_id(url)
    if not slug:
        canonico = soup.find("link", rel=lambda v: v and "canonical" in v)
        if canonico and canonico.get("href"):
            slug = urlutil.movie_id(canonico["href"])
    if not slug:
        log.debug("sin identificador en %s", url)
        return None

    hero = _bloque(soup, "media-hero-json")
    marcador = _bloque(soup, "media-scorecard-json")
    donde_ver = _bloque(soup, "where-to-watch-json")
    fotos = _bloque(soup, "photosCarousel")
    curacion = _bloque(soup, "curation-json")
    ld = _jsonld(soup)

    contenido = hero.get("content") or {}
    titulo = (
        contenido.get("title")
        or donde_ver.get("title")
        or (ld.get("name") if isinstance(ld.get("name"), str) else None)
    )
    if not titulo:
        log.debug("sin titulo en %s", url)
        return None

    propiedades = _propiedades(contenido.get("metadataProps"))
    if propiedades["year"] is None and donde_ver.get("releaseYear"):
        propiedades["year"] = _entero(donde_ver["releaseYear"])
    if propiedades["certificate"] is None and ld.get("contentRating"):
        propiedades["certificate"] = str(ld["contentRating"])

    generos = [
        nombre
        for nombre in (urlutil.nombre_genero(g) for g in contenido.get("metadataGenres") or [])
        if nombre
    ]

    criticos = marcador.get("criticsScore") or {}
    publico = marcador.get("audienceScore") or {}

    # La nota sobre diez que dan los criticos es la que entiende el sitio; el
    # Tomatometer y el Popcornmeter viajan aparte, que son la marca de la casa.
    nota = _numero(criticos.get("averageRating"))
    tomatometer = _entero(criticos.get("score"))
    publico_score = _entero(publico.get("score"))

    # Un porcentaje no dice a cuanta gente le gusto: para ordenar por popular
    # sirve el numero de personas que han votado.
    votos = (_entero(publico.get("likedCount")) or 0) + (_entero(publico.get("notLikedCount")) or 0)

    caratula = urlutil.caratula(contenido.get("posterSrc"))
    fondo = (hero.get("iconic") or {}).get("srcDesktop")

    imagenes: list[dict] = []
    vistas: set[str] = set()
    for enlace, pie in [(caratula, ""), (fondo, "")]:
        if enlace and enlace not in vistas:
            vistas.add(enlace)
            imagenes.append({"url": enlace, "caption": pie})
    for imagen in (fotos.get("images") or [])[:MAX_IMAGENES]:
        enlace = imagen.get("imageUrl")
        if enlace and enlace not in vistas:
            vistas.add(enlace)
            imagenes.append({"url": enlace, "caption": (imagen.get("caption") or "").strip()})

    video = contenido.get("primaryVideo") or {}
    directores = _personas(ld.get("director"), 4)
    if not directores and donde_ver.get("director"):
        directores = [{"id": None, "name": donde_ver["director"], "image": None}]

    donde = [
        {"name": (sitio.get("text") or sitio.get("icon") or "").strip(), "url": sitio.get("url")}
        for sitio in (donde_ver.get("affiliates") or [])
        if sitio.get("url")
    ]

    return {
        "id": slug,
        "url": urlutil.movie_url(slug),
        "category": urlutil.category_key(generos),
        "type": curacion.get("type") or "movie",
        "title": titulo.strip(),
        "original_title": titulo.strip(),
        "genres": generos,
        "year": propiedades["year"],
        "end_year": None,
        "release_date": None,
        "runtime_minutes": propiedades["runtime_minutes"],
        "certificate": propiedades["certificate"],
        "rating": round(nota, 1) if nota is not None else None,
        "votes": votos or None,
        "tomatometer": tomatometer,
        "tomatometer_count": _entero(criticos.get("reviewCount")),
        "tomatometer_certified": bool(criticos.get("certified")),
        "audience_score": publico_score,
        "audience_count": _entero(publico.get("reviewCount")),
        "metascore": None,
        "plot": (marcador.get("description") or "").strip(),
        "tagline": "",
        "poster": caratula,
        "images": imagenes,
        "trailer": _trailer(video),
        "directors": [{"id": d["id"], "name": d["name"]} for d in directores],
        "writers": [],
        "cast": [
            {"id": p["id"], "name": p["name"], "character": "", "image": p["image"]}
            for p in _personas(ld.get("actor"), MAX_REPARTO)
        ],
        "keywords": [],
        "countries": [],
        "languages": [],
        "companies": [],
        "budget": None,
        "gross_worldwide": None,
        "streaming": donde,
        "similar": [],
        "source": "rottentomatoes.com",
        "scraped_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
