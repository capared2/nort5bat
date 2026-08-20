from scraper import urls


def test_normaliza_una_ficha_a_su_forma_canonica():
    variantes = [
        "https://www.rottentomatoes.com/m/The_Godfather?cmp=rt_leaderboard",
        "http://rottentomatoes.com/m/the_godfather/",
        "https://www.rottentomatoes.com/m/the_godfather#reparto",
        "https://www.rottentomatoes.com/m/the_godfather",
    ]
    assert {urls.normalize(v) for v in variantes} == {
        "https://www.rottentomatoes.com/m/the_godfather"
    }


def test_reconoce_la_ficha_pero_no_sus_subpaginas():
    assert urls.is_movie_url("https://www.rottentomatoes.com/m/the_godfather")
    assert not urls.is_movie_url("https://www.rottentomatoes.com/m/the_godfather/reviews")
    assert not urls.is_movie_url("https://www.rottentomatoes.com/celebrity/al_pacino")
    assert not urls.is_movie_url("https://www.otrositio.com/m/the_godfather")


def test_descarta_rutas_que_nunca_son_una_pelicula():
    assert urls.is_excluded("https://www.rottentomatoes.com/browse/movies_at_home/")
    assert urls.is_excluded("https://www.rottentomatoes.com/tv/the_sopranos")
    assert not urls.is_excluded("https://www.rottentomatoes.com/m/the_godfather")


def test_identificadores():
    assert urls.movie_id("https://www.rottentomatoes.com/m/the_godfather") == "the_godfather"
    assert urls.person_id("https://www.rottentomatoes.com/celebrity/al_pacino") == "al_pacino"
    assert urls.movie_id("https://www.rottentomatoes.com/browse/movies_at_home/") is None


def test_los_generos_llegan_traducidos():
    assert urls.genero_en_castellano("Mystery & Thriller") == "Misterio y suspense"
    assert urls.genero_en_castellano("Sci-Fi") == "Ciencia ficción"
    assert urls.genero_en_castellano("Kids & Family") == "Infantil y familiar"
    # Ya traducido, de una ficha que se vuelve a leer.
    assert urls.genero_en_castellano("Comedia") == "Comedia"
    assert urls.genero_en_castellano("Loquesea") == ""


def test_el_genero_principal_es_el_que_mas_dice_de_la_pelicula():
    assert urls.category_key(["Ciencia ficción", "Terror"]) == "terror"
    assert urls.category_key(["Drama", "Crimen"]) == "crimen"
    assert urls.category_key(["Aventura", "Acción"]) == "accion"
    assert urls.category_key([]) == "otros"


def test_la_caratula_se_pide_al_tamaño_que_haga_falta():
    # Las paginas la traen a 68x102, que es un sello de correos.
    pequena = "https://resizing.flixster.com/HASH=/68x102/v2/https://resizing.flixster.com/X=/a.jpg"
    assert "/300x450/" in urls.caratula(pequena)
    # Solo se cambia la primera medida: la URL interior no se toca.
    assert urls.caratula(pequena).count("x450") == 1
    assert urls.caratula(None) is None
