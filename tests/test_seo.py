from scraper import seo


def entrada(tconst, genero="drama"):
    return {
        "id": tconst,
        "category": genero,
        "title": f"Pelicula {tconst}",
        "poster": f"https://m.media-amazon.com/{tconst}.jpg",
        "updated_at": "2026-08-20T10:00:00Z",
    }


def test_construye_indice_sitemap_de_generos_y_de_peliculas(tmp_path):
    manifiesto = seo.construir(
        tmp_path,
        "https://nort5.com/",
        [entrada("tt0000001"), entrada("tt0000002", "horror")],
        [{"genre": "drama"}, {"genre": "horror"}],
    )

    assert manifiesto["site_url"] == "https://nort5.com"
    assert manifiesto["sitemaps"] == ["sitemap-generos.xml", "sitemap-peliculas-0001.xml"]

    peliculas = (tmp_path / "seo" / "sitemap-peliculas-0001.xml").read_text()
    assert "https://nort5.com/pelicula/tt0000001" in peliculas
    assert "https://nort5.com/pelicula/tt0000002" in peliculas
    # La caratula viaja en el sitemap para entrar en Google Imagenes.
    assert "<image:loc>https://m.media-amazon.com/tt0000001.jpg</image:loc>" in peliculas

    generos = (tmp_path / "seo" / "sitemap-generos.xml").read_text()
    assert "https://nort5.com/genero/horror" in generos
    assert "https://nort5.com/top" in generos

    indice = (tmp_path / "seo" / "sitemap.xml").read_text()
    assert indice.count("<sitemap>") == 2


def test_escapa_lo_que_hay_que_escapar(tmp_path):
    peligrosa = entrada("tt0000003")
    peligrosa["title"] = 'Tom & Jerry: "El regreso"'
    seo.construir(tmp_path, "https://nort5.com", [peligrosa], [])
    xml = (tmp_path / "seo" / "sitemap-peliculas-0001.xml").read_text()
    assert "Tom &amp; Jerry" in xml and "&" not in xml.replace("&amp;", "").replace("&quot;", "")


def test_no_reescribe_un_sitemap_identico(tmp_path):
    datos = ([entrada("tt0000001")], [{"genre": "drama"}])
    seo.construir(tmp_path, "https://nort5.com", *datos)
    fichero = tmp_path / "seo" / "sitemap-peliculas-0001.xml"
    antes = fichero.stat().st_mtime_ns

    seo.construir(tmp_path, "https://nort5.com", *datos)
    assert fichero.stat().st_mtime_ns == antes
