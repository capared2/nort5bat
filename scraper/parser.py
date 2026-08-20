"""Convierte la ficha HTML de un titulo de IMDb en un registro estructurado."""
from __future__ import annotations

import json
import logging
import re
from datetime import datetime, timezone
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from . import urls as urlutil

log = logging.getLogger(__name__)

# Tipos de schema.org con los que IMDb marca una ficha.
TITLE_TYPES = {
    "movie", "tvseries", "tvminiseries", "tvepisode", "tvspecial",
    "videogame", "creativework", "video", "episode",
}

MAX_CAST = 20          # el reparto completo de un blockbuster son cientos de nombres
MAX_SIMILAR = 12
MAX_KEYWORDS = 20
DURACION_RE = re.compile(r"^P(?:(\d+)D)?T?(?:(\d+)H)?(?:(\d+)M)?", re.I)


def _texto(nodo) -> str:
    return re.sub(r"\s+", " ", nodo.get_text(" ", strip=True)).strip() if nodo else ""


def _meta(soup: BeautifulSoup, *nombres: str) -> str | None:
    for nombre in nombres:
        for atributo in ("property", "name", "itemprop"):
            tag = soup.find("meta", attrs={atributo: nombre})
            if tag and tag.get("content"):
                return tag["content"].strip()
    return None


# --- utilidades sobre JSON ---------------------------------------------

def _ruta(datos, camino: str):
    """``_ruta(d, "ratingsSummary.aggregateRating")`` sin reventar por el camino."""
    actual = datos
    for tramo in camino.split("."):
        if isinstance(actual, dict):
            actual = actual.get(tramo)
        else:
            return None
        if actual is None:
            return None
    return actual


def _primero(datos, *caminos: str):
    for camino in caminos:
        valor = _ruta(datos, camino)
        if valor not in (None, "", [], {}):
            return valor
    return None


def _buscar_clave(datos, clave: str, limite: int = 4000):
    """Primer valor asociado a ``clave`` en cualquier nivel del arbol.

    El JSON de la ficha cambia de forma cada pocos meses; buscar por nombre de
    campo aguanta esos cambios mucho mejor que fijar la ruta completa.
    """
    pila = [datos]
    visitados = 0
    while pila and visitados < limite:
        actual = pila.pop(0)
        visitados += 1
        if isinstance(actual, dict):
            if clave in actual and actual[clave] not in (None, "", [], {}):
                return actual[clave]
            pila.extend(actual.values())
        elif isinstance(actual, list):
            pila.extend(actual)
    return None


def _texto_de(nodo, claves: tuple[str, ...], profundidad: int = 0) -> str | None:
    """Primer texto legible de un nodo, buscando por las claves dadas.

    IMDb anida sus etiquetas de formas distintas segun el campo
    (``{"text": ...}``, ``{"company": {"companyText": {"text": ...}}}``), asi
    que se baja por el arbol hasta dar con una de las claves pedidas.
    """
    if isinstance(nodo, str):
        return nodo.strip() or None
    if not isinstance(nodo, dict) or profundidad > 4:
        return None
    for clave in claves:
        if clave in nodo:
            hallado = _texto_de(nodo[clave], claves, profundidad + 1)
            if hallado:
                return hallado
    for valor in nodo.values():
        if isinstance(valor, dict):
            hallado = _texto_de(valor, claves, profundidad + 1)
            if hallado:
                return hallado
    return None


def _textos(valor, *claves: str) -> list[str]:
    """Lista de cadenas a partir de las formas en que IMDb devuelve etiquetas."""
    buscadas = claves or ("text", "name", "id")
    items = valor if isinstance(valor, list) else [valor]
    salida: list[str] = []
    for item in items:
        # Las conexiones estilo GraphQL vienen como {"node": {...}}.
        if isinstance(item, dict) and "node" in item:
            item = item["node"]
        hallado = _texto_de(item, buscadas)
        if hallado:
            salida.append(hallado)
    vistos: set[str] = set()
    return [t for t in salida if not (t.lower() in vistos or vistos.add(t.lower()))]


def duracion_minutos(valor) -> int | None:
    """Acepta ``PT2H22M``, segundos o los minutos ya calculados."""
    if valor is None:
        return None
    if isinstance(valor, (int, float)):
        # IMDb da segundos en su JSON y minutos en algunos campos sueltos.
        return int(valor // 60) if valor > 600 else int(valor)
    match = DURACION_RE.match(str(valor).strip())
    if not match:
        return None
    dias, horas, minutos = (int(g or 0) for g in match.groups())
    total = dias * 1440 + horas * 60 + minutos
    return total or None


def fecha_iso(valor) -> str | None:
    """Normaliza a ``YYYY-MM-DD`` lo que IMDb entregue como fecha de estreno."""
    if not valor:
        return None
    if isinstance(valor, dict):
        anio, mes, dia = valor.get("year"), valor.get("month"), valor.get("day")
        if not anio:
            return None
        return f"{int(anio):04d}-{int(mes or 1):02d}-{int(dia or 1):02d}"
    crudo = str(valor).strip()
    match = re.search(r"(\d{4})-(\d{2})-(\d{2})", crudo)
    if match:
        return match.group(0)
    if re.fullmatch(r"\d{4}", crudo):
        return f"{crudo}-01-01"
    return None


def _dinero(valor) -> dict | None:
    """``{"amount": 25000000, "currency": "USD"}`` venga como venga."""
    if not isinstance(valor, dict):
        return None
    cantidad = valor.get("amount")
    if cantidad is None:
        dentro = valor.get("total") or valor.get("budget")
        if isinstance(dentro, dict):
            cantidad = dentro.get("amount")
            valor = dentro
    if not isinstance(cantidad, (int, float)):
        return None
    return {"amount": int(cantidad), "currency": valor.get("currency") or "USD"}


# --- extraccion de los dos bloques de datos ----------------------------

def _iter_jsonld(soup: BeautifulSoup):
    for tag in soup.find_all("script", attrs={"type": re.compile(r"ld\+json", re.I)}):
        crudo = (tag.string or tag.get_text() or "").strip()
        if not crudo:
            continue
        try:
            datos = json.loads(crudo)
        except json.JSONDecodeError:
            continue
        pila = [datos]
        while pila:
            item = pila.pop()
            if isinstance(item, list):
                pila.extend(item)
            elif isinstance(item, dict):
                if "@graph" in item:
                    pila.append(item["@graph"])
                yield item


def _ficha_jsonld(soup: BeautifulSoup) -> dict:
    mejor: dict = {}
    for item in _iter_jsonld(soup):
        tipos = item.get("@type") or item.get("type") or ""
        if isinstance(tipos, str):
            tipos = [tipos]
        if {str(t).lower() for t in tipos} & TITLE_TYPES:
            if len(json.dumps(item, default=str)) > len(json.dumps(mejor, default=str)):
                mejor = item
    return mejor


def _next_data(soup: BeautifulSoup) -> dict:
    """El JSON que IMDb incrusta para pintar la pagina en el navegador.

    Trae mucho mas que el JSON-LD (sinopsis larga, reparto, presupuesto,
    recaudacion, titulos parecidos). Si un dia deja de estar, el resto del
    parseo sigue funcionando con el JSON-LD.
    """
    tag = soup.find("script", id="__NEXT_DATA__")
    if not tag:
        return {}
    try:
        datos = json.loads(tag.string or tag.get_text() or "{}")
    except json.JSONDecodeError:
        log.debug("__NEXT_DATA__ ilegible")
        return {}

    props = _ruta(datos, "props.pageProps") or {}
    arriba = props.get("aboveTheFoldData") or {}
    principal = props.get("mainColumnData") or {}
    if not arriba and not principal:
        return props if isinstance(props, dict) else {}
    # Un solo diccionario con los dos bloques: los campos no se pisan entre si.
    return {**principal, **arriba, "_main": principal, "_above": arriba}


def _reparto(next_data: dict, jsonld: dict) -> list[dict]:
    bordes = _primero(next_data, "cast.edges", "_main.cast.edges") or []
    reparto: list[dict] = []
    for borde in bordes[:MAX_CAST]:
        nodo = borde.get("node") if isinstance(borde, dict) else None
        if not isinstance(nodo, dict):
            continue
        nombre = _ruta(nodo, "name.nameText.text")
        if not nombre:
            continue
        personajes = _textos(nodo.get("characters"), "name")
        reparto.append(
            {
                "id": _ruta(nodo, "name.id"),
                "name": nombre,
                "character": personajes[0] if personajes else "",
                "image": _ruta(nodo, "name.primaryImage.url"),
            }
        )
    if reparto:
        return reparto

    for actor in (jsonld.get("actor") or [])[:MAX_CAST]:
        if isinstance(actor, dict) and actor.get("name"):
            reparto.append(
                {
                    "id": urlutil.name_id(actor.get("url", "") or ""),
                    "name": actor["name"].strip(),
                    "character": "",
                    "image": None,
                }
            )
    return reparto


def _equipo(next_data: dict, jsonld: dict, papel: str) -> list[dict]:
    """Direccion y guion, del bloque de creditos principales o del JSON-LD."""
    creditos = _primero(next_data, "principalCredits", "_main.principalCredits") or []
    for bloque in creditos:
        if not isinstance(bloque, dict):
            continue
        etiqueta = (_ruta(bloque, "category.text") or _ruta(bloque, "category.id") or "").lower()
        if papel not in etiqueta:
            continue
        gente = []
        for credito in bloque.get("credits") or []:
            nombre = _ruta(credito, "name.nameText.text")
            if nombre:
                gente.append({"id": _ruta(credito, "name.id"), "name": nombre})
        if gente:
            return gente

    clave = {"director": "director", "writer": "creator"}.get(papel, papel)
    salida = []
    for persona in (jsonld.get(clave) or []):
        if isinstance(persona, dict) and persona.get("name"):
            salida.append(
                {"id": urlutil.name_id(persona.get("url", "") or ""), "name": persona["name"].strip()}
            )
    return salida


def _imagenes(soup: BeautifulSoup, next_data: dict, jsonld: dict, base_url: str) -> list[dict]:
    encontradas: list[dict] = []
    vistas: set[str] = set()

    def anadir(url, pie: str = "") -> None:
        if not isinstance(url, str) or not url.strip():
            return
        absoluta = urljoin(base_url, url.strip())
        if absoluta.startswith("data:") or absoluta in vistas:
            return
        vistas.add(absoluta)
        encontradas.append({"url": absoluta, "caption": pie})

    anadir(_primero(next_data, "primaryImage.url", "_above.primaryImage.url"),
           _primero(next_data, "primaryImage.caption.plainText") or "")
    imagen = jsonld.get("image")
    anadir(imagen if isinstance(imagen, str) else _ruta(imagen or {}, "url"))
    anadir(_meta(soup, "og:image", "twitter:image"))

    for borde in (_primero(next_data, "titleMainImages.edges", "_main.titleMainImages.edges") or [])[:8]:
        nodo = borde.get("node") if isinstance(borde, dict) else None
        if isinstance(nodo, dict):
            anadir(nodo.get("url"), _ruta(nodo, "caption.plainText") or "")

    return encontradas


def parse_title(html: str, url: str) -> dict | None:
    """Construye el registro del titulo. ``None`` si la pagina no es una ficha."""
    soup = BeautifulSoup(html, "lxml")
    jsonld = _ficha_jsonld(soup)
    siguiente = _next_data(soup)

    tconst = urlutil.title_id(url) or urlutil.title_id(jsonld.get("url", "") or "")
    if not tconst:
        canonico = soup.find("link", rel=lambda v: v and "canonical" in v)
        if canonico and canonico.get("href"):
            tconst = urlutil.title_id(urljoin(url, canonico["href"]))
    if not tconst:
        log.debug("sin tconst en %s", url)
        return None

    titulo = (
        _primero(siguiente, "titleText.text", "_above.titleText.text")
        or (jsonld.get("name") if isinstance(jsonld.get("name"), str) else None)
        or _meta(soup, "og:title")
        or _texto(soup.select_one("h1[data-testid=hero__pageTitle], h1"))
    )
    if not titulo:
        log.debug("sin titulo en %s", url)
        return None
    # og:title llega como "El padrino (1972) - IMDb".
    titulo = re.sub(r"\s*[-|]\s*IMDb\s*$", "", titulo).strip()

    original = (
        _primero(siguiente, "originalTitleText.text", "_above.originalTitleText.text")
        or (jsonld.get("alternateName") if isinstance(jsonld.get("alternateName"), str) else None)
        or titulo
    )

    generos = _textos(
        _primero(siguiente, "genres.genres", "titleGenres.genres", "_above.genres.genres")
        or jsonld.get("genre")
    )
    # Se descarta lo que no sea un genero reconocido: por ese campo tambien
    # asoman identificadores internos que no pintan nada en el sitio.
    generos = [g for g in generos if urlutil.genre_slug(g)]

    anio = _primero(siguiente, "releaseYear.year", "_above.releaseYear.year")
    if not isinstance(anio, int):
        anio = None
    estreno = fecha_iso(
        _primero(siguiente, "releaseDate", "_above.releaseDate") or jsonld.get("datePublished")
    )
    if anio is None and estreno:
        anio = int(estreno[:4])

    nota = _primero(siguiente, "ratingsSummary.aggregateRating", "_above.ratingsSummary.aggregateRating")
    votos = _primero(siguiente, "ratingsSummary.voteCount", "_above.ratingsSummary.voteCount")
    if nota is None:
        nota = _ruta(jsonld, "aggregateRating.ratingValue")
    if votos is None:
        votos = _ruta(jsonld, "aggregateRating.ratingCount")

    sinopsis = (
        _primero(siguiente, "plot.plotText.plainText", "_above.plot.plotText.plainText")
        or (jsonld.get("description") if isinstance(jsonld.get("description"), str) else None)
        or _texto(soup.select_one("[data-testid=plot-xl], [data-testid=plot]"))
        or ""
    )

    etiquetas = _textos(_primero(siguiente, "keywords.edges", "_main.keywords.edges"))[:MAX_KEYWORDS]
    if not etiquetas:
        claves = jsonld.get("keywords")
        if isinstance(claves, str):
            etiquetas = [k.strip() for k in claves.split(",") if k.strip()][:MAX_KEYWORDS]

    parecidos = [
        identificador
        for identificador in _textos(
            _primero(siguiente, "moreLikeThisTitles.edges", "_main.moreLikeThisTitles.edges"),
            "id",
        )
        if urlutil.is_tconst(identificador)
    ][:MAX_SIMILAR]

    imagenes = _imagenes(soup, siguiente, jsonld, url)
    trailer = _primero(siguiente, "primaryVideos.edges") or jsonld.get("trailer")

    tipo = (
        _primero(siguiente, "titleType.id", "_above.titleType.id")
        or (jsonld.get("@type") if isinstance(jsonld.get("@type"), str) else None)
        or "movie"
    )

    return {
        "id": tconst,
        "url": urlutil.title_url(tconst),
        "category": urlutil.category_key(generos),
        "type": str(tipo),
        "title": titulo,
        "original_title": original.strip(),
        "genres": generos,
        "year": anio,
        "end_year": _primero(siguiente, "releaseYear.endYear", "_above.releaseYear.endYear"),
        "release_date": estreno,
        "runtime_minutes": duracion_minutos(
            _primero(siguiente, "runtime.seconds", "_above.runtime.seconds") or jsonld.get("duration")
        ),
        "certificate": _primero(siguiente, "certificate.rating", "_above.certificate.rating")
        or jsonld.get("contentRating"),
        "rating": round(float(nota), 1) if isinstance(nota, (int, float)) else None,
        "votes": int(votos) if isinstance(votos, (int, float)) else None,
        "metascore": _primero(siguiente, "metacritic.metascore.score", "_main.metacritic.metascore.score"),
        "plot": sinopsis.strip(),
        "tagline": (_textos(_primero(siguiente, "taglines.edges", "_main.taglines.edges")) or [""])[0],
        "poster": imagenes[0]["url"] if imagenes else None,
        "images": imagenes[:8],
        "trailer": _buscar_clave(trailer, "embedUrl") or _buscar_clave(trailer, "url"),
        "directors": _equipo(siguiente, jsonld, "director"),
        "writers": _equipo(siguiente, jsonld, "writer"),
        "cast": _reparto(siguiente, jsonld),
        "keywords": etiquetas,
        "countries": _textos(_primero(siguiente, "countriesOfOrigin.countries", "_main.countriesOfOrigin.countries")),
        "languages": _textos(_primero(siguiente, "spokenLanguages.spokenLanguages", "_main.spokenLanguages.spokenLanguages")),
        "companies": _textos(
            _primero(siguiente, "production.edges", "_main.production.edges", "productionCompanies"),
            "companyText",
            "text",
        )[:6],
        "budget": _dinero(_primero(siguiente, "productionBudget", "_main.productionBudget")),
        "gross_worldwide": _dinero(_primero(siguiente, "worldwideGross", "_main.worldwideGross")),
        "similar": parecidos,
        "source": "imdb.com",
        "scraped_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    }
