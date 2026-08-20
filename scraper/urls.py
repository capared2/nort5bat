"""Normalizacion de URLs de Rotten Tomatoes, deteccion de fichas y generos."""
from __future__ import annotations

import re
import unicodedata
from urllib.parse import urlsplit, urlunsplit

from . import config

# https://www.rottentomatoes.com/m/the_godfather
PELICULA_RE = re.compile(r"^/m/(?P<slug>[a-z0-9][a-z0-9_\-]*)(?:/(?P<sub>[^/?#]*))?/?$", re.I)
PERSONA_RE = re.compile(r"^/celebrity/(?P<slug>[a-z0-9][a-z0-9_\-]*)/?$", re.I)

# Rotten Tomatoes cuelga estos parametros de sus enlaces internos.
TRACKING_PREFIXES = ("cmp", "utm_", "wtwref", "ref_", "src", "intcmp")

# Tamaño al que se piden las caratulas. El redimensionador de Flixster acepta
# cualquier medida en la ruta, y la que trae la pagina son 68x102: un sello.
ANCHO_CARATULA = "300x450"
TAMANO_RE = re.compile(r"/(\d{2,4})x(\d{2,4})/")


def normalize(url: str, drop_fragment: bool = True) -> str:
    """Forma canonica: sin fragmento, sin parametros de seguimiento, sin barra final."""
    parts = urlsplit(url.strip())
    scheme = "https" if parts.scheme in ("", "http", "https") else parts.scheme
    netloc = parts.netloc.lower()
    if netloc == "rottentomatoes.com":
        netloc = "www.rottentomatoes.com"

    path = parts.path or "/"
    match = PELICULA_RE.match(path)
    if match and not match["sub"]:
        return urlunsplit((scheme, netloc, f"/m/{match['slug'].lower()}", "", ""))

    query = "&".join(
        piece
        for piece in parts.query.split("&")
        if piece and not piece.split("=")[0].lower().startswith(TRACKING_PREFIXES)
    )
    if len(path) > 1 and path.endswith("/"):
        path = path.rstrip("/")

    return urlunsplit((scheme, netloc, path, query, "" if drop_fragment else parts.fragment))


def host_allowed(url: str) -> bool:
    return urlsplit(url).netloc.lower() in config.ALLOWED_HOSTS


def is_excluded(url: str) -> bool:
    return urlsplit(url).path.lower().startswith(config.EXCLUDED_PATH_PREFIXES)


def is_movie_url(url: str) -> bool:
    """True solo para la ficha de una pelicula, no para sus subpaginas."""
    if not host_allowed(url) or is_excluded(url):
        return False
    match = PELICULA_RE.match(urlsplit(url).path)
    if not match:
        return False
    return not match["sub"]


def movie_id(url: str) -> str | None:
    """El identificador de una pelicula, que en Rotten Tomatoes es su slug."""
    match = PELICULA_RE.match(urlsplit(url).path)
    return match["slug"].lower() if match else None


def person_id(url: str) -> str | None:
    match = PERSONA_RE.match(urlsplit(url).path)
    return match["slug"].lower() if match else None


def movie_url(slug: str) -> str:
    return f"{config.BASE_URL}/m/{slug}"


def slugify(value: str) -> str:
    value = unicodedata.normalize("NFKD", value)
    value = value.encode("ascii", "ignore").decode("ascii").lower()
    value = re.sub(r"[^a-z0-9]+", "-", value).strip("-")
    return value


def genre_slug(nombre: str) -> str:
    """"Mystery & Thriller" -> "mystery-thriller". Vacio si no lo manejamos."""
    slug = slugify(nombre)
    return slug if slug in config.GENRES else ""


def nombre_genero(nombre: str) -> str:
    """Nombre canonico de un genero: "Sci-Fi", "Kids & Family"..."""
    clave = config.GENRE_ALIASES.get(nombre.strip().lower())
    if clave:
        return config.GENRES[clave]
    # Puede venir ya canonico, de una ficha que se vuelve a leer.
    return config.GENRES.get(slugify(nombre), "")


def category_key(generos: list[str] | None) -> str:
    """Carpeta donde vive la ficha: su genero principal.

    Manda el genero que mas dice de la pelicula (ver ``GENRE_PRIORITY``), no el
    orden en que Rotten Tomatoes los devuelve.
    """
    slugs = [s for s in (genre_slug(g) for g in (generos or [])) if s]
    if not slugs:
        return "other"
    orden = {clave: indice for indice, clave in enumerate(config.GENRE_PRIORITY)}
    return min(slugs, key=lambda s: orden.get(s, len(orden)))


def caratula(url: str | None, tamano: str = ANCHO_CARATULA) -> str | None:
    """Pide la imagen al tamaño que hace falta.

    Las paginas traen las caratulas a 68x102 pixeles. El redimensionador de
    Flixster lleva la medida en la propia ruta y acepta cambiarla, asi que se
    piden a un tamaño que sirva para una parrilla.
    """
    if not url:
        return None
    return TAMANO_RE.sub(f"/{tamano}/", url, count=1)
