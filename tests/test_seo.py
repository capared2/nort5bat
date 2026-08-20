from scraper import seo


def entrada(slug, genero="drama"):
    return {
        "id": slug,
        "category": genero,
        "title": f"Pelicula {slug}",
        "poster": f"https://resizing.flixster.com/AAA=/300x450/v2/{slug}.jpg",
        "updated_at": "2026-08-20T10:00:00Z",
    }


def test_construye_indice_sitemap_de_generos_y_de_peliculas(tmp_path):
    manifiesto = seo.construir(
        tmp_path,
        "https://nort5.com/",
        [entrada("the_godfather"), entrada("alien", "terror")],
        [{"genre": "drama"}, {"genre": "terror"}],
    )

    assert manifiesto["site_url"] == "https://nort5.com"
    assert manifiesto["sitemaps"] == ["sitemap-generos.xml", "sitemap-peliculas-0001.xml"]

    peliculas = (tmp_path / "seo" / "sitemap-peliculas-0001.xml").read_text()
    assert "https://nort5.com/pelicula/the_godfather" in peliculas
    assert "https://nort5.com/pelicula/alien" in peliculas
    # La caratula viaja en el sitemap para entrar en Google Imagenes.
    assert "<image:loc>https://resizing.flixster.com/AAA=/300x450/v2/the_godfather.jpg</image:loc>" in peliculas

    generos = (tmp_path / "seo" / "sitemap-generos.xml").read_text()
    assert "https://nort5.com/genero/terror" in generos
    assert "https://nort5.com/top" in generos

    indice = (tmp_path / "seo" / "sitemap.xml").read_text()
    assert indice.count("<sitemap>") == 2


def test_escapa_lo_que_hay_que_escapar(tmp_path):
    peligrosa = entrada("tom_y_jerry")
    peligrosa["title"] = 'Tom & Jerry: "El regreso"'
    seo.construir(tmp_path, "https://nort5.com", [peligrosa], [])
    xml = (tmp_path / "seo" / "sitemap-peliculas-0001.xml").read_text()
    assert "Tom &amp; Jerry" in xml and "&" not in xml.replace("&amp;", "").replace("&quot;", "")


def test_no_reescribe_un_sitemap_identico(tmp_path):
    datos = ([entrada("the_godfather")], [{"genre": "drama"}])
    seo.construir(tmp_path, "https://nort5.com", *datos)
    fichero = tmp_path / "seo" / "sitemap-peliculas-0001.xml"
    antes = fichero.stat().st_mtime_ns

    seo.construir(tmp_path, "https://nort5.com", *datos)
    assert fichero.stat().st_mtime_ns == antes
