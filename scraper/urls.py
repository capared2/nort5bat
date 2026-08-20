"""Normalizacion de URLs de IMDb, deteccion de fichas y claves de genero."""
from __future__ import annotations

import re
import unicodedata
from urllib.parse import urlsplit, urlunsplit

from . import config

# https://www.imdb.com/title/tt0111161/  ->  tt0111161
TITLE_RE = re.compile(r"^/(?:[a-z]{2}/)?title/(?P<id>tt\d{7,10})(?:/(?P<sub>[^/?#]*))?/?$")
# https://www.imdb.com/name/nm0000209/
NAME_RE = re.compile(r"^/(?:[a-z]{2}/)?name/(?P<id>nm\d{7,10})(?:/[^/?#]*)?/?$")

# IMDb cuelga un ?ref_= de casi todos sus enlaces internos.
TRACKING_PREFIXES = ("ref_", "utm_", "pf_rd_", "src", "ref", "gclid", "fbclid")


def normalize(url: str, drop_fragment: bool = True) -> str:
    """Forma canonica: sin fragmento, sin parametros de seguimiento, sin barra final.

    Las fichas se reducen ademas a ``/title/ttXXXXXXX/``: IMDb sirve la misma
    pagina bajo decenas de variantes (``/es/title/...``, ``?ref_=...``,
    ``/title/tt.../?pf_rd_m=...``) y sin esto la misma pelicula entraria en la
    cola una vez por variante.
    """
    parts = urlsplit(url.strip())
    scheme = "https" if parts.scheme in ("", "http", "https") else parts.scheme
    netloc = parts.netloc.lower()
    if netloc in ("imdb.com", "m.imdb.com"):
        netloc = "www.imdb.com"

    path = parts.path or "/"
    match = TITLE_RE.match(path)
    if match and not match["sub"]:
        return urlunsplit((scheme, netloc, f"/title/{match['id']}/", "", ""))

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
    path = urlsplit(url).path.lower()
    # Las ediciones por idioma repiten todo el sitio bajo /es/, /de/...
    path = re.sub(r"^/[a-z]{2}(?=/)", "", path)
    return path.startswith(config.EXCLUDED_PATH_PREFIXES)


def is_title_url(url: str) -> bool:
    """True solo para la ficha de un titulo, no para sus subpaginas."""
    if not host_allowed(url) or is_excluded(url):
        return False
    match = TITLE_RE.match(urlsplit(url).path)
    if not match:
        return False
    return not match["sub"]


def title_id(url: str) -> str | None:
    """El ``tconst`` de una URL de IMDb (``tt0111161``)."""
    match = TITLE_RE.match(urlsplit(url).path)
    return match["id"] if match else None


def name_id(url: str) -> str | None:
    match = NAME_RE.match(urlsplit(url).path)
    return match["id"] if match else None


def title_url(tconst: str) -> str:
    return f"{config.BASE_URL}/title/{tconst}/"


def is_tconst(value: str) -> bool:
    return bool(re.fullmatch(r"tt\d{7,10}", value or ""))


def slugify(value: str) -> str:
    value = unicodedata.normalize("NFKD", value)
    value = value.encode("ascii", "ignore").decode("ascii").lower()
    value = re.sub(r"[^a-z0-9]+", "-", value).strip("-")
    return value


def genre_slug(genre: str) -> str:
    """"Sci-Fi" -> "sci-fi". Devuelve cadena vacia si no es un genero de IMDb."""
    slug = slugify(genre)
    return slug if slug in config.GENRES else ""


def category_key(genres: list[str] | None) -> str:
    """Carpeta donde vive la ficha: su genero principal.

    Un titulo suele traer hasta tres generos. Se queda con el que mas dice de
    la pelicula (ver ``GENRE_PRIORITY``), para que "Alien" caiga en terror y no
    en aventura solo por el orden en que IMDb los devuelve.
    """
    slugs = [s for s in (genre_slug(g) for g in (genres or [])) if s]
    if not slugs:
        return "sin-genero"
    orden = {clave: indice for indice, clave in enumerate(config.GENRE_PRIORITY)}
    return min(slugs, key=lambda s: orden.get(s, len(orden)))
