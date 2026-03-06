#!/usr/bin/env python3
"""
scripts/vocab/parsers/rkka_parser.py
Парсер rkka.ru для словарей ВОВ.

Стратегия (двухуровневый crawler):
  Level 0 — directory page (oper.htm, hist/f.htm итд):
    - Текст ссылок → названия операций/формирований
    - Заголовки разделов из <td> без href
    → ~50-80 терминов

  Level 1 — страницы операций/статей (max MAX_PAGES):
    3 паттерна (структурированный + нарративный текст):
    1. _extract_from_tables(): scan <td> cells
    2. _extract_rank_names():  звание + ФИО (импорт из militera_parser)
    3. _extract_unit_names():  формирования (импорт из militera_parser)
    → ~20-50 терминов/страница

Итого: ~500-1000 терминов/директория

Кодировка: windows-1251 (явно, не autodetect)
SSL: verify=False
Rate limit: 2 сек/запрос

Запуск:
  python scripts/vocab/parsers/rkka_parser.py \\
      --url "http://rkka.ru/oper.htm" \\
      --category 5 \\
      --output-dir data/parsed
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from scripts.vocab.parsers.base_parser import BaseParser
from scripts.vocab.parsers.wiki_parser import (
    _clean_term,
    _dedupe_ordered,
    _normalize_caps,
)
from scripts.vocab.parsers.militera_parser import (
    _extract_rank_names,
    _extract_unit_names,
		_extract_quoted_terms,
    _normalize_case,
    _is_stopword_term,
)
from scripts.vocab.utils import (
    fetch_with_retry,
    get_cached,
    get_default_rate_limiter,
    make_session,
    save_cache,
    setup_logger,
)

logger = setup_logger("parser.rkka")

# ─────────────────────────────────────────────
# КОНСТАНТЫ
# ─────────────────────────────────────────────

ENCODING = "windows-1251"
MAX_PAGES = 60
MIN_TERM_LEN = 3
MAX_TERM_LEN = 80

# Стоп-слова для текста ссылок Level 0
_LINK_STOPWORDS = {
    "В", "На", "За", "По", "Об", "О", "К", "С", "Из", "От",
    "Для", "При", "Над", "Под", "Без", "Или", "И",
}

# ─────────────────────────────────────────────
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ─────────────────────────────────────────────

def _is_content_link(href: str, base_domain: str) -> bool:
    """
    Фильтр ссылок Level 1.
    Принимаем: относительные rkka-ссылки на .htm/.html
    Отклоняем: якоря, внешние домены, CSS/JS, пустые
    """
    if not href:
        return False
    if href.startswith("#"):
        return False
    if href.startswith("mailto"):
        return False
    if href.startswith("http") and base_domain not in href:
        return False
    if re.search(r"\.(css|js|jpg|png|gif|pdf)$", href, re.IGNORECASE):
        return False
    if re.search(r"\.html?$", href, re.IGNORECASE):
        return True
    return False


def _clean_link_text(raw: str) -> str | None:
    text = re.sub(r"\s+", " ", raw).strip()
    if len(text) < 4:
        return None
    first_word = text.split()[0]
    if first_word in _LINK_STOPWORDS:
        return None
    # ← ДОБАВИТЬ: только тексты с кириллицей
    if not re.search(r"[а-яёА-ЯЁ]", text):
        return None
    term = _clean_term(text)
    if not term or len(term) < MIN_TERM_LEN:
        return None
    return term


def _extract_table_cells(soup: BeautifulSoup) -> list[str]:
    """
    Извлекает термины из <td> ячеек.
    Используется и на Level 0 (заголовки разделов),
    и на Level 1 (таблицы командиров, формирований).
    """
    terms: list[str] = []
    for td in soup.find_all("td"):
        # Пропускаем ячейки со ссылками — они обработаны отдельно
        if td.find("a"):
            continue
        raw = td.get_text(" ", strip=True)
        raw = re.sub(r"\s+", " ", raw).strip()
        if len(raw) < MIN_TERM_LEN or len(raw) > MAX_TERM_LEN:
            continue
        # Только строки с кириллицей
        if not re.search(r"[а-яёА-ЯЁ]", raw):
            continue
        term = _clean_term(_normalize_caps(raw))
        if term and not _is_stopword_term(term):
            terms.append(term)
    return terms


def _extract_level0_link_texts(soup: BeautifulSoup) -> list[str]:
    """Названия операций/статей из текста ссылок Level 0."""
    terms: list[str] = []
    for a in soup.find_all("a", href=True):
        raw = a.get_text(" ", strip=True)
        term = _clean_link_text(raw)
        if term:
            terms.append(term)
    return terms

def _extract_page_terms(soup: BeautifulSoup) -> list[str]:
    for tag in soup.select("nav, .footnote, .note, script, style"):
        tag.decompose()
    terms: list[str] = []
    terms.extend(_extract_table_cells(soup))
    text = soup.get_text(" ", strip=True)
    terms.extend(_extract_rank_names(text))
    terms.extend(_extract_unit_names(text))
    terms.extend(_extract_quoted_terms(text))   # ← ДОБАВИТЬ
    return terms

# ─────────────────────────────────────────────
# RKKA PARSER
# ─────────────────────────────────────────────

class RkkaParser(BaseParser):
    """
    Парсер rkka.ru.
    Двухуровневый crawler: Level 0 (directory) + Level 1 (страницы).
    Кодировка: windows-1251 (явно).
    Rate limit: 2 сек/запрос.
    """

    ENCODING = "windows-1251"

    def _fetch_html(self, url: str) -> str | None:
        """Фетч с cp1251 декодированием и кэшированием."""
        cached = get_cached(url)
        if cached is not None:
            return cached
        try:
            self.rate_limiter.wait(self.domain)
            # fetch_with_retry возвращает bytes или str — обрабатываем оба случая
            raw = fetch_with_retry(
                url=url,
                session=self.session,
                rate_limiter=self.rate_limiter,
                timeout=self.timeout,
                use_cache=False,
            )
            # Если вернулись bytes — декодируем явно
            if isinstance(raw, bytes):
                html = raw.decode(self.ENCODING, errors="replace")
            else:
                html = raw
            save_cache(url, html)
            return html
        except Exception as exc:
            self.logger.warning(f"Не удалось скачать {url}: {exc}")
            return None

    def fetch(self) -> str:
        self.logger.info(f"fetch Level 0 → {self.url}")
        html = self._fetch_html(self.url)
        if html is None:
            raise RuntimeError(f"Не удалось скачать {self.url}")
        self.logger.info(f"fetch Level 0 OK — {len(html):,} символов")
        return html

    def _get_page_urls(self, soup: BeautifulSoup) -> list[str]:
        """Собирает уникальные ссылки Level 1 с directory-страницы."""
        base_domain = urlparse(self.url).netloc
        urls: list[str] = []
        seen: set[str] = set()
        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            if not _is_content_link(href, base_domain):
                continue
            abs_url = urljoin(self.url, href)
            if abs_url in seen:
                continue
            seen.add(abs_url)
            urls.append(abs_url)
            if len(urls) >= MAX_PAGES:
                break
        self.logger.info(
            f"Найдено {len(urls)} уникальных страниц (max {MAX_PAGES})"
        )
        return urls

    def extract_terms(self, html: str) -> list[str]:
        soup = BeautifulSoup(html, "html.parser")
        all_terms: list[str] = []

        # ── Level 0 ──────────────────────────────
        link_texts = _extract_level0_link_texts(soup)
        section_headers = _extract_table_cells(soup)
        level0_terms = _dedupe_ordered(link_texts + section_headers)
        self.logger.info(
            f"Level 0: ссылки={len(link_texts)}, заголовки={len(section_headers)}"
            f" → {len(level0_terms)} уникальных"
        )
        all_terms.extend(level0_terms)

        # ── Level 1 ──────────────────────────────
        page_urls = self._get_page_urls(soup)
        for i, page_url in enumerate(page_urls, start=1):
            self.logger.info(f"Level 1 [{i}/{len(page_urls)}] → {page_url}")
            page_html = self._fetch_html(page_url)
            if not page_html:
                continue
            page_soup = BeautifulSoup(page_html, "html.parser")
            page_terms = _dedupe_ordered(_extract_page_terms(page_soup))
            self.logger.info(f"  → {len(page_terms)} терминов")
            all_terms.extend(page_terms)

        result = _dedupe_ordered(all_terms)
        self.logger.info(f"extract total (after dedup): {len(result)} терминов")
        return result


# ─────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="RkkaParser — парсинг директорий rkka.ru"
    )
    parser.add_argument("--url", required=True, help="URL directory-страницы")
    parser.add_argument("--category", required=True, help="ID категории (1–16)")
    parser.add_argument("--output-dir", default="data/parsed")
    parser.add_argument("--no-cache", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    parser = RkkaParser(
        url=args.url,
        category=args.category,
        output_dir=args.output_dir,
        use_cache=not args.no_cache,
    )
    terms = parser.run()
    print(f"\n✅ Извлечено терминов: {len(terms)}")
    if terms:
        print("  Первые 15:")
        for t in terms[:15]:
            print(f"    {t}")


if __name__ == "__main__":
    main()
