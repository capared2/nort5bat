from scraper import urls


def test_normaliza_ficha_a_su_forma_canonica():
    variantes = [
        "https://www.imdb.com/title/tt0111161/?ref_=chttp_t_1",
        "http://imdb.com/title/tt0111161",
        "https://m.imdb.com/es/title/tt0111161/#reparto",
        "https://www.imdb.com/title/tt0111161/",
    ]
    assert {urls.normalize(v) for v in variantes} == {"https://www.imdb.com/title/tt0111161/"}


def test_reconoce_solo_la_ficha_no_sus_subpaginas():
    assert urls.is_title_url("https://www.imdb.com/title/tt0111161/")
    assert not urls.is_title_url("https://www.imdb.com/title/tt0111161/fullcredits/")
    assert not urls.is_title_url("https://www.imdb.com/name/nm0000209/")
    assert not urls.is_title_url("https://www.otrositio.com/title/tt0111161/")


def test_descarta_rutas_que_nunca_son_fichas():
    assert urls.is_excluded("https://www.imdb.com/search/title/?genres=drama")
    assert urls.is_excluded("https://www.imdb.com/es/list/ls123/")
    assert not urls.is_excluded("https://www.imdb.com/title/tt0111161/")


def test_identificadores():
    assert urls.title_id("https://www.imdb.com/title/tt0111161/") == "tt0111161"
    assert urls.name_id("https://www.imdb.com/name/nm0000209/") == "nm0000209"
    assert urls.title_id("https://www.imdb.com/chart/top/") is None
    assert urls.is_tconst("tt0111161") and not urls.is_tconst("ls0111161")


def test_el_genero_principal_es_el_que_mas_dice_de_la_pelicula():
    # "Alien" llega como Terror/Ciencia ficcion: manda el terror.
    assert urls.category_key(["Sci-Fi", "Horror"]) == "horror"
    # Un drama con aventura se archiva como aventura solo si no hay nada mas fuerte.
    assert urls.category_key(["Drama", "Crime"]) == "crime"
    assert urls.category_key(["Adventure", "Action"]) == "action"
    assert urls.category_key([]) == "sin-genero"
    assert urls.category_key(["Loquesea"]) == "sin-genero"


def test_slug_de_genero_valida_contra_la_lista_de_imdb():
    assert urls.genre_slug("Sci-Fi") == "sci-fi"
    assert urls.genre_slug("Film-Noir") == "film-noir"
    assert urls.genre_slug("Superheroes") == ""
