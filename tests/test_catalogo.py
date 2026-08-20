from scraper import catalogo
from tests.fake_site import FakeFetcher


def construir(**extra):
    return {f["id"]: f for f in catalogo.construir(FakeFetcher(), min_votos=1000, **extra)}


def test_solo_entra_lo_que_pasa_los_filtros():
    fichas = construir()
    # tt9999999 no llega a los votos, tt1111111 es un episodio y tt2222222 es de 1899.
    assert set(fichas) == {"tt0111161", "tt0068646"}


def test_la_ficha_tiene_la_misma_forma_que_la_del_html():
    ficha = construir()["tt0111161"]
    assert ficha["url"] == "https://www.imdb.com/title/tt0111161/"
    assert ficha["year"] == 1994
    assert ficha["runtime_minutes"] == 142
    assert ficha["rating"] == 9.3
    assert ficha["votes"] == 2900000
    assert ficha["genres"] == ["Drama"]
    assert ficha["category"] == "drama"
    assert ficha["source"] == "imdb-datasets"
    # Lo que los datasets no traen queda vacio, no ausente: el sitio lo espera.
    for campo in ("poster", "trailer", "release_date", "certificate", "metascore"):
        assert ficha[campo] is None
    assert ficha["plot"] == "" and ficha["images"] == [] and ficha["keywords"] == []


def test_el_titulo_se_traduce_prefiriendo_españa():
    fichas = construir()
    # Hay alias de ES y de MX: manda el de España.
    assert fichas["tt0111161"]["title"] == "Cadena perpetua"
    assert fichas["tt0111161"]["original_title"] == "The Shawshank Redemption"
    # Sin region pero declarado en español, tambien vale.
    assert fichas["tt0068646"]["title"] == "El padrino"


def test_equipo_y_reparto_salen_con_su_nombre_resuelto():
    ficha = construir()["tt0111161"]
    assert [d["name"] for d in ficha["directors"]] == ["Frank Darabont"]
    assert [g["name"] for g in ficha["writers"]] == ["Stephen King", "Frank Darabont"]
    assert ficha["cast"][0] == {
        "id": "nm0000209",
        "name": "Tim Robbins",
        "character": "Andy Dufresne",
        "image": None,
    }
    # El director aparece en principals pero no es reparto.
    assert all(quien["id"] != "nm0001104" for quien in ficha["cast"])


def test_se_puede_saltar_el_reparto_para_no_bajar_los_ficheros_grandes():
    falso = FakeFetcher()
    fichas = catalogo.construir(falso, min_votos=1000, con_reparto=False)
    assert all(f["cast"] == [] and f["directors"] == [] for f in fichas)
    assert not any("principals" in url for url in falso.pedidas)
    assert not any("name.basics" in url for url in falso.pedidas)


def test_el_limite_se_aplica_por_popularidad():
    fichas = catalogo.construir(FakeFetcher(), min_votos=1000, limite=1)
    assert [f["id"] for f in fichas] == ["tt0111161"]
