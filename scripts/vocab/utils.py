#!/usr/bin/env python3
"""
scripts/vocab/utils.py
Общие утилиты для всех парсеров словарей ВОВ/ВМВ:
  - логирование (file + console)
  - per-domain rate limiting
  - requests.Session с реалистичным UA
  - кэш HTML на диске (TTL 7 дней)
  - единая точка HTTP-запроса с retry
  - вспомогательные функции URL
"""

from __future__ import annotations

import hashlib
import logging
import time
from pathlib import Path
from threading import Lock
from urllib.parse import urlparse

import requests
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

# ─────────────────────────────────────────────
# КОНСТАНТЫ
# ─────────────────────────────────────────────

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36"
)

LOG_FILE = "vocab_parser.log"
CACHE_DIR = Path("data/cache")
CACHE_TTL_DAYS = 7
DEFAULT_TIMEOUT = 15  # секунд

# ─────────────────────────────────────────────
# ЛОГИРОВАНИЕ
# ─────────────────────────────────────────────

def setup_logger(name: str) -> logging.Logger:
    """
    Возвращает именованный logger с двумя хэндлерами:
    файл vocab_parser.log + консоль.
    Повторный вызов с тем же name не дублирует хэндлеры.
    """
    logger = logging.getLogger(name)
    if logger.handlers:
        return logger  # уже настроен — не добавляем хэндлеры повторно

    logger.setLevel(logging.INFO)
    fmt = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s — %(message)s", "%H:%M:%S"
    )

    fh = logging.FileHandler(LOG_FILE, encoding="utf-8")
    fh.setFormatter(fmt)
    logger.addHandler(fh)

    ch = logging.StreamHandler()
    ch.setFormatter(fmt)
    logger.addHandler(ch)

    return logger


# ─────────────────────────────────────────────
# PER-DOMAIN RATE LIMITER
# ─────────────────────────────────────────────

class DomainRateLimiter:
    """
    Thread-safe per-domain rate limiter.
    min_interval_map позволяет задать разный интервал для разных доменов:
      {"pamyat-naroda.ru": 2.0, "podvignaroda.ru": 2.0}  →  0.5 req/sec
    Все прочие домены — default_interval (1.0 сек = 1 req/sec).
    """

    def __init__(
        self,
        default_interval: float = 1.0,
        min_interval_map: dict[str, float] | None = None,
    ) -> None:
        self._last_call: dict[str, float] = {}
        self._lock = Lock()
        self._default = default_interval
        self._map: dict[str, float] = min_interval_map or {}

    def wait(self, domain: str) -> None:
        interval = self._map.get(domain, self._default)
        with self._lock:
            now = time.monotonic()
            last = self._last_call.get(domain, 0.0)
            delta = now - last
            if delta < interval:
                time.sleep(interval - delta)
            self._last_call[domain] = time.monotonic()


# Shared singleton для всех парсеров
_DEFAULT_RATE_LIMITER = DomainRateLimiter(
    default_interval=1.0,
    min_interval_map={
        "pamyat-naroda.ru": 2.0,   # 0.5 req/sec — строгий лимит API
        "podvignaroda.ru": 2.0,
    },
)


def get_default_rate_limiter() -> DomainRateLimiter:
    """Возвращает shared DomainRateLimiter для использования в парсерах."""
    return _DEFAULT_RATE_LIMITER


# ─────────────────────────────────────────────
# REQUESTS SESSION
# ─────────────────────────────────────────────

def make_session() -> requests.Session:
    """
    Создаёт requests.Session с реалистичными заголовками.
    Каждый парсер создаёт одну сессию на экземпляр.
    """
    session = requests.Session()
    session.headers.update(
        {
            "User-Agent": USER_AGENT,
            "Accept": (
                "text/html,application/xhtml+xml,application/xml;"
                "q=0.9,image/webp,*/*;q=0.8"
            ),
            "Accept-Language": "ru-RU,ru;q=0.9,en-US;q=0.8,en;q=0.7",
            "Accept-Encoding": "gzip, deflate, br",
            "Connection": "keep-alive",
        }
    )
    return session


# ─────────────────────────────────────────────
# КЭШИРОВАНИЕ
# ─────────────────────────────────────────────

def _cache_path(url: str) -> Path:
    """data/cache/{domain}/{md5(url)}.html"""
    domain = get_domain(url)
    url_hash = hashlib.md5(url.encode("utf-8")).hexdigest()
    return CACHE_DIR / domain / f"{url_hash}.html"


def get_cached(url: str) -> str | None:
    """
    Возвращает HTML из кэша, если файл существует и моложе CACHE_TTL_DAYS.
    Иначе возвращает None.
    """
    path = _cache_path(url)
    if not path.exists():
        return None
    age_days = (time.time() - path.stat().st_mtime) / 86400
    if age_days > CACHE_TTL_DAYS:
        return None
    return path.read_text(encoding="utf-8", errors="replace")


def save_cache(url: str, html: str) -> None:
    """Сохраняет HTML в кэш."""
    path = _cache_path(url)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(html, encoding="utf-8")


# ─────────────────────────────────────────────
# FETCH С RETRY И КЭШЕМ
# ─────────────────────────────────────────────

def fetch_with_retry(
    url: str,
    session: requests.Session | None = None,
    rate_limiter: DomainRateLimiter | None = None,
    timeout: int = DEFAULT_TIMEOUT,
    use_cache: bool = True,
) -> str:
    """
    Главная точка входа для всех HTTP GET-запросов.

    Порядок:
      1. Проверить кэш (если use_cache=True)
      2. Rate limit для домена
      3. GET с retry (3 попытки, backoff 1→4→16с)
      4. Сохранить в кэш
      5. Вернуть HTML (str)

    Исключения пробрасываются наружу — парсер решает, как их обработать.
    """
    if use_cache:
        cached = get_cached(url)
        if cached is not None:
            return cached

    sess = session or make_session()
    rl = rate_limiter or _DEFAULT_RATE_LIMITER
    domain = get_domain(url)

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=16),
        retry=retry_if_exception_type(
            (requests.exceptions.Timeout, requests.exceptions.ConnectionError)
        ),
        reraise=True,
    )
    def _get() -> str:
        rl.wait(domain)
        resp = sess.get(url, timeout=timeout)
        resp.raise_for_status()
        resp.encoding = resp.apparent_encoding or "utf-8"
        return resp.text

    html = _get()
    if use_cache:
        save_cache(url, html)
    return html


# ─────────────────────────────────────────────
# URL-УТИЛИТЫ
# ─────────────────────────────────────────────

def get_domain(url: str) -> str:
    """
    Возвращает netloc без www.
    Пример: 'https://www.militera.lib.ru/...' → 'militera.lib.ru'
    """
    try:
        return urlparse(url).netloc.lower().lstrip("www.")
    except Exception:
        return ""


def normalize_url(url: str) -> str:
    """Убирает trailing slash и фрагмент (#...)."""
    parsed = urlparse(url)
    clean = parsed._replace(fragment="")
    result = clean.geturl().rstrip("/")
    return result
