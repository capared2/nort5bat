import json

import pytest

from scraper import runner
from scraper.runner import Options
from tests.fake_site import FakeFetcher


@pytest.fixture
def falso(monkeypatch):
    doble = FakeFetcher()
    monkeypatch.setattr(runner, "Fetcher", lambda **kwargs: doble)
    return doble


def opciones(tmp_path, **extra):
    base = dict(
        sources=["charts"],
        data_dir=str(tmp_path / "data"),
        state_dir=str(tmp_path / "state"),
        workers=2,
        delay=0,
        time_budget=0,
        follow_similar=False,
    )
    base.update(extra)
    return Options(**base)


def test_de_punta_a_punta_descubre_guarda_e_indexa(tmp_path, falso):
    resumen = runner.run(opciones(tmp_path))

    assert resumen["discovered"] == 2
    assert resumen["queued"] == 2
    assert resumen["saved"] == 2
    assert resumen["failed"] == 0

    # El sitio falso sirve la misma ficha para las dos URLs, pero el tconst
    # sale de la URL pedida: son dos titulos distintos.
    assert resumen["total_titles"] == 2
    indice = json.loads((tmp_path / "data" / "index.json").read_text())
    assert indice["source"] == "imdb.com"
    assert (tmp_path / "data" / "portada.json").exists()
    assert (tmp_path / "data" / "seo" / "sitemap.xml").exists()
    assert (tmp_path / "data" / "titulos" / "crime" / "part-0001.json").exists()


def test_el_tope_de_titulos_deja_lo_demas_en_la_cola(tmp_path, falso):
    resumen = runner.run(opciones(tmp_path, max_titles=1))
    assert resumen["fetched"] == 1
    estado = json.loads((tmp_path / "state" / "run.json").read_text())
    assert estado["pending"] == 1


def test_una_segunda_pasada_no_vuelve_a_pedir_lo_ya_visto(tmp_path, falso):
    runner.run(opciones(tmp_path))
    falso.pedidas.clear()

    resumen = runner.run(opciones(tmp_path))
    assert resumen["queued"] == 0
    assert resumen["fetched"] == 0
    # Se vuelven a mirar las listas publicas, pero ninguna ficha se repite.
    assert falso.pedidas and all("/chart/" in url for url in falso.pedidas)


def test_el_refresco_vuelve_a_pasar_por_las_fichas_guardadas(tmp_path, falso):
    runner.run(opciones(tmp_path))
    resumen = runner.run(opciones(tmp_path, refresh=5, skip_discovery=True))
    assert resumen["refreshed"] > 0
    assert resumen["fetched"] == resumen["refreshed"]


def test_los_titulos_parecidos_se_encolan_solos(tmp_path, falso):
    resumen = runner.run(opciones(tmp_path, follow_similar=True, max_titles=1))
    pendientes = (tmp_path / "state" / "pending.txt").read_text().split()
    assert "https://www.imdb.com/title/tt0071562/" in pendientes
    assert resumen["saved"] == 1


def test_una_ficha_que_no_baja_cuenta_como_fallo(tmp_path, monkeypatch):
    doble = FakeFetcher(fallos={"https://www.imdb.com/title/tt0068646/"})
    monkeypatch.setattr(runner, "Fetcher", lambda **kwargs: doble)

    resumen = runner.run(opciones(tmp_path))
    assert resumen["failed"] == 1
    assert resumen["saved"] == 1
    fallidas = json.loads((tmp_path / "state" / "failed.json").read_text())
    assert fallidas == {"https://www.imdb.com/title/tt0068646/": 1}
