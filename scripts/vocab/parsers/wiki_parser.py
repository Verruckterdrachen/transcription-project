#!/usr/bin/env python3
"""
scripts/vocab/parsers/wiki_parser.py
Парсер Wikipedia (ru + en) для словарей ВОВ/ВМВ.

Стратегия:
  1. Wikipedia REST API (action=parse&prop=text) → чистый HTML
  2. Три режима извлечения: wikitable → ul/li → h2/h3
  3. Нормализация: убираем [[...]], сноски[1], скобки кроме латиницы
  4. Язык определяется автоматически из домена URL
  5. en.wikipedia: primary=кириллица из ячеек, secondary=латиница

FIX A: _extract_from_tables — сканирует cells[0..2], берёт первый валидный
FIX B: extract_terms — для en.wikipedia сначала ищет кириллицу,
        латиница сохраняется в отдельный файл _en.txt

Запуск:
  python scripts/vocab/parsers/wiki_parser.py \
      --url "https://ru.wikipedia.org/wiki/Список_Маршалов_Советского_Союза" \
      --category 1 \
      --output-dir data/parsed
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from urllib.parse import urlparse, unquote

from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from scripts.vocab.parsers.base_parser import BaseParser
from scripts.vocab.utils import (
    fetch_with_retry,
    get_default_rate_limiter,
    make_session,
    setup_logger,
)

logger = setup_logger("parser.wiki")

# ─────────────────────────────────────────────
# КОНСТАНТЫ
# ─────────────────────────────────────────────

WIKI_API = "https://{lang}.wikipedia.org/w/api.php"

WIKI_API_PARAMS = {
    "action": "parse",
    "prop": "text",
    "disablelimitreport": "1",
    "disableeditsection": "1",
    "disabletoc": "1",
    "format": "json",
}

MIN_TERM_LEN = 3
MAX_TERM_LEN = 80

_RE_WIKI_LINK   = re.compile(r"\[\[.*?\]\]")
_RE_FOOTNOTE    = re.compile(r"\[\d+\]")
_RE_PARENS_RU   = re.compile(r"\([^A-Za-z()]*?\)")
_RE_PARENS_KEEP = re.compile(r"\([A-Za-z][^()]*?\)")
_RE_DIGITS_ONLY = re.compile(r"^\d[\d\s\-–—.,]*$")
_RE_SPACES      = re.compile(r"\s{2,}")
_RE_HTML_ENTITY = re.compile(r"&[a-zA-Z]+;|&#\d+;")
_RE_CYRILLIC    = re.compile(r"[А-ЯЁа-яё]{2,}")  # FIX B: детектор кириллицы

_NOISE_TAGS = ["sup", "span.reference", "span.mw-editsection"]

# Максимум столбцов таблицы для сканирования (FIX A)
_MAX_COL_SCAN = 3

# ─────────────────────────────────────────────
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ─────────────────────────────────────────────

def _get_lang(url: str) -> str:
    host = urlparse(url).netloc.lower()
    return host.split(".")[0]


def _get_page_title(url: str) -> str:
    path = urlparse(url).path
    title = path.split("/wiki/", 1)[-1]
    return unquote(title)


def _remove_noise(tag: BeautifulSoup) -> None:
    for selector in _NOISE_TAGS:
        for el in tag.select(selector):
            el.decompose()

def _clean_term(raw: str) -> str | None:
    t = raw.strip()
    t = _RE_HTML_ENTITY.sub(" ", t)
    t = _RE_WIKI_LINK.sub("", t)
    t = _RE_FOOTNOTE.sub("", t)

    latin_brackets: list[str] = []

    def _stash_latin(m: re.Match) -> str:
        latin_brackets.append(m.group(0))
        return f"\x00LAT{len(latin_brackets) - 1}\x00"

    t = _RE_PARENS_KEEP.sub(_stash_latin, t)
    t = _RE_PARENS_RU.sub("", t)

    for i, bracket in enumerate(latin_brackets):
        t = t.replace(f"\x00LAT{i}\x00", bracket)

    t = t.replace("—", " ").replace("–", " ").replace("«", "").replace("»", "")
    t = _RE_SPACES.sub(" ", t).strip().strip(".,;:—–")

    if not t:
        return None
    if len(t) < MIN_TERM_LEN or len(t) > MAX_TERM_LEN:
        return None
    if _RE_DIGITS_ONLY.match(t):
        return None
    if not re.search(r"[А-ЯA-Za-zёЁ]", t):
        return None

    # БАГ 1 FIX: нормализуем КАПСЛОК
    t = _normalize_caps(t)

    return t

def _normalize_caps(text: str) -> str:
    """
    Нормализует КАПСЛОК в именах.
    'ВОРОШИЛОВ КЛИМЕНТ' → 'Ворошилов Климент'

    Правила:
    - Слово целиком в верхнем регистре И только буквы И длина > 4 → capitalize()
    - Аббревиатуры ≤ 4 символов (ГДР, СССР, ЧССР, НКВД) — не трогаем
    - Смешанный регистр (СБД-2, Т-34) — не трогаем
    """
    words = text.split()
    result = []
    for w in words:
        if w.isupper() and w.isalpha() and len(w) > 4:
            result.append(w.capitalize())
        else:
            result.append(w)
    return " ".join(result)

def _dedupe_ordered(terms: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for t in terms:
        key = t.lower()
        if key not in seen:
            seen.add(key)
            result.append(t)
    return result


def _is_cyrillic_term(term: str) -> bool:
    """Возвращает True если термин содержит кириллицу."""
    return bool(_RE_CYRILLIC.search(term))

_RE_HAS_DIGIT  = re.compile(r"\d")
_RE_ROMAN_NUM  = re.compile(r"\b(I{1,3}|IV|VI{0,3}|IX|X{1,3}XI{0,2}|XII)\b")
_RE_ALL_LATIN = re.compile(r"^[A-Za-z\d\s\-\.\/]+$")


# Служебные слова en.wikipedia — не техника
_LATIN_STOPWORDS = {
    "timeline", "bibliography", "contents", "references", "notes",
    "see also", "further reading", "external links", "gallery",
    "sources", "footnotes", "appendix", "index", "overview",
}

# Строки состоящие только из цифр, пробелов, "and" — это годы/диапазоны
_RE_YEARS_RANGE = re.compile(r"^[\d\s\-–andto]+$", re.IGNORECASE)


def _is_useful_latin(term: str) -> bool:
    """
    Латинский термин полезен ТОЛЬКО если это обозначение техники/аббревиатура:
      ✅ содержит цифры + буквы → Panzer-IV, Bf-109, Ju-87 (не просто год)
      ✅ содержит римские числа → Tiger I, Panzer III
      ✅ одно слово ≤ 20 chr, не служебное → StuG, Wehrmacht, Waffen-SS

    ❌ служебные слова → Timeline, Bibliography
    ❌ строки из цифр/годов → 1935 1940 and 1943, 1941-1945
    ❌ 2+ слова без цифр/римских → Georgy Zhukov
    """
    if not _RE_ALL_LATIN.match(term):
        return False

    # БАГ 2 FIX (a): исключаем служебные слова
    if term.lower().strip() in _LATIN_STOPWORDS:
        return False

    # БАГ 2 FIX (b): исключаем строки из цифр/годов без букв-индексов
    if _RE_YEARS_RANGE.match(term):
        return False

    # Цифры + буквы → техника (Panzer-IV, Bf-109)
    if _RE_HAS_DIGIT.search(term) and re.search(r"[A-Za-z]", term):
        return True

    # Римские числа → Tiger I, Panzer III
    if _RE_ROMAN_NUM.search(term):
        return True

    # Одиночное слово, не служебное
    words = term.split()
    if len(words) == 1 and len(term) <= 20:
        return True

    return False

# ─────────────────────────────────────────────
# СТРАТЕГИИ ИЗВЛЕЧЕНИЯ
# ─────────────────────────────────────────────

def _extract_from_tables(soup: BeautifulSoup) -> list[str]:
    """
    Извлекает термины из wikitable.

    FIX A: Сканирует cells[0], [1], [2] — берёт первый валидный термин
    в строке. Решает проблему нумерованных таблиц где имя в cells[1].
    """
    terms: list[str] = []
    for table in soup.select("table.wikitable"):
        for row in table.select("tr"):
            cells = row.select("td")
            if not cells:
                continue
            # FIX A: сканируем первые _MAX_COL_SCAN ячеек, берём первый валидный
            for idx in range(min(_MAX_COL_SCAN, len(cells))):
                cell = cells[idx]
                _remove_noise(cell)
                raw = cell.get_text(" ", strip=True)
                term = _clean_term(raw)
                if term:
                    terms.append(term)
                    break  # нашли валидный термин в этой строке — переходим к следующей
    return terms


def _extract_from_lists(soup: BeautifulSoup) -> list[str]:
    terms: list[str] = []
    for noise in soup.select(".toc, .navbox, .mw-jump-link, nav"):
        noise.decompose()

    for li in soup.select("ul > li"):
        _remove_noise(li)
        raw = li.get_text(" ", strip=True)
        for sep in (" — ", " - ", " – "):
            if sep in raw:
                raw = raw.split(sep)[0]
                break
        term = _clean_term(raw)
        if term:
            terms.append(term)
    return terms


def _extract_from_headings(soup: BeautifulSoup) -> list[str]:
    terms: list[str] = []
    SKIP_HEADINGS = {
        "содержание", "примечания", "ссылки", "литература",
        "источники", "см. также", "references", "notes",
        "external links", "further reading", "contents",
    }
    for tag in soup.select("h2, h3"):
        _remove_noise(tag)
        raw = tag.get_text(" ", strip=True)
        if raw.lower() in SKIP_HEADINGS:
            continue
        term = _clean_term(raw)
        if term:
            terms.append(term)
    return terms


# ─────────────────────────────────────────────
# FIX БАГ 2: _extract_cyrillic_from_cells — только кириллица в скобках
# ─────────────────────────────────────────────

# Паттерн: (Кириллический текст) — именно так en.wikipedia пишет оригинальные имена:
# "Georgy Zhukov (Георгий Жуков)" → захватываем "Георгий Жуков"
_RE_CYRILLIC_IN_PARENS = re.compile(
    r"\(\s*([А-ЯЁа-яё][А-ЯЁа-яё\s\-\.]{3,})\s*\)"
)


def _extract_cyrillic_from_cells(soup: BeautifulSoup) -> list[str]:
    """
    FIX БАГ 2: ищет кириллику ТОЛЬКО внутри скобок в ячейках таблиц и li.
    Паттерн: 'Georgy Zhukov (Георгий Жуков)' → 'Георгий Жуков'
    Одиночные кириллические слова вне скобок (Выстрел, etc.) — игнорируются.
    """
    terms: list[str] = []

    # Ячейки таблиц
    for table in soup.select("table.wikitable"):
        for row in table.select("tr"):
            cells = row.select("td")
            for cell in cells[:_MAX_COL_SCAN]:
                _remove_noise(cell)
                raw = cell.get_text(" ", strip=True)
                for m in _RE_CYRILLIC_IN_PARENS.finditer(raw):
                    term = _clean_term(m.group(1))
                    if term and len(term) >= 4:
                        terms.append(term)

    # li элементы
    for li in soup.select("ul > li"):
        _remove_noise(li)
        raw = li.get_text(" ", strip=True)
        for m in _RE_CYRILLIC_IN_PARENS.finditer(raw):
            term = _clean_term(m.group(1))
            if term and len(term) >= 4:
                terms.append(term)

    return terms
		
# ─────────────────────────────────────────────
# WIKI PARSER
# ─────────────────────────────────────────────

class WikiParser(BaseParser):
    """
    Парсер Wikipedia (ru + en).

    ru.wikipedia: стандартная стратегия table → list → heading
    en.wikipedia: FIX B — сначала ищет кириллицу в ячейках (primary),
                  затем латиницу (secondary, сохраняется в _en.txt)
    """

    def fetch(self) -> str:
        lang = _get_lang(self.url)
        title = _get_page_title(self.url)
        api_url = WIKI_API.format(lang=lang)
        params = {**WIKI_API_PARAMS, "page": title}

        self.logger.info(f"Wikipedia API → lang={lang}, title={title!r}")

        from scripts.vocab.utils import get_cached, save_cache
        cached = get_cached(self.url)
        if cached is not None:
            self.logger.info(f"fetch → cache hit ({len(cached):,} символов)")
            return cached

        self.rate_limiter.wait(self.domain)
        resp = self.session.get(api_url, params=params, timeout=self.timeout)
        resp.raise_for_status()
        data = resp.json()

        if "error" in data:
            raise ValueError(
                f"Wikipedia API error: {data['error'].get('info', data['error'])}"
            )
        if "parse" not in data:
            raise ValueError(f"Wikipedia API: неожиданный ответ для {title!r}")

        html = data["parse"]["text"]["*"]
        self.logger.info(f"fetch OK — {len(html):,} символов")
        save_cache(self.url, html)
        return html

    def extract_terms(self, html: str) -> list[str]:
        """
        ru.wikipedia: table → list → heading, возвращает кириллицу.

        en.wikipedia:
          Primary   → кириллица из ячеек (имена в скобках)
          Secondary → латиница ТОЛЬКО если это техника/аббревиатура
                      (цифры, римские числа, одиночное слово)
          Discard   → транслитерированные русские имена (Georgy Zhukov и т.п.)
        """
        soup = BeautifulSoup(html, "html.parser")
        lang = _get_lang(self.url)

        table_terms   = _extract_from_tables(soup)
        list_terms    = _extract_from_lists(soup)
        heading_terms = _extract_from_headings(soup)

        self.logger.info(
            f"extract [{lang}]: tables={len(table_terms)}, "
            f"lists={len(list_terms)}, headings={len(heading_terms)}"
        )

        if lang == "en":
            # Primary: кириллица из ячеек (имена через скобки)
            cyrillic_terms = _dedupe_ordered(
                [t for t in _extract_cyrillic_from_cells(soup)
                 if _is_cyrillic_term(t)]
            )

            # Secondary: латиница ТОЛЬКО для техники/аббревиатур
            useful_latin = _dedupe_ordered(
                [t for t in (table_terms + list_terms + heading_terms)
                 if not _is_cyrillic_term(t) and _is_useful_latin(t)]
            )

            # Отброшенные транслитерации (только для лога)
            discarded = [
                t for t in (table_terms + list_terms + heading_terms)
                if not _is_cyrillic_term(t) and not _is_useful_latin(t)
            ]

            self.logger.info(
                f"extract [en]: cyrillic={len(cyrillic_terms)}, "
                f"useful_latin={len(useful_latin)}, "
                f"discarded_transliterations={len(discarded)}"
            )

            if cyrillic_terms:
                self.logger.info(
                    f"✅ Primary: кириллица ({len(cyrillic_terms)} терминов)"
                )
            else:
                self.logger.warning(
                    "⚠️ Кириллица не найдена — только техника/аббревиатуры"
                )

            if useful_latin:
                self._save_latin(useful_latin)

            # Возвращаем кириллицу + полезную латиницу (техника)
            result = _dedupe_ordered(cyrillic_terms + useful_latin)

        else:
            combined = table_terms + list_terms + heading_terms
            result = _dedupe_ordered(combined)

        self.logger.info(f"extract total (after dedup): {len(result)}")
        return result

    def _save_latin(self, terms: list[str]) -> None:
        """Сохраняет латинские термины в отдельный файл {domain}_en.txt."""
        out_dir = self.output_dir / self.category
        out_dir.mkdir(parents=True, exist_ok=True)
        safe_domain = self.domain.replace(".", "_").replace("/", "_")
        out_path = out_dir / f"{safe_domain}_en.txt"
        with open(out_path, "w", encoding="utf-8") as f:
            for term in terms:
                f.write(term.strip() + "\n")
        self.logger.info(f"save latin → {out_path} ({len(terms)} терминов)")


# ─────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="WikiParser — парсинг одной Wikipedia-страницы"
    )
    parser.add_argument("--url", required=True)
    parser.add_argument("--category", required=True)
    parser.add_argument("--output-dir", default="data/parsed")
    parser.add_argument("--no-cache", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    parser = WikiParser(
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
