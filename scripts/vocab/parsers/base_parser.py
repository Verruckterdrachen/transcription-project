#!/usr/bin/env python3
"""
scripts/vocab/parsers/base_parser.py
Абстрактный базовый класс для всех парсеров словарей ВОВ/ВМВ.

Паттерн: Template Method
  run() = fetch() → extract_terms() → save() → return terms

Каждый конкретный парсер:
  - наследует BaseParser
  - реализует extract_terms(html: str) -> list[str]
  - при необходимости переопределяет fetch()
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from pathlib import Path

import requests

from scripts.vocab.utils import (
    DomainRateLimiter,
    fetch_with_retry,
    get_cached,
    get_default_rate_limiter,
    get_domain,
    make_session,
    setup_logger,
)


class BaseParser(ABC):
    """
    Абстрактный базовый парсер.

    Параметры:
        url          : URL для парсинга
        category     : строковый id категории (например '1', '3Б')
        output_dir   : корневая директория для сохранения .txt
                       (по умолчанию 'data/parsed')
        rate_limiter : shared DomainRateLimiter (если None — используется singleton)
        timeout      : таймаут HTTP-запроса в секундах
        use_cache    : использовать дисковый кэш (TTL 7 дней)
    """

    def __init__(
        self,
        url: str,
        category: str,
        output_dir: str = "data/parsed",
        rate_limiter: DomainRateLimiter | None = None,
        timeout: int = 15,
        use_cache: bool = True,
    ) -> None:
        self.url = url
        self.category = category
        self.output_dir = Path(output_dir)
        self.rate_limiter = rate_limiter or get_default_rate_limiter()
        self.timeout = timeout
        self.use_cache = use_cache

        self.domain = get_domain(url)
        self.session: requests.Session = make_session()
        self.logger: logging.Logger = setup_logger(
            f"parser.{self.__class__.__name__}.{self.domain}"
        )

    # ─────────────────────────────────────────
    # FETCH  (конкретный, переопределяемый)
    # ─────────────────────────────────────────

    def fetch(self) -> str:
        """
        Загружает URL и возвращает HTML (str).
        Переопределяется в api_parser.py и pdf_parser.py,
        где механизм получения данных принципиально другой.
        """
        self.logger.info(f"fetch → {self.url}")
        html = fetch_with_retry(
            url=self.url,
            session=self.session,
            rate_limiter=self.rate_limiter,
            timeout=self.timeout,
            use_cache=self.use_cache,
        )
        self.logger.info(f"fetch OK — {len(html):,} символов")
        return html

    # ─────────────────────────────────────────
    # EXTRACT_TERMS  (абстрактный)
    # ─────────────────────────────────────────

    @abstractmethod
    def extract_terms(self, html: str) -> list[str]:
        """
        Извлекает список терминов из HTML/текста.
        Реализуется в каждом конкретном парсере.
        Должен возвращать list[str], по одному термину.
        """
        ...

    # ─────────────────────────────────────────
    # SAVE  (конкретный)
    # ─────────────────────────────────────────

    def save(self, terms: list[str]) -> Path:
        """
        Сохраняет термины в:
          {output_dir}/{category}/{domain}.txt
        Один термин — одна строка. Файл перезаписывается.
        Возвращает Path к сохранённому файлу.
        """
        out_dir = self.output_dir / self.category
        out_dir.mkdir(parents=True, exist_ok=True)

        # Имя файла: домен с заменой точек на подчёркивания
        safe_domain = self.domain.replace(".", "_").replace("/", "_")
        out_path = out_dir / f"{safe_domain}.txt"

        with open(out_path, "w", encoding="utf-8") as f:
            for term in terms:
                f.write(term.strip() + "\n")

        self.logger.info(
            f"save → {out_path} ({len(terms)} терминов)"
        )
        return out_path

    # ─────────────────────────────────────────
    # RUN  (Template Method — не переопределять)
    # ─────────────────────────────────────────

    def run(self) -> list[str]:
        """
        Полный цикл: fetch → extract_terms → save.
        Ошибки логируются, не роняют оркестратор.
        Возвращает список извлечённых терминов (пустой при ошибке).
        """
        self.logger.info(
            f"[START] {self.__class__.__name__} | cat={self.category} | {self.url}"
        )
        try:
            html = self.fetch()
            terms = self.extract_terms(html)

            if not terms:
                self.logger.warning(f"extract_terms вернул 0 терминов: {self.url}")
                return []

            out_path = self.save(terms)
            self.logger.info(
                f"[DONE ] {self.__class__.__name__} | "
                f"{len(terms)} терминов → {out_path}"
            )
            return terms

        except Exception as exc:
            self.logger.error(
                f"[FAIL ] {self.__class__.__name__} | {self.url} | {exc}",
                exc_info=True,
            )
            return []

    # ─────────────────────────────────────────
    # __repr__
    # ─────────────────────────────────────────

    def __repr__(self) -> str:
        return (
            f"{self.__class__.__name__}("
            f"url={self.url!r}, category={self.category!r})"
        )
