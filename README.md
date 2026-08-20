# nort5bat — scraper de IMDb

Recolector de fichas de [imdb.com](https://www.imdb.com/). Guarda el catálogo
como JSON troceado dentro de este mismo repositorio y publica, en la misma
pasada, los índices y los sitemaps que consume el frontend.

El sitio que lo usa vive en **[capared2/nort5](https://github.com/capared2/nort5)**.
Aquí no hay web: solo el proceso que recoge los datos y el archivo resultante.

## Cómo funciona

```
descubrir URLs ──▶ cola reanudable ──▶ descargar ficha ──▶ parsear ──▶ data/
   charts            state/pending      Fetcher educado    JSON-LD +     índices
   datasets                             (robots.txt)       __NEXT_DATA__  sitemaps
   sitemap
```

Tres fuentes para encontrar títulos:

- **charts** — las listas públicas (Top 250, lo más popular, taquilla). Cuatro
  peticiones y traen justo lo que la gente está viendo ahora.
- **datasets** — los [datasets oficiales de IMDb](https://developer.imdb.com/non-commercial-datasets/),
  que dan el catálogo entero con sus votos. Se recorren en streaming y se
  filtran por tipo, votos y año, así que nunca se cargan enteros en memoria.
- **sitemap** — los sitemaps del propio sitio, como red de seguridad.

Además, cada ficha trae sus «títulos parecidos» y esos vuelven a la cola: el
archivo crece solo por vecindad sin tener que pedir el catálogo entero.

Cada ejecución tiene un presupuesto de tiempo. Cuando se acaba, guarda lo hecho
y deja el resto en `state/pending.txt`, así que la siguiente sigue donde lo dejó.

## Uso

```bash
pip install -r requirements.txt

# Lo más visto ahora mismo, sin límite de fichas
python -m scraper

# Catálogo completo: películas con 5.000 votos o más desde 1970
python -m scraper --mode full --min-votes 5000 --min-year 1970

# Solo vaciar la cola pendiente de la ejecución anterior
python -m scraper --skip-discovery

# Refrescar notas y votos de las 500 fichas más antiguas
python -m scraper --refresh 500 --skip-discovery
```

Opciones que más se tocan:

| Opción | Para qué |
| --- | --- |
| `--mode incremental\|full` | `full` baja el catálogo entero; `incremental` solo mira las listas |
| `--min-votes` | umbral de votos para entrar en el catálogo (por defecto 1000) |
| `--types` | `movie,tvMovie` por defecto; admite `tvSeries`, `short`… |
| `--catalog-limit` | tope de títulos que se sacan del catálogo |
| `--refresh N` | devuelve a la cola N fichas ya guardadas, para actualizarlas |
| `--time-budget` | segundos de descarga antes de guardar y salir |
| `--delay` / `--workers` | ritmo de las peticiones |
| `--no-similar` | no encolar los títulos parecidos de cada ficha |

`python -m scraper --help` tiene la lista completa.

## Qué hay en `data/`

```
data/
  index.json                 géneros, cuántos títulos y en qué ficheros
  portada.json               los carruseles de la home, en un solo fichero
  titulos/<género>/
    part-0001.json           las fichas completas, de 60 en 60
    lookup.json              id → número de parte, para resolver una ficha con una sola lectura
  generos/<género>.json      lo mejor de cada género, incluidos los secundarios
  rutas/<xx>.json            id → (género, parte), troceado por el final del id
  buscar/<inicial>.json      índice de búsqueda troceado por letra
  seo/                       sitemaps listos para servir
```

Cada ficha vive en la carpeta de su **género principal**, que se elige por
relevancia y no por el orden en que IMDb los devuelve: «Alien» cae en terror,
no en aventura. Como una película tiene hasta tres géneros, `generos/<género>.json`
guarda además las mejores de cada uno contando también los secundarios, que es
lo que hace que «Alien» salga en terror **y** en ciencia ficción.

La dirección pública de una película es solo su identificador (`/pelicula/tt0111161`),
no su género: una película puede cambiar de género principal entre ejecuciones y
las direcciones ya publicadas no pueden romperse por eso. `rutas/` es lo que
permite resolver un identificador a su fichero con una sola lectura pequeña.

Los ficheros solo se reescriben cuando su contenido cambia de verdad. Sin eso,
cada ejecución dejaría en git un diff de miles de ficheros idénticos salvo por
la marca de tiempo.

### Por qué troceado

El frontend corre sobre Cloudflare Workers, que en el plan gratuito corta a los
10 ms de CPU por petición. Descargar un JSON de cientos de megas y buscar dentro
no cabe ahí. Con este reparto, pintar una ficha son dos lecturas pequeñas
(`rutas/<xx>.json` y su `part-NNNN.json`) y una búsqueda es una sola.

## Estado entre ejecuciones

`state/` se versiona junto a los datos:

- `pending.txt` — cola de URLs por visitar, en orden de prioridad
- `seen.txt` — lo ya guardado
- `failed.json` — intentos fallidos por URL; a los tres se abandona
- `run.json` — resumen de la última ejecución

## Automatización

`.github/workflows/scrape.yml` corre cada seis horas, guarda lo nuevo y hace
commit de `data/` y `state/`. Se puede lanzar a mano desde la pestaña Actions
con todos los parámetros de arriba. La variable de repositorio `SITE_URL` marca
el dominio que se escribe en los sitemaps.

`.github/workflows/tests.yml` pasa la batería de tests, que no toca la red: el
sitio se sustituye por un doble en `tests/fake_site.py`.

## Buenos modales

El scraper espacia las peticiones —el freno es global, así que `--delay 1.0`
es una petición por segundo en total, no por hilo—, reintenta con backoff y se
identifica con un User-Agent propio, que se puede cambiar con `IMDB_USER_AGENT`.

Por defecto obedece `robots.txt`, incluido su `crawl-delay`. **Este despliegue
no lo hace**: el `robots.txt` de IMDb prohíbe `/title/` y `/chart/` a los
agentes que no son buscadores conocidos, así que el workflow pasa
`--ignore-robots` y la recolección sigue adelante. Es una decisión consciente
del dueño del repositorio, no un descuido, y queda a la vista en la entrada
`ignore_robots` del workflow: ponla en `false` y el scraper vuelve a obedecer
(y a no traer nada de IMDb). Ignorar `robots.txt` va contra lo que IMDb pide y
contra sus condiciones de uso, y pueden cortar la IP del runner en cualquier
momento.

Los datasets de IMDb se publican **para uso personal y no comercial**, y las
condiciones del sitio son las suyas. Este repositorio es un ejercicio de
agregación: antes de darle cualquier uso comercial hay que pasar por la
[API de datos con licencia](https://developer.imdb.com/) de IMDb.
