"""Genera los sitemaps del sitio a partir del dataset.

Se hacen aqui, en la misma pasada que los indices, por dos razones: quedan al
dia solos en cada ejecucion, y el sitio los sirve tal cual, sin gastar CPU en
construirlos por peticion (Cloudflare Workers corta a los 10 ms en el plan
gratuito).
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from pathlib import Path
from xml.sax.saxutils import escape

log = logging.getLogger(__name__)

# El protocolo admite 50.000 URLs por fichero; se usa la mitad para que cada
# uno sea rapido de servir.
URLS_POR_SITEMAP = 25_000


def _ahora() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _escribir(ruta: Path, contenido: str) -> None:
    """Solo toca el disco si el XML cambio, para no ensuciar el historial."""
    ruta.parent.mkdir(parents=True, exist_ok=True)
    if ruta.exists() and ruta.read_text(encoding="utf-8") == contenido:
        return
    ruta.write_text(contenido, encoding="utf-8")


def _urlset(urls: list[str], espacios: str = "") -> str:
    cabecera = f'<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9"{espacios}>'
    return "\n".join(['<?xml version="1.0" encoding="UTF-8"?>', cabecera, *urls, "</urlset>", ""])


def _entrada(
    loc: str,
    lastmod: str | None = None,
    prioridad: str | None = None,
    frecuencia: str | None = None,
    extra: str = "",
) -> str:
    partes = ["  <url>", f"    <loc>{escape(loc)}</loc>"]
    if lastmod:
        partes.append(f"    <lastmod>{lastmod}</lastmod>")
    if frecuencia:
        partes.append(f"    <changefreq>{frecuencia}</changefreq>")
    if prioridad:
        partes.append(f"    <priority>{prioridad}</priority>")
    if extra:
        partes.append(extra)
    partes.append("  </url>")
    return "\n".join(partes)


def construir(
    data_dir: str | Path,
    site_url: str,
    titulos: list[dict],
    generos: list[dict],
) -> dict:
    """Escribe los sitemaps en ``data/seo/``.

    ``titulos`` son entradas ligeras {id, category, title, poster, updated_at};
    ``generos`` es lo que ya publica index.json.
    """
    base = site_url.rstrip("/")
    destino = Path(data_dir) / "seo"

    # Orden estable: sin esto, cada ejecucion reordenaria ficheros enteros y el
    # repositorio se llenaria de diffs que no dicen nada.
    ordenados = sorted(titulos, key=lambda t: t.get("id") or "")

    trozos: list[str] = []
    for numero, comienzo in enumerate(range(0, len(ordenados), URLS_POR_SITEMAP), start=1):
        lote = ordenados[comienzo : comienzo + URLS_POR_SITEMAP]
        urls = []
        for ficha in lote:
            # La caratula en el sitemap: es lo que mete la pelicula en Google
            # Imagenes, que para un sitio de cine trae mucha visita.
            imagen = ""
            if ficha.get("poster"):
                imagen = (
                    "    <image:image>\n"
                    f"      <image:loc>{escape(ficha['poster'])}</image:loc>\n"
                    f"      <image:title>{escape(ficha.get('title', ''))}</image:title>\n"
                    "    </image:image>"
                )
            urls.append(
                _entrada(
                    f"{base}/movie/{ficha['id']}",
                    ficha.get("updated_at"),
                    prioridad="0.7",
                    frecuencia="weekly",
                    extra=imagen,
                )
            )
        nombre = f"sitemap-movies-{numero:04d}.xml"
        _escribir(
            destino / nombre,
            _urlset(urls, ' xmlns:image="http://www.google.com/schemas/sitemap-image/1.1"'),
        )
        trozos.append(nombre)

    fijas = [
        _entrada(f"{base}/", _ahora(), "1.0", "daily"),
        _entrada(f"{base}/genres", _ahora(), "0.6", "weekly"),
        _entrada(f"{base}/top", _ahora(), "0.8", "daily"),
    ]
    for genero in sorted(generos, key=lambda g: g.get("genre", "")):
        clave = genero.get("genre")
        if clave:
            fijas.append(_entrada(f"{base}/genre/{clave}", _ahora(), "0.7", "daily"))
    _escribir(destino / "sitemap-genres.xml", _urlset(fijas))

    hijos = ["sitemap-genres.xml", *trozos]
    lineas = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<sitemapindex xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">',
    ]
    for hijo in hijos:
        lineas += [
            "  <sitemap>",
            f"    <loc>{base}/{hijo}</loc>",
            f"    <lastmod>{_ahora()}</lastmod>",
            "  </sitemap>",
        ]
    lineas += ["</sitemapindex>", ""]
    _escribir(destino / "sitemap.xml", "\n".join(lineas))

    manifiesto = {
        "generated_at": _ahora(),
        "site_url": base,
        "total_urls": len(ordenados) + len(fijas),
        "sitemaps": hijos,
    }
    log.info("SEO: %s URLs en %s sitemaps", manifiesto["total_urls"], len(hijos))
    return manifiesto
