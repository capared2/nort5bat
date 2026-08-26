"""Dataset JSON troceado por genero, mas el estado reanudable de cada ejecucion."""
from __future__ import annotations

import json
import logging
import os
import re
import shutil
import threading
import unicodedata
from datetime import datetime, timezone
from pathlib import Path

from . import config
from . import urls as urlutil

log = logging.getLogger(__name__)

PART_TEMPLATE = "part-{:04d}.json"
TITLES_DIR = "titulos"        # ficha completa, en la carpeta de su genero principal
GENRES_DIR = "generos"        # lo mejor de cada genero, incluidos los secundarios
SEARCH_DIR = "buscar"         # indice de busqueda troceado por inicial
ROUTES_DIR = "rutas"          # id -> (genero, parte), troceado por final del id

RAIL_LIMIT = 40               # fichas por carrusel de la portada
GENRE_TOP_LIMIT = 200         # destacadas por genero
# Titulos por inicial. Ahora cada pelicula entra en varias letras, asi que el
# tope sube; las entradas llegan ordenadas por votos, de modo que si un cubo se
# llena lo que se cae es lo que nadie busca.
SEARCH_BUCKET_LIMIT = 4000
PLOT_PREVIEW = 200            # caracteres de sinopsis que viajan en una tarjeta

# Lo que necesita el frontend para pintar una tarjeta sin bajarse la ficha.
CARD_FIELDS = (
    "id", "category", "type", "title", "original_title", "year", "genres",
    "rating", "votes", "tomatometer", "audience_score", "runtime_minutes",
    "certificate", "poster",
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def _read_json(path: Path, default):
    if not path.exists():
        return default
    try:
        with path.open(encoding="utf-8") as handle:
            return json.load(handle)
    except (json.JSONDecodeError, OSError) as exc:
        log.error("JSON corrupto en %s (%s); se rehace ese fichero", path, exc)
        return default


def _write_json(path: Path, payload, volatiles: tuple[str, ...] = ("updated_at",)) -> bool:
    """Escritura atomica que no toca el fichero si el contenido no ha cambiado.

    Los indices se rehacen enteros en cada ejecucion. Sin esta comprobacion,
    cada run dejaria en git un diff de miles de ficheros identicos salvo por la
    marca de tiempo, y el repositorio crecería sin que hubiera nada nuevo.
    """
    path.parent.mkdir(parents=True, exist_ok=True)

    if isinstance(payload, dict) and volatiles:
        anterior = _read_json(path, None)
        if isinstance(anterior, dict):
            sin_fecha = {k: v for k, v in payload.items() if k not in volatiles}
            previo = {k: v for k, v in anterior.items() if k not in volatiles}
            if sin_fecha == previo:
                return False

    tmp = path.with_suffix(path.suffix + ".tmp")
    with tmp.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")
    os.replace(tmp, path)
    return True


def tarjeta(ficha: dict) -> dict:
    """Version ligera de una ficha: lo justo para una tarjeta con caratula."""
    resumen = {campo: ficha.get(campo) for campo in CARD_FIELDS}
    sinopsis = (ficha.get("plot") or "").strip()
    if len(sinopsis) > PLOT_PREVIEW:
        sinopsis = sinopsis[:PLOT_PREVIEW].rsplit(" ", 1)[0] + "…"
    resumen["plot"] = sinopsis
    resumen["directors"] = [d.get("name") for d in (ficha.get("directors") or [])[:2]]
    return resumen


# Palabras que no sirven para buscar: nadie teclea "el" esperando encontrar algo.
VACIAS = {
    "el", "la", "los", "las", "un", "una", "unos", "unas", "lo", "de", "del",
    "y", "en", "al", "a", "the", "of", "and", "an", "to", "in", "on", "for",
}


def _iniciales(titulo: str) -> set[str]:
    """Letras bajo las que se indexa un titulo para la busqueda.

    No basta con la primera: en castellano casi todo empieza por "El" o "La",
    y quien busca "padrino" no escribe "el padrino". Se indexa por la inicial
    de cada palabra que signifique algo, asi que "El padrino" se encuentra
    tanto por la "e" como por la "p".
    """
    limpio = unicodedata.normalize("NFKD", titulo or "")
    limpio = limpio.encode("ascii", "ignore").decode("ascii").lower()

    letras: set[str] = set()
    for palabra in re.split(r"[^a-z0-9]+", limpio):
        if not palabra or (palabra in VACIAS and len(letras) > 0):
            continue
        letras.add(palabra[0] if palabra[0].isalpha() else "0")
    return letras or {"other"}


def _orden(ficha: dict) -> tuple:
    """De mas conocido a menos: es el orden con el que se recorre todo el sitio."""
    return (-(ficha.get("votes") or 0), -(ficha.get("rating") or 0), ficha.get("id") or "")


class TitleStore:
    """Escribe ``data/titulos/<genero>/part-NNNN.json`` de tamaño acotado."""

    def __init__(self, data_dir: str | Path, shard_size: int):
        self.data_dir = Path(data_dir)
        self.shard_size = max(1, shard_size)
        self.sitemap_entries: list[dict] = []
        self._lock = threading.Lock()
        self._buffers: dict[str, list[dict]] = {}

    def add(self, ficha: dict) -> None:
        with self._lock:
            self._buffers.setdefault(ficha["category"], []).append(ficha)

    @property
    def pending_count(self) -> int:
        with self._lock:
            return sum(len(v) for v in self._buffers.values())

    def genre_dir(self, genero: str) -> Path:
        return self.data_dir / TITLES_DIR / genero

    def _parts(self, genero: str) -> list[Path]:
        directorio = self.genre_dir(genero)
        if not directorio.is_dir():
            return []
        return sorted(p for p in directorio.glob("part-*.json") if p.is_file())

    def flush(self) -> dict[str, int]:
        """Vuelca lo acumulado. Devuelve cuantas fichas nuevas por genero."""
        with self._lock:
            buffers, self._buffers = self._buffers, {}

        escritas: dict[str, int] = {}
        for genero, fichas in buffers.items():
            if fichas:
                escritas[genero] = self._append(genero, fichas)
        return escritas

    def _append(self, genero: str, fichas: list[dict]) -> int:
        """Añade fichas al ultimo trozo del genero, abriendo otro al llenarse.

        Una ficha ya guardada se sustituye en su sitio: las notas y los votos de
        IMDb cambian a diario y la gracia de volver a pasar por un titulo es
        justamente refrescarlos.
        """
        directorio = self.genre_dir(genero)
        directorio.mkdir(parents=True, exist_ok=True)

        # Donde vive cada ficha ya guardada de este genero.
        ubicacion: dict[str, Path] = {}
        contenidos: dict[Path, dict] = {}
        for parte in self._parts(genero):
            payload = _read_json(parte, None)
            if not isinstance(payload, dict):
                continue
            contenidos[parte] = payload
            for existente in payload.get("titles", []):
                if existente.get("id"):
                    ubicacion[existente["id"]] = parte

        partes = self._parts(genero)
        indice = int(partes[-1].stem.split("-")[-1]) if partes else 1
        actual = directorio / PART_TEMPLATE.format(indice)
        payload = contenidos.get(actual) or _read_json(actual, None)
        cubo = payload.get("titles", []) if isinstance(payload, dict) else []

        tocados: set[Path] = set()
        nuevas = 0
        for ficha in fichas:
            anterior = ubicacion.get(ficha["id"])
            if anterior is not None:
                # Se sustituye dentro de la propia lista, sin crear otra: puede
                # ser la misma que ``cubo``, y cambiarla por una copia perderia
                # la actualizacion al guardar el trozo en curso.
                lista = contenidos[anterior].get("titles", [])
                for posicion, guardada in enumerate(lista):
                    if guardada.get("id") == ficha["id"]:
                        lista[posicion] = ficha
                        break
                tocados.add(anterior)
                continue

            if len(cubo) >= self.shard_size:
                self._save_part(actual, genero, indice, cubo)
                tocados.discard(actual)
                indice += 1
                actual = directorio / PART_TEMPLATE.format(indice)
                cubo = []
            cubo.append(ficha)
            ubicacion[ficha["id"]] = actual
            nuevas += 1

        for parte in tocados:
            if parte != actual:
                self._save_part(parte, genero, int(parte.stem.split("-")[-1]),
                                contenidos[parte].get("titles", []))
        self._save_part(actual, genero, indice, cubo)
        return nuevas

    @staticmethod
    def _save_part(path: Path, genero: str, indice: int, fichas: list[dict]) -> None:
        # Orden estable por identificador: asi un fichero solo cambia en git
        # cuando cambia lo que contiene, no cuando cambia el orden de llegada.
        fichas.sort(key=lambda f: f.get("id") or "")
        _write_json(
            path,
            {
                "genre": genero,
                "part": indice,
                "count": len(fichas),
                "updated_at": _now(),
                "titles": fichas,
            },
        )

    # -- indices ---------------------------------------------------------
    def rebuild_index(self) -> dict:
        """Rehace indices, carruseles de portada, listas por genero y busqueda."""
        # Primero se limpia y despues se indexa lo que queda: al reves, un
        # genero retirado seguiria colandose en el indice de esta pasada.
        self._limpiar_restos()
        self._purgar_duplicados()

        generos: list[dict] = []
        lookups: dict[str, dict[str, int]] = {}
        tarjetas: list[dict] = []
        self.sitemap_entries = []
        total = 0

        raiz = self.data_dir / TITLES_DIR
        for parte in sorted(raiz.rglob("part-*.json")) if raiz.is_dir() else []:
            payload = _read_json(parte, {})
            genero = payload.get("genre")
            if not genero:
                continue
            lookup = lookups.setdefault(genero, {})
            for ficha in payload.get("titles", []):
                if not ficha.get("id"):
                    continue
                lookup[ficha["id"]] = payload.get("part", 1)
                tarjetas.append(tarjeta(ficha))
                self.sitemap_entries.append(
                    {
                        "id": ficha["id"],
                        "category": ficha.get("category"),
                        "title": ficha.get("title", ""),
                        "poster": ficha.get("poster"),
                        "updated_at": ficha.get("scraped_at"),
                    }
                )

            relativo = parte.relative_to(self.data_dir).as_posix()
            entrada = next((g for g in generos if g["genre"] == genero), None)
            if entrada is None:
                entrada = {
                    "genre": genero,
                    "name": config.GENRES.get(genero, genero.replace("-", " ").title()),
                    "titles": 0,
                    "files": [],
                }
                generos.append(entrada)
            entrada["titles"] += payload.get("count", 0)
            entrada["files"].append({"file": relativo, "count": payload.get("count", 0)})
            total += payload.get("count", 0)

        generos.sort(key=lambda g: (-g["titles"], g["genre"]))
        tarjetas.sort(key=_orden)

        for genero, lookup in lookups.items():
            _write_json(
                self.genre_dir(genero) / "lookup.json",
                {"genre": genero, "count": len(lookup), "parts": lookup},
                volatiles=(),
            )

        self._escribir_rutas(lookups)
        self._escribir_portada(tarjetas)
        destacadas = self._escribir_generos(tarjetas)
        self._escribir_busqueda(tarjetas)

        # Hay generos que nunca ganan como principal ("Aventura" siempre cede
        # ante "Accion"): sin esto no aparecerian en el menu aunque tengan lista.
        conocidos = {g["genre"] for g in generos}
        for clave, cuantos in destacadas.items():
            if clave not in conocidos:
                generos.append({
                    "genre": clave,
                    "name": config.GENRES.get(clave, clave),
                    "titles": 0,
                    "files": [],
                })
        for entrada in generos:
            entrada["tagged"] = destacadas.get(entrada["genre"], 0)
        generos.sort(key=lambda g: (-g["tagged"], -g["titles"], g["genre"]))

        indice = {
            "source": "rottentomatoes.com",
            "generated_at": _now(),
            "total_titles": total,
            "total_genres": len(generos),
            "genres": generos,
        }
        _write_json(self.data_dir / "index.json", indice, volatiles=("generated_at",))
        return indice

    def _purgar_duplicados(self) -> int:
        """Deja una sola copia de cada ficha, la mas reciente.

        Una ficha vive en la carpeta de su genero principal, y ese genero puede
        cambiar entre ejecuciones: basta con que la pagina añada o quite un
        genero, o con que la anterior viniera sin ninguno y cayera en "other".
        ``_append`` solo mira la carpeta del genero que le toca, asi que la
        copia vieja se quedaba donde estaba y el archivo acababa con la misma
        pelicula dos veces.

        No era un adorno: ``_escribir_rutas`` resuelve el id contra el ultimo
        genero que lo declara, de modo que la direccion publica podia acabar
        sirviendo justo la copia caducada, con los datos de hace dias. Ademas
        inflaba ``total_titles``, repetia la URL en el sitemap y colaba la
        pelicula en un genero al que ya no pertenece.

        Se hace aqui, antes de indexar, para que rutas, portada, listas de
        genero, busqueda y sitemaps se construyan ya sobre el archivo limpio, y
        para que una ejecucion repare de paso los duplicados que quedaran de
        antes.
        """
        raiz = self.data_dir / TITLES_DIR
        if not raiz.is_dir():
            return 0

        # identificador -> [(fecha de scrapeo, fichero, posicion en el fichero)]
        copias: dict[str, list[tuple[str, Path, int]]] = {}
        contenidos: dict[Path, dict] = {}
        for parte in sorted(raiz.rglob("part-*.json")):
            payload = _read_json(parte, None)
            if not isinstance(payload, dict):
                continue
            contenidos[parte] = payload
            for posicion, ficha in enumerate(payload.get("titles", [])):
                if ficha.get("id"):
                    copias.setdefault(ficha["id"], []).append(
                        (ficha.get("scraped_at") or "", parte, posicion)
                    )

        # La copia buena es la ultima que se guardo. El fichero desempata para
        # que dos ejecuciones sobre el mismo archivo decidan igual.
        sobran: dict[Path, set[int]] = {}
        for identificador, entradas in copias.items():
            if len(entradas) < 2:
                continue
            entradas.sort(key=lambda entrada: (entrada[0], entrada[1].as_posix()), reverse=True)
            log.info(
                "ficha duplicada %s: se conserva %s y se retiran %s",
                identificador,
                entradas[0][1].relative_to(self.data_dir).as_posix(),
                ", ".join(e[1].relative_to(self.data_dir).as_posix() for e in entradas[1:]),
            )
            for _, parte, posicion in entradas[1:]:
                sobran.setdefault(parte, set()).add(posicion)

        for parte, descartadas in sobran.items():
            fichas = contenidos[parte].get("titles", [])
            quedan = [f for i, f in enumerate(fichas) if i not in descartadas]
            if quedan:
                self._save_part(
                    parte,
                    contenidos[parte].get("genre") or parte.parent.name,
                    int(parte.stem.split("-")[-1]),
                    quedan,
                )
            else:
                # Un trozo vacio solo seria ruido en el indice y en git.
                parte.unlink()
                # Y si era el ultimo del genero, la carpeta se va con el: si no,
                # quedaria con su lookup.json de la pasada anterior y nada mas.
                if not any(parte.parent.glob("part-*.json")):
                    shutil.rmtree(parte.parent, ignore_errors=True)

        return sum(len(descartadas) for descartadas in sobran.values())

    def _limpiar_restos(self) -> None:
        """Borra las carpetas de generos que ya no existen.

        Cuando cambia la tabla de generos, las carpetas viejas se quedan ahi y
        el indice las sigue anunciando. Limpiarlas aqui permite hacer el cambio
        en una sola ejecucion, sin tener que vaciar el archivo a mano y dejar
        el sitio sin nada mientras se rehace.
        """
        vivos = set(config.GENRES)

        raiz = self.data_dir / TITLES_DIR
        for carpeta in sorted(raiz.iterdir()) if raiz.is_dir() else []:
            if carpeta.is_dir() and carpeta.name not in vivos:
                log.info("genero retirado: se borra %s", carpeta)
                shutil.rmtree(carpeta)

        listas = self.data_dir / GENRES_DIR
        for fichero in sorted(listas.glob("*.json")) if listas.is_dir() else []:
            if fichero.stem not in vivos:
                log.info("genero retirado: se borra %s", fichero)
                fichero.unlink()

    def _escribir_rutas(self, lookups: dict[str, dict[str, int]]) -> None:
        """Resuelve un identificador a su fichero sin leer el archivo entero.

        La direccion publica de una pelicula es solo su id, para que no se rompa
        el dia que cambie de genero principal. A cambio hace falta esto: cien
        cubos por las dos ultimas cifras del id, de modo que dar con una ficha
        cueste siempre una lectura pequeña.
        """
        cubos: dict[str, dict[str, list]] = {}
        for genero, lookup in lookups.items():
            for identificador, parte in lookup.items():
                cubos.setdefault(identificador[-2:], {})[identificador] = [genero, parte]

        for sufijo, entradas in cubos.items():
            _write_json(
                self.data_dir / ROUTES_DIR / f"{sufijo}.json",
                {"bucket": sufijo, "count": len(entradas), "titles": dict(sorted(entradas.items()))},
                volatiles=(),
            )

    def _escribir_portada(self, tarjetas: list[dict]) -> None:
        """Los carruseles de la portada, en un solo fichero.

        Va todo junto a proposito: la portada se pinta en el edge de Cloudflare
        y cada peticion extra al dataset es tiempo que no tiene.
        """
        populares = tarjetas[:RAIL_LIMIT]

        # Para "mejor valoradas" no vale la nota a secas: una pelicula con
        # cuarenta votos y un 9,4 no compite con "El padrino".
        con_aval = [t for t in tarjetas if (t.get("votes") or 0) >= 25_000 and t.get("rating")]
        mejor = sorted(con_aval, key=lambda t: (-(t["rating"] or 0), -(t.get("votes") or 0)))[:RAIL_LIMIT]

        con_anio = [t for t in tarjetas if isinstance(t.get("year"), int)]
        recientes = sorted(
            con_anio, key=lambda t: (-(t["year"] or 0), -(t.get("votes") or 0))
        )[:RAIL_LIMIT]

        clasicos = sorted(
            [t for t in con_aval if (t.get("year") or 9999) < 1990],
            key=lambda t: (-(t["rating"] or 0), -(t.get("votes") or 0)),
        )[:RAIL_LIMIT]

        _write_json(
            self.data_dir / "portada.json",
            {
                "generated_at": _now(),
                "populares": populares,
                "mejor_valoradas": mejor,
                "recientes": recientes,
                "clasicos": clasicos,
            },
            volatiles=("generated_at",),
        )

    def _escribir_generos(self, tarjetas: list[dict]) -> dict[str, int]:
        """Lo mejor de cada genero, contando tambien los generos secundarios.

        Una ficha vive en la carpeta de su genero principal, pero "Alien" tiene
        que salir en terror y en ciencia ficcion. Estas listas son la unica
        copia cruzada, y van acotadas para que no se disparen.
        """
        por_genero: dict[str, list[dict]] = {}
        for carta in tarjetas:
            for nombre in carta.get("genres") or []:
                clave = urlutil.genre_slug(nombre)
                if clave:
                    por_genero.setdefault(clave, []).append(carta)

        cuentas: dict[str, int] = {}
        for clave, lista in por_genero.items():
            recortada = lista[:GENRE_TOP_LIMIT]      # ya venian ordenadas por _orden
            cuentas[clave] = len(lista)
            _write_json(
                self.data_dir / GENRES_DIR / f"{clave}.json",
                {
                    "genre": clave,
                    "name": config.GENRES.get(clave, clave),
                    "count": len(lista),
                    "titles": recortada,
                },
                volatiles=(),
            )
        return cuentas

    def _escribir_busqueda(self, tarjetas: list[dict]) -> None:
        """Indice de busqueda troceado por inicial del titulo.

        Buscar "matrix" solo debe costar un fichero. Las entradas van como
        tuplas y sin caratula: el buscador enseña una lista, y asi cada trozo
        se queda en decenas de kilobytes.
        """
        cubos: dict[str, list[list]] = {}
        for carta in tarjetas:
            for titulo in {carta.get("title"), carta.get("original_title")}:
                if not titulo:
                    continue
                entrada = [
                    carta["id"], carta["category"], titulo, carta.get("year"), carta.get("rating")
                ]
                for letra in _iniciales(titulo):
                    cubos.setdefault(letra, []).append(entrada)

        destino = self.data_dir / SEARCH_DIR
        for letra, entradas in cubos.items():
            vistas: set[tuple] = set()
            unicas = [e for e in entradas if not (tuple(e[:3]) in vistas or vistas.add(tuple(e[:3])))]
            _write_json(
                destino / f"{letra}.json",
                {"letter": letra, "count": len(unicas), "titles": unicas[:SEARCH_BUCKET_LIMIT]},
                volatiles=(),
            )

        _write_json(
            destino / "index.json",
            {"letters": sorted(cubos), "count": sum(len(v) for v in cubos.values())},
            volatiles=(),
        )


class RunState:
    """Guarda lo ya visitado, la cola pendiente y los fallos por URL."""

    def __init__(self, state_dir: str | Path, max_failures: int = 3):
        self.state_dir = Path(state_dir)
        self.seen_path = self.state_dir / "seen.txt"
        self.pending_path = self.state_dir / "pending.txt"
        self.failed_path = self.state_dir / "failed.json"
        self.meta_path = self.state_dir / "run.json"
        self.max_failures = max(1, max_failures)

        self.seen: set[str] = self._read_lines(self.seen_path)
        self.pending: list[str] = [
            u for u in self._read_ordered(self.pending_path) if u not in self.seen
        ]
        fallidas = _read_json(self.failed_path, {})
        self.failed: dict[str, int] = fallidas if isinstance(fallidas, dict) else {}
        # Por donde iba el refresco: sin esto se repasarian siempre las mismas
        # fichas y el resto del archivo envejeceria sin que nadie lo mirase.
        meta = _read_json(self.meta_path, {})
        self.refresh_cursor: int = meta.get("refresh_cursor", 0) if isinstance(meta, dict) else 0
        self._lock = threading.Lock()

    def _agotadas(self) -> set[str]:
        return {url for url, veces in self.failed.items() if veces >= self.max_failures}

    @staticmethod
    def _read_lines(path: Path) -> set[str]:
        if not path.exists():
            return set()
        with path.open(encoding="utf-8") as handle:
            return {linea.strip() for linea in handle if linea.strip()}

    @staticmethod
    def _read_ordered(path: Path) -> list[str]:
        if not path.exists():
            return []
        with path.open(encoding="utf-8") as handle:
            return [linea.strip() for linea in handle if linea.strip()]

    def enqueue(self, candidatas) -> int:
        """Encola lo que no se ha visto, respetando el orden de prioridad."""
        with self._lock:
            conocidas = self.seen | set(self.pending) | self._agotadas()
            nuevas = 0
            for url in candidatas:
                if url not in conocidas:
                    self.pending.append(url)
                    conocidas.add(url)
                    nuevas += 1
            return nuevas

    def take(self, cuantas: int) -> list[str]:
        with self._lock:
            lote = self.pending[:cuantas]
            self.pending = self.pending[cuantas:]
            return lote

    def mark_seen(self, url: str) -> None:
        with self._lock:
            self.seen.add(url)
            self.failed.pop(url, None)

    def mark_failed(self, url: str) -> None:
        with self._lock:
            self.failed[url] = self.failed.get(url, 0) + 1

    def rotar(self, cuantas: int) -> list[str]:
        """Las siguientes ``cuantas`` fichas del archivo, dando la vuelta al final.

        El cursor se guarda con el estado, de modo que cada ejecucion repasa un
        tramo distinto y en unas cuantas pasadas se recorre el archivo entero.
        """
        with self._lock:
            if cuantas <= 0 or not self.seen:
                return []
            todas = sorted(self.seen)
            arranque = self.refresh_cursor % len(todas)
            tramo = todas[arranque : arranque + cuantas]
            if len(tramo) < cuantas:
                tramo += todas[: cuantas - len(tramo)]      # da la vuelta
            self.refresh_cursor = (arranque + len(tramo)) % len(todas)
            return tramo

    def forget(self, urls) -> int:
        """Saca URLs de lo ya visto para volver a pasar por ellas.

        Es lo que permite refrescar notas y votos sin rehacer el dataset.
        """
        with self._lock:
            fuera = [u for u in urls if u in self.seen]
            self.seen.difference_update(fuera)
            return len(fuera)

    def requeue(self, urls) -> None:
        with self._lock:
            self.pending = list(urls) + self.pending

    def save(self, meta: dict | None = None) -> None:
        self.state_dir.mkdir(parents=True, exist_ok=True)
        with self._lock:
            self._write_lines(self.seen_path, sorted(self.seen))
            self._write_lines(self.pending_path, self.pending)
            _write_json(self.failed_path, dict(sorted(self.failed.items())), volatiles=())
            payload = {
                "updated_at": _now(),
                "seen": len(self.seen),
                "pending": len(self.pending),
                "failed": len(self.failed),
                "abandoned": len(self._agotadas()),
                "refresh_cursor": self.refresh_cursor,
            }
            payload.update(meta or {})
            _write_json(self.meta_path, payload, volatiles=("updated_at",))

    @staticmethod
    def _write_lines(path: Path, lineas) -> None:
        tmp = path.with_suffix(path.suffix + ".tmp")
        with tmp.open("w", encoding="utf-8") as handle:
            for linea in lineas:
                handle.write(f"{linea}\n")
        os.replace(tmp, path)
