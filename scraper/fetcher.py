"""Capa HTTP: sesion con freno, reintentos y respeto a robots.txt."""
from __future__ import annotations

import gzip
import io
import logging
import random
import threading
import time
from dataclasses import dataclass
from typing import Iterator
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import requests

from . import config

log = logging.getLogger(__name__)

RETRYABLE_STATUS = {408, 425, 429, 500, 502, 503, 504}


@dataclass
class Response:
    url: str
    status: int
    text: str
    content_type: str


class RateLimiter:
    """Separacion minima entre peticiones, compartida por todos los hilos."""

    def __init__(self, delay: float):
        self.delay = max(0.0, delay)
        self._lock = threading.Lock()
        self._next_at = 0.0

    def wait(self) -> None:
        if self.delay <= 0:
            return
        with self._lock:
            now = time.monotonic()
            sleep_for = max(0.0, self._next_at - now)
            self._next_at = max(now, self._next_at) + self.delay
        if sleep_for > 0:
            time.sleep(sleep_for)

    def set_delay(self, delay: float) -> None:
        with self._lock:
            self.delay = max(0.0, delay)


class Fetcher:
    """Cliente HTTP seguro entre hilos que no maltrata al origen."""

    def __init__(
        self,
        user_agent: str = config.DEFAULT_USER_AGENT,
        delay: float = config.DEFAULT_DELAY,
        timeout: int = config.DEFAULT_TIMEOUT,
        retries: int = config.DEFAULT_RETRIES,
        respect_robots: bool = True,
    ):
        self.user_agent = user_agent
        self.timeout = timeout
        self.retries = retries
        self.respect_robots = respect_robots
        self.limiter = RateLimiter(delay)
        self.session = requests.Session()
        self.session.headers.update(
            {
                "User-Agent": user_agent,
                "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
                # IMDb decide el idioma de la ficha con esta cabecera. Se pide
                # en ingles a proposito: los titulos originales son la clave
                # con la que todo el mundo busca una pelicula.
                "Accept-Language": "en-US,en;q=0.9",
            }
        )
        self._robots: dict[str, RobotFileParser | None] = {}
        self._robots_lock = threading.Lock()
        self.stats = {"requests": 0, "errors": 0, "blocked": 0}

    # -- robots -----------------------------------------------------------
    def _robots_for(self, url: str) -> RobotFileParser | None:
        parts = urlsplit(url)
        origin = f"{parts.scheme}://{parts.netloc}"
        with self._robots_lock:
            if origin in self._robots:
                return self._robots[origin]
        parser: RobotFileParser | None = None
        try:
            self.stats["requests"] += 1
            resp = self.session.get(f"{origin}/robots.txt", timeout=self.timeout)
            if resp.status_code == 200:
                parser = RobotFileParser()
                parser.parse(resp.text.splitlines())
                delay = parser.crawl_delay(self.user_agent)
                if delay and float(delay) > self.limiter.delay:
                    log.info("robots.txt pide crawl-delay=%ss en %s; obedecemos", delay, origin)
                    self.limiter.set_delay(float(delay))
        except requests.RequestException as exc:
            log.warning("no se pudo leer robots.txt de %s: %s", origin, exc)
        with self._robots_lock:
            self._robots[origin] = parser
        return parser

    def allowed(self, url: str) -> bool:
        if not self.respect_robots:
            return True
        parser = self._robots_for(url)
        if parser is None:
            return True
        return parser.can_fetch(self.user_agent, url)

    def sitemaps_from_robots(self, origin: str) -> list[str]:
        parser = self._robots_for(origin)
        if parser is None:
            return []
        return list(getattr(parser, "sitemaps", None) or [])

    # -- descargas --------------------------------------------------------
    def _request(self, url: str, stream: bool = False):
        """Peticion con reintentos. Devuelve la respuesta cruda de requests."""
        if not self.allowed(url):
            self.stats["blocked"] += 1
            log.debug("robots.txt no permite %s", url)
            return None

        last_error: str | None = None
        for attempt in range(1, self.retries + 1):
            self.limiter.wait()
            try:
                self.stats["requests"] += 1
                resp = self.session.get(
                    url, timeout=self.timeout, allow_redirects=True, stream=stream
                )
            except requests.RequestException as exc:
                last_error = str(exc)
            else:
                if resp.status_code == 200:
                    return resp
                resp.close()
                if resp.status_code not in RETRYABLE_STATUS:
                    log.debug("GET %s -> HTTP %s", url, resp.status_code)
                    self.stats["errors"] += 1
                    return None
                last_error = f"HTTP {resp.status_code}"

            if attempt < self.retries:
                espera = min(30.0, (2 ** attempt) + random.uniform(0, 0.75))
                log.debug("reintento %s/%s de %s en %.1fs (%s)", attempt, self.retries, url, espera, last_error)
                time.sleep(espera)

        self.stats["errors"] += 1
        log.warning("se abandona %s (%s)", url, last_error)
        return None

    def get(self, url: str) -> Response | None:
        resp = self._request(url)
        if resp is None:
            return None
        if resp.encoding is None:
            resp.encoding = resp.apparent_encoding or "utf-8"
        return Response(
            url=str(resp.url),
            status=resp.status_code,
            text=resp.text,
            content_type=resp.headers.get("Content-Type", ""),
        )

    def get_xml(self, url: str) -> Response | None:
        """Como ``get``, descomprimiendo los sitemaps ``.xml.gz`` de IMDb."""
        resp = self._request(url, stream=True)
        if resp is None:
            return None
        with resp:
            crudo = resp.content
        if crudo[:2] == b"\x1f\x8b":
            try:
                crudo = gzip.decompress(crudo)
            except OSError as exc:
                log.warning("%s dice ser gzip pero no se puede abrir: %s", url, exc)
                return None
        return Response(
            url=str(resp.url),
            status=resp.status_code,
            text=crudo.decode("utf-8", errors="replace"),
            content_type=resp.headers.get("Content-Type", ""),
        )

    def stream_lines(self, url: str) -> Iterator[str]:
        """Recorre un ``.tsv.gz`` linea a linea sin dejarlo entero en memoria.

        ``title.basics.tsv.gz`` ocupa cientos de megas descomprimido: leerlo de
        golpe reventaria la memoria del runner.
        """
        resp = self._request(url, stream=True)
        if resp is None:
            return
        with resp:
            resp.raw.decode_content = True
            crudo: io.BufferedIOBase = resp.raw
            if url.endswith(".gz"):
                crudo = gzip.GzipFile(fileobj=resp.raw)
            with io.TextIOWrapper(crudo, encoding="utf-8", errors="replace") as texto:
                for linea in texto:
                    yield linea.rstrip("\n")

    def close(self) -> None:
        self.session.close()
