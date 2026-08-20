"""Constantes y ajustes del scraper de Rotten Tomatoes."""
from __future__ import annotations

import os


def _entorno(clave: str, defecto: str) -> str:
    """Valor del entorno, tratando la cadena vacia como "no definido".

    GitHub Actions pasa una variable de repositorio inexistente como cadena
    vacia, no como ausente: con os.environ.get a secas, no declarar SITE_URL
    dejaba los sitemaps sin dominio.
    """
    return os.environ.get(clave) or defecto


BASE_URL = "https://www.rottentomatoes.com"

# Dominio publico del sitio que consume este dataset (para los sitemaps).
SITE_URL = _entorno("SITE_URL", "https://nort5.com")

ALLOWED_HOSTS = {
    "www.rottentomatoes.com",
    "rottentomatoes.com",
}

DEFAULT_USER_AGENT = _entorno(
    "RT_USER_AGENT",
    "nort5bat-scraper/1.0 (+https://github.com/capared2/nort5bat)",
)

DEFAULT_DELAY = 1.0          # segundos entre peticiones (global, no por hilo)
DEFAULT_WORKERS = 4
DEFAULT_TIMEOUT = 30
DEFAULT_RETRIES = 3
DEFAULT_SHARD_SIZE = 60      # fichas por fichero JSON
DEFAULT_TIME_BUDGET = 3300   # segundos de descarga de fichas por ejecucion

# Una pelicula sin publico no le interesa a nadie y llena el archivo de ruido.
DEFAULT_MIN_VOTES = 0

# La cuenta de la plataforma de video desde la que se sirven los trailers. El
# identificador publico de cada video ya viene en la ficha, asi que con esto se
# arma la URL del medio sin pedir la pagina de trailers.
VIDEO_BASE_URL = _entorno("VIDEO_BASE_URL", "https://link.theplatform.com/s/NGweTC/media")

SITEMAP_CANDIDATES = [
    "/sitemap.xml",
    "/sitemaps/sitemap.xml",
]

# Las paginas de listado de las que salen las peliculas. Rotten Tomatoes las
# ordena y filtra por la propia ruta, asi que cada variante trae un surtido
# distinto sin necesidad de paginar a mano.
BROWSE_SEEDS = [
    "/browse/movies_at_home/sort:popular",
    "/browse/movies_at_home/sort:top_box_office",
    "/browse/movies_at_home/critics:certified_fresh~sort:popular",
    "/browse/movies_at_home/audience:upright~sort:popular",
    "/browse/movies_in_theaters/sort:popular",
    "/browse/movies_in_theaters/sort:top_box_office",
    "/browse/movies_coming_soon/",
]

# Rutas que nunca son la ficha de una pelicula.
EXCLUDED_PATH_PREFIXES = (
    "/critics",
    "/celebrity",
    "/napi",
    "/search",
    "/user",
    "/franchise",
    "/showtimes",
    "/account",
    "/privacy",
    "/help",
    "/about",
    "/policies",
    "/browse",
    "/tv",
)

# Subrutas que cuelgan de la ficha pero no son la ficha.
MOVIE_SUBPAGES = (
    "reviews", "pictures", "trailers", "cast-and-crew", "news", "videos",
    "clips", "quotes", "similar", "awards",
)

# The genres Rotten Tomatoes uses. The site speaks English because the source
# does: translating titles we do not have would be worse than not translating.
GENRES = {
    "action": "Action",
    "adventure": "Adventure",
    "animation": "Animation",
    "anime": "Anime",
    "biography": "Biography",
    "comedy": "Comedy",
    "crime": "Crime",
    "documentary": "Documentary",
    "drama": "Drama",
    "entertainment": "Entertainment",
    "fantasy": "Fantasy",
    "game-show": "Game Show",
    "history": "History",
    "holiday": "Holiday",
    "horror": "Horror",
    "kids-family": "Kids & Family",
    "lgbtq": "LGBTQ+",
    "music": "Music",
    "musical": "Musical",
    "mystery-thriller": "Mystery & Thriller",
    "nature": "Nature",
    "news": "News",
    "reality": "Reality",
    "romance": "Romance",
    "sci-fi": "Sci-Fi",
    "short": "Short",
    "sports": "Sports",
    "stand-up": "Stand-Up",
    "talk-show": "Talk Show",
    "travel": "Travel",
    "war": "War",
    "western": "Western",
    "other": "Other",
}

# How the source names each genre, and which key of ours it falls into. The
# comparison is done lowercased.
GENRE_ALIASES = {
    "action": "action",
    "action & adventure": "action",
    "adventure": "adventure",
    "animation": "animation",
    "anime": "anime",
    "biography": "biography",
    "comedy": "comedy",
    "crime": "crime",
    "documentary": "documentary",
    "drama": "drama",
    "entertainment": "entertainment",
    "faith & spirituality": "other",
    "fantasy": "fantasy",
    "game show": "game-show",
    "health & wellness": "other",
    "history": "history",
    "holiday": "holiday",
    "horror": "horror",
    "house & garden": "other",
    "kids & family": "kids-family",
    "lgbtq+": "lgbtq",
    "music": "music",
    "musical": "musical",
    "mystery & thriller": "mystery-thriller",
    "nature": "nature",
    "news": "news",
    "reality": "reality",
    "romance": "romance",
    "sci-fi": "sci-fi",
    "short": "short",
    "soap": "other",
    "special interest": "other",
    "sports": "sports",
    "stand-up": "stand-up",
    "talk show": "talk-show",
    "travel": "travel",
    "variety": "entertainment",
    "war": "war",
    "western": "western",
}

# When a film carries several genres, the first one on this list wins: it is
# the one that decides which folder its record lives in. The "shape" genres
# (documentary, short) describe the container, not the subject, so they go last.
GENRE_PRIORITY = (
    "western", "musical", "horror", "sci-fi", "fantasy", "anime", "animation",
    "war", "crime", "mystery-thriller", "romance", "comedy", "action",
    "adventure", "history", "biography", "sports", "music", "kids-family",
    "holiday", "lgbtq", "drama", "nature", "travel", "stand-up", "talk-show",
    "game-show", "reality", "news", "entertainment", "documentary", "short",
    "other",
)

GENRE_PAGE_SIZE = 60
