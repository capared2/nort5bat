"""Constantes y ajustes del scraper de IMDb."""
from __future__ import annotations

import os

BASE_URL = "https://www.imdb.com"

def _entorno(clave: str, defecto: str) -> str:
    """Valor del entorno, tratando la cadena vacia como "no definido".

    GitHub Actions pasa una variable de repositorio inexistente como cadena
    vacia, no como ausente: con os.environ.get a secas, no declarar SITE_URL
    dejaba los sitemaps sin dominio.
    """
    return os.environ.get(clave) or defecto


# Dominio publico del sitio que consume este dataset (para los sitemaps).
SITE_URL = _entorno("SITE_URL", "https://nort5.com")

# Hosts de los que aceptamos descargar fichas.
ALLOWED_HOSTS = {
    "www.imdb.com",
    "imdb.com",
    "m.imdb.com",
}

# Los datasets oficiales viven en su propio host y no son HTML.
DATASET_BASE_URL = _entorno("IMDB_DATASET_URL", "https://datasets.imdbws.com")
DATASET_BASICS = "title.basics.tsv.gz"
DATASET_RATINGS = "title.ratings.tsv.gz"
DATASET_AKAS = "title.akas.tsv.gz"
DATASET_CREW = "title.crew.tsv.gz"
DATASET_PRINCIPALS = "title.principals.tsv.gz"
DATASET_NAMES = "name.basics.tsv.gz"

DEFAULT_USER_AGENT = _entorno(
    "IMDB_USER_AGENT",
    "nort5bat-scraper/1.0 (+https://github.com/capared2/nort5bat)",
)

# IMDb sirve paginas grandes y corta el grifo antes que un diario: se va mas
# despacio que en markap y con menos hilos.
DEFAULT_DELAY = 1.0          # segundos entre peticiones (global, no por hilo)
DEFAULT_WORKERS = 4
DEFAULT_TIMEOUT = 30
DEFAULT_RETRIES = 3
DEFAULT_SHARD_SIZE = 60      # fichas por fichero JSON: pesan mas que una noticia
DEFAULT_TIME_BUDGET = 3300   # segundos de descarga de fichas por ejecucion

# Filtros del catalogo. Sin ellos entrarian los 11 millones de registros de
# IMDb, casi todos episodios sueltos sin una sola valoracion.
DEFAULT_TYPES = ("movie", "tvMovie")
DEFAULT_MIN_VOTES = 1000
DEFAULT_MIN_YEAR = 1920

# Tipos que IMDb reconoce, por si se quieren pedir desde la linea de ordenes.
KNOWN_TYPES = (
    "movie", "tvMovie", "tvSeries", "tvMiniSeries", "tvSpecial",
    "short", "tvShort", "video", "videoGame", "tvEpisode",
)

# Sitemaps que IMDb publica. Si robots.txt anuncia otros, se usan tambien.
SITEMAP_CANDIDATES = [
    "/sitemap/index.xml.gz",
    "/sitemap/index.xml",
    "/sitemap.xml",
]

# Listas publicas de IMDb: la via mas barata de encontrar lo que la gente ve
# ahora mismo, sin bajarse el catalogo entero.
CHART_SEEDS = [
    "/chart/top/",
    "/chart/moviemeter/",
    "/chart/boxoffice/",
    "/chart/top-english-movies/",
    "/chart/toptv/",
    "/chart/tvmeter/",
]

# Rutas que nunca contienen la ficha de un titulo.
EXCLUDED_PATH_PREFIXES = (
    "/search/",
    "/find",
    "/register",
    "/registration/",
    "/ap/",
    "/r/",
    "/offsite/",
    "/whitelist",
    "/_json/",
    "/tr/",
    "/list/",
    "/user/",
    "/poll/",
    "/showtimes/",
    "/calendar/",
    "/pro/",
)

# Subrutas de /title/ que cuelgan de la ficha pero no son la ficha.
TITLE_SUBPAGES = (
    "fullcredits", "reviews", "ratings", "trivia", "quotes", "goofs",
    "releaseinfo", "companycredits", "technical", "locations", "awards",
    "mediaindex", "mediaviewer", "videogallery", "soundtrack", "parentalguide",
    "externalsites", "keywords", "plotsummary", "taglines", "criticreviews",
    "episodes", "faq", "crazycredits", "alternateversions", "movieconnections",
    "news", "boxoffice", "bio", "video",
)

# Los generos de IMDb, con su nombre en castellano para el frontend.
GENRES = {
    "action": "Acción",
    "adventure": "Aventura",
    "animation": "Animación",
    "biography": "Biografía",
    "comedy": "Comedia",
    "crime": "Crimen",
    "documentary": "Documental",
    "drama": "Drama",
    "family": "Familiar",
    "fantasy": "Fantasía",
    "film-noir": "Cine negro",
    "game-show": "Concurso",
    "history": "Historia",
    "horror": "Terror",
    "music": "Música",
    "musical": "Musical",
    "mystery": "Misterio",
    "news": "Actualidad",
    "reality-tv": "Telerrealidad",
    "romance": "Romance",
    "sci-fi": "Ciencia ficción",
    "short": "Cortometraje",
    "sport": "Deporte",
    "talk-show": "Late night",
    "thriller": "Suspense",
    "war": "Bélico",
    "western": "Western",
}

# Cuando un titulo tiene varios generos, el primero de esta lista manda: es el
# que decide en que carpeta vive su ficha. Los generos "de forma" (corto,
# documental) describen el envase, no el tema, asi que van al final.
GENRE_PRIORITY = (
    "film-noir", "western", "musical", "horror", "sci-fi", "fantasy",
    "animation", "war", "crime", "mystery", "thriller", "romance", "comedy",
    "action", "adventure", "history", "biography", "sport", "music", "family",
    "drama", "documentary", "short", "news", "reality-tv", "game-show",
    "talk-show",
)

# Cuantas fichas caben en cada pagina de genero que consume el frontend.
GENRE_PAGE_SIZE = 60
