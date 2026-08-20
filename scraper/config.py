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

# Los generos de Rotten Tomatoes, con su nombre en castellano.
GENRES = {
    "accion": "Acción",
    "aventura": "Aventura",
    "animacion": "Animación",
    "anime": "Anime",
    "biografia": "Biografía",
    "comedia": "Comedia",
    "crimen": "Crimen",
    "documental": "Documental",
    "drama": "Drama",
    "entretenimiento": "Entretenimiento",
    "fantasia": "Fantasía",
    "concurso": "Concurso",
    "historia": "Historia",
    "navidad": "Navidad",
    "terror": "Terror",
    "infantil-y-familiar": "Infantil y familiar",
    "lgbtq": "LGBTQ+",
    "musica": "Música",
    "musical": "Musical",
    "misterio-y-suspense": "Misterio y suspense",
    "naturaleza": "Naturaleza",
    "actualidad": "Actualidad",
    "telerrealidad": "Telerrealidad",
    "romance": "Romance",
    "ciencia-ficcion": "Ciencia ficción",
    "cortometraje": "Cortometraje",
    "deporte": "Deporte",
    "monologos": "Monólogos",
    "late-night": "Late night",
    "viajes": "Viajes",
    "belico": "Bélico",
    "western": "Western",
    "otros": "Otros",
}

# Como llama Rotten Tomatoes a cada genero en sus paginas, y en que clave
# nuestra cae. Se compara en minusculas y sin signos.
GENRE_ALIASES = {
    "action": "accion",
    "adventure": "aventura",
    "action & adventure": "accion",
    "animation": "animacion",
    "anime": "anime",
    "biography": "biografia",
    "comedy": "comedia",
    "crime": "crimen",
    "documentary": "documental",
    "drama": "drama",
    "entertainment": "entretenimiento",
    "faith & spirituality": "otros",
    "fantasy": "fantasia",
    "game show": "concurso",
    "health & wellness": "otros",
    "history": "historia",
    "holiday": "navidad",
    "horror": "terror",
    "house & garden": "otros",
    "kids & family": "infantil-y-familiar",
    "lgbtq+": "lgbtq",
    "music": "musica",
    "musical": "musical",
    "mystery & thriller": "misterio-y-suspense",
    "nature": "naturaleza",
    "news": "actualidad",
    "reality": "telerrealidad",
    "romance": "romance",
    "sci-fi": "ciencia-ficcion",
    "short": "cortometraje",
    "soap": "otros",
    "special interest": "otros",
    "sports": "deporte",
    "stand-up": "monologos",
    "talk show": "late-night",
    "travel": "viajes",
    "variety": "entretenimiento",
    "war": "belico",
    "western": "western",
}

# Cuando una pelicula tiene varios generos, el primero de esta lista manda: es
# el que decide en que carpeta vive su ficha. Los generos "de forma"
# (documental, cortometraje) describen el envase, no el tema, asi que van al
# final.
GENRE_PRIORITY = (
    "western", "musical", "terror", "ciencia-ficcion", "fantasia", "anime",
    "animacion", "belico", "crimen", "misterio-y-suspense", "romance",
    "comedia", "accion", "aventura", "historia", "biografia", "deporte",
    "musica", "infantil-y-familiar", "navidad", "lgbtq", "drama", "naturaleza",
    "viajes", "monologos", "late-night", "concurso", "telerrealidad",
    "actualidad", "entretenimiento", "documental", "cortometraje", "otros",
)

GENRE_PAGE_SIZE = 60
