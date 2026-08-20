# nort5bat — scraper de Rotten Tomatoes

Recolector de fichas de [rottentomatoes.com](https://www.rottentomatoes.com/).
Guarda el catálogo como JSON troceado dentro de este mismo repositorio y
publica, en la misma pasada, los índices y los sitemaps que consume el
frontend.

El sitio que lo usa vive en **[capared2/nort5](https://github.com/capared2/nort5)**.
Aquí no hay web: sólo el proceso que recoge los datos y el archivo resultante.

## Por qué Rotten Tomatoes

El primer intento fue IMDb, y no se pudo. Comprobado contra el sitio real, no
en teoría:

- Su `robots.txt` prohíbe `/title/` y `/chart/` a todo agente que no sea un
  buscador conocido.
- Y aunque se ignore, IMDb responde **`HTTP 202` a todas las peticiones**: el
  muro anti-bot de Amazon acepta la conexión y devuelve un interstitial en vez
  de la página.
- Sus datasets públicos sí están abiertos, pero **no contienen ni un solo campo
  de imagen**, y sin carátulas esto no es un sitio de cine.

Rotten Tomatoes, en cambio, nos deja entrar: su `robots.txt` permite `/m/`,
responde 200, y **cada ficha trae carátula, fondo, sinopsis, reparto con foto
de cada intérprete y dónde ver la película**. Es una página más rica que la de
IMDb.

Antes de escribir una línea de parser, todo esto se comprobó con
`herramientas/sondeo.py` (ver más abajo).

## Cómo funciona

```
descubrir URLs ──▶ cola reanudable ──▶ descargar ficha ──▶ parsear ──▶ data/
   browse            state/pending      Fetcher educado    bloques JSON  índices
   sitemap                              (robots.txt)       incrustados   sitemaps
   vecinas ◀──────────────────────────────────────────────────┘
```

Dos fuentes para encontrar películas:

- **browse** — las páginas de listado (lo popular, la taquilla, lo certificado
  fresco, lo mejor valorado por el público). Siete peticiones y traen justo lo
  que la gente está viendo.
- **sitemap** — los sitemaps del propio sitio, como red de seguridad.

Además, **cada ficha enlaza a otras películas y esos enlaces vuelven a la
cola**. Como salen de una página que ya se ha pedido, crecer por vecindad no
cuesta ni una petición más: el archivo se llena solo.

Cada ejecución tiene un presupuesto de tiempo. Cuando se acaba, guarda lo hecho
y deja el resto en `state/pending.txt`, así que la siguiente sigue donde lo
dejó.

## De dónde sale cada dato

La ficha reparte sus datos en varios bloques JSON incrustados en el HTML:

| Bloque | Qué aporta |
| --- | --- |
| `media-hero-json` | carátula, fondo, géneros, año, duración, clasificación, tráiler |
| `media-scorecard-json` | Tomatometer, Popcornmeter, nota media sobre 10, sinopsis |
| `where-to-watch-json` | dirección, año de estreno y dónde verla |
| `photosCarousel` | fotogramas |
| `JSON-LD` | reparto y dirección, con la foto de cada uno |

Las carátulas vienen a 68×102 píxeles, que es un sello de correos. El
redimensionador de Flixster lleva la medida en la propia ruta y acepta
cambiarla, así que se piden a un tamaño que sirva para una parrilla.

## Uso

```bash
pip install -r requirements.txt

# Lo que se está viendo ahora, sin límite de fichas
python -m scraper

# Recorrido a fondo: listados y sitemaps
python -m scraper --mode full

# Sólo vaciar la cola pendiente de la ejecución anterior
python -m scraper --skip-discovery

# Refrescar notas y porcentajes de las 500 fichas más antiguas
python -m scraper --refresh 500 --skip-discovery
```

| Opción | Para qué |
| --- | --- |
| `--mode incremental\|full` | `full` añade el recorrido de los sitemaps |
| `--min-votes` | descarta películas con poco público (0 = guardarlas todas) |
| `--refresh N` | devuelve a la cola N fichas ya guardadas, para actualizarlas |
| `--time-budget` | segundos de descarga antes de guardar y salir |
| `--delay` / `--workers` | ritmo de las peticiones |
| `--no-related` | no encolar las películas que enlaza cada ficha |

Los géneros, los títulos y las sinopsis se guardan tal y como vienen, en
inglés: el sitio que los consume está en ese idioma por la misma razón.

`python -m scraper --help` tiene la lista completa.

## Sondear un origen antes de escribirle un scraper

Construir el scraper de IMDb entero para descubrir después que contesta 202
costó horas y cuatro ejecuciones. `herramientas/sondeo.py` cuesta un minuto:
usa el mismo cliente que el scraper, con sus mismas cabeceras, y dice por cada
URL si `robots.txt` la permite, con qué código responde el origen y de qué
bloques de datos se puede sacar una ficha.

```bash
python -m herramientas.sondeo https://www.rottentomatoes.com/m/the_godfather --volcar 2000
```

También está como workflow (**Sondear un origen**), para preguntar desde un
runner en vez de desde una máquina cualquiera.

## Qué hay en `data/`

```
data/
  index.json                 géneros, cuántas películas y en qué ficheros
  portada.json               los carruseles de la home, en un solo fichero
  titulos/<género>/
    part-0001.json           las fichas completas, de 60 en 60
    lookup.json              id → número de parte
  generos/<género>.json      lo mejor de cada género, incluidos los secundarios
  rutas/<xx>.json            id → (género, parte), troceado por el final del id
  buscar/<inicial>.json      índice de búsqueda troceado por letra
  seo/                       sitemaps listos para servir
```

Cada ficha vive en la carpeta de su **género principal**, elegido por
relevancia y no por el orden en que Rotten Tomatoes los devuelve. Como una
película tiene varios géneros, `generos/<género>.json` guarda además las
mejores de cada uno contando también los secundarios.

La dirección pública de una película es sólo su identificador
(`/pelicula/the_godfather`), no su género: una película puede cambiar de género
principal entre ejecuciones y las direcciones ya publicadas no pueden romperse
por eso.

El índice de búsqueda se trocea por la inicial de **cada palabra** que
signifique algo, no sólo la primera: quien busca «padrino» no escribe «el
padrino».

Los ficheros sólo se reescriben cuando su contenido cambia de verdad. Sin eso,
cada ejecución dejaría en git un diff de miles de ficheros idénticos salvo por
la marca de tiempo.

### Por qué troceado

El frontend corre sobre Cloudflare Workers, que en el plan gratuito corta a los
10 ms de CPU por petición. Descargar un JSON de cientos de megas y buscar
dentro no cabe ahí. Con este reparto, pintar una ficha son dos lecturas
pequeñas y una búsqueda es una sola.

## Estado entre ejecuciones

`state/` se versiona junto a los datos:

- `pending.txt` — cola de URLs por visitar, en orden de prioridad
- `seen.txt` — lo ya guardado
- `failed.json` — intentos fallidos por URL; a los tres se abandona
- `run.json` — resumen de la última ejecución

## Automatización

`.github/workflows/scrape.yml` corre **cada seis horas** (a las 00:20, 06:20,
12:20 y 18:20 UTC), guarda lo nuevo y hace commit de `data/` y `state/`.

Cada pasada hace dos cosas:

1. **Añade** lo que encuentre: los siete listados traen los estrenos y lo que
   está en cartelera, y de cada ficha descargada salen enlaces a otras
   películas que vuelven a la cola. Ese es el motor que llena el archivo.
2. **Repasa** 500 fichas ya guardadas, para que las notas y los porcentajes no
   envejezcan. El tramo va rotando entre ejecuciones —el cursor se guarda en
   `state/run.json`—, de modo que en unas cuantas pasadas se recorre el archivo
   entero en vez de repasar siempre las mismas.

Con el ritmo por defecto, una ejecución descarga del orden de 3.000 fichas en
sus 55 minutos de presupuesto. Si una ejecución no guarda nada porque el origen
la rechaza, el workflow **falla** en vez de publicar un commit vacío con tick
verde. El resumen incluye el recuento de códigos HTTP devueltos, que es lo que
convierte un «fallaron todas» en un diagnóstico.

La variable de repositorio `SITE_URL` marca el dominio que se escribe en los
sitemaps.

`.github/workflows/tests.yml` pasa la batería de tests, que no toca la red: el
sitio se sustituye por un doble en `tests/fake_site.py`, y la fixture está
calcada de la estructura real que devolvió el sondeo.

## Buenos modales

El scraper obedece `robots.txt` (incluido su `crawl-delay`), espacia las
peticiones —el freno es global, así que `--delay 1.0` es una petición por
segundo en total, no por hilo—, reintenta con backoff y se identifica con un
User-Agent propio, que se puede cambiar con `RT_USER_AGENT`.

Los datos y las imágenes son de Rotten Tomatoes, que es de Fandango. Este
repositorio es un ejercicio de agregación y cada ficha enlaza a su página de
origen; antes de darle cualquier uso comercial hay que hablar con ellos.
