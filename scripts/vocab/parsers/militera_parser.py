#!/usr/bin/env python3
"""
scripts/vocab/parsers/militera_parser.py
Парсер militera.lib.ru для словарей ВОВ/ВМВ.

Стратегия (двухуровневый crawler):
  Level 0 — index.html книги:
    - Автор из <title> / <h1>
    - TOC-ссылки: топонимы/операции из названий глав
    → ~20 терминов

  Level 1 — страницы глав (max MAX_CHAPTERS):
    4 паттерна без NER:
    1. _extract_rank_names():   (звание) + (инициалы + фамилия) | (фамилия)
    2. _extract_quoted_terms(): текст в «»
    3. _extract_unit_names():   формирования всех падежей + прилагательные
    4. _extract_cap_sequences(): 2-5 слов с заглавной (не начало предложения)
    → ~30-60 терминов/глава

Итого: ~500-600 терминов/книга

Запуск:
  python scripts/vocab/parsers/militera_parser.py \
      --url "http://militera.lib.ru/memo/russian/rokossovsky/index.html" \
      --category 1 \
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
from scripts.vocab.utils import (
    fetch_with_retry,
    get_cached,
    get_default_rate_limiter,
    make_session,
    save_cache,
    setup_logger,
)

logger = setup_logger("parser.militera")

# ─────────────────────────────────────────────
# КОНСТАНТЫ
# ─────────────────────────────────────────────

MAX_CHAPTERS = 15
MIN_TERM_LEN = 3
MAX_TERM_LEN = 80

# ─────────────────────────────────────────────
# ПАТТЕРН 1: ЗВАНИЯ + ФИО
#
# Militera использует ДВА формата:
#   А) звание + Фамилия Имя Отчество (полное ФИО)
#   Б) звание + И.И. Фамилия (инициалы перед фамилией) ← ОСНОВНОЙ на militera
#   В) звание + Фамилия (только фамилия)
# ─────────────────────────────────────────────

# Прилагательные-характеристики МЕЖДУ номером/именем и типом формирования:
# механизированный, танковый, гвардейский, стрелковый, кавалерийский,
# общевойсковой, моторизованный, воздушный, горно-стрелковый...
_UNIT_ADJ = (
    r"(?:[а-яёА-ЯЁ][а-яё]*"
    r"(?:"
    r"ский|ского|скому|ским|ском|ской|скую"
    r"|цкий|цкого|цкому|цким|цком|цкой|цкую"
    r"|ный|ного|ному|ным|ном|ной|ную|ные|ных|ными"
    r"|ованный|ованного|ованному|ованным|ованном|ованной|ованную|ованные"
    r"|овой|овому|овым|овом|овую|овые|овых|овыми"
    r"|овый|ового|овому|овым|овом"
    r"|евой|евого|евому|евым|евом|евую"
    r"|ый|ого|ому|ым|ом"
    r"|ий|его|ему|им|ем"
    r"|ая|ой|ую|ою"
    r"|яя|ей|юю"
    r")\s+){0,3}"
)

_RANKS_PATTERN = (
    r"(?:"
    # Советские/российские
    r"маршал(?:у|а|ом|е|ов)?\s+(?:Советского\s+Союза\s+)?"
    r"|генерал(?:-(?:майор|лейтенант|полковник|армии|фельдмаршал))?"
      r"(?:у|а|ом|е|ов|ами)?"
    r"|адмирал(?:у|а|ом|е|ов|флота)?"
    r"|вице-адмирал(?:у|а|ом|е)?"
    r"|контр-адмирал(?:у|а|ом|е)?"
    r"|полковник(?:у|а|ом|е|ов)?"
    r"|подполковник(?:у|а|ом|е|ов)?"
    r"|майор(?:у|а|ом|е|ов)?"
    r"|капитан(?:\s+(?:1|2|3)-го\s+ранга)?(?:у|а|ом|е|ов)?"
    r"|лейтенант(?:у|а|ом|е|ов)?"
    r"|старший\s+лейтенант(?:у|а|ом|е|ов)?"
    r"|мл(?:адший)?[\.\s]+лейтенант(?:у|а|ом|е|ов)?"
    r"|комбриг(?:у|а|ом|е|ов)?"
    r"|комдив(?:у|а|ом|е|ов)?"
    r"|комкор(?:у|а|ом|е|ов)?"
    r"|командарм(?:у|а|ом|е|ов)?"
    r"|командир(?:у|а|ом|е|ов)?\s+(?:корпуса|дивизии|бригады|полка|батальона)?"
    # Немецкие
    r"|фельдмаршал(?:у|а|ом|е|ов)?"
    r"|оберст(?:-лейтенант|-группенфюрер|-фельдфебель)?(?:у|а|ом|е|ов)?"
    r"|группенфюрер(?:у|а|ом|е|ов)?"
    r"|оберфюрер(?:у|а|ом|е|ов)?"
    r")"
)

# Формат А: Фамилия + [Имя [Отчество]]  (2-3 слова, всё с заглавной)
_RE_RANK_SURNAME_FIRST = re.compile(
    r"(?:маршал[а-я]*|генерал(?:-(?:майор|лейтенант|полковник|армии))?[а-я]*"
    r"|адмирал[а-я]*|полковник[а-я]*|подполковник[а-я]*|майор[а-я]*"
    r"|капитан[а-я]*|лейтенант[а-я]*|комбриг[а-я]*|комдив[а-я]*"
    r"|комкор[а-я]*|командарм[а-я]*|фельдмаршал[а-я]*)\s+"
    r"([А-ЯЁ][а-яё]{2,}(?:\s+[А-ЯЁ][а-яё]{2,}){0,2})",
    re.IGNORECASE | re.UNICODE,
)

# Формат Б: И.И. Фамилия  (инициалы перед фамилией) ← ОСНОВНОЙ на militera
_RE_RANK_INITIALS_FIRST = re.compile(
    r"(?:маршал[а-я]*|генерал(?:-(?:майор|лейтенант|полковник|армии))?[а-я]*"
    r"|адмирал[а-я]*|полковник[а-я]*|подполковник[а-я]*|майор[а-я]*"
    r"|капитан[а-я]*|лейтенант[а-я]*|комбриг[а-я]*|комдив[а-я]*"
    r"|комкор[а-я]*|командарм[а-я]*|фельдмаршал[а-я]*)\s+"
    r"([А-ЯЁ]\.\s*[А-ЯЁ]\.\s+[А-ЯЁ][а-яё]{2,})",
    re.IGNORECASE | re.UNICODE,
)

# Формат В: просто "И.И. Фамилия" без явного звания — ловим отдельно
# Рокоссовский пишет: "Г. К. Жукова", "М. А. Пуркаевым", "А.Г. Маслова"
_RE_INITIALS_SURNAME = re.compile(
    r"\b([А-ЯЁ]\.\s*[А-ЯЁ]\.\s+[А-ЯЁ][а-яё]{2,})\b",
    re.UNICODE,
)

# ─────────────────────────────────────────────
# ПАТТЕРН 2: ЦИТАТЫ В «»
# ─────────────────────────────────────────────

_RE_QUOTED = re.compile(r"«([^»]{3,60})»", re.UNICODE)

# ─────────────────────────────────────────────
# ПАТТЕРН 3: ВОИНСКИЕ ФОРМИРОВАНИЯ
#
# Покрываем:
#   - числовой префикс: 9-й, 35-я, 131-я, 5-м, 20-й
#   - прилагательное: Западный, Черноморский, Киевский Особый
#   - тип формирования во всех падежах
# ─────────────────────────────────────────────

# Числовые префиксы (все падежи числительных-прилагательных)
_NUM_PREFIX = (
    r"\d+[-‑–]?\s*"
    r"(?:й|я|е|го|му|м|ю|х|ми|ой|ей|им|ым|их|ых|ая|ое|ые|ого|ему|ем|ую|ою)?"
    r"\s+"
)

# Словесные числительные (все падежи)
_WORD_NUM = (
    r"(?:первый|первого|первому|первым|первом|первая|первой|первую|первою"
    r"|второй|второго|второму|вторым|втором|вторая|второй|вторую|второю"
    r"|третий|третьего|третьему|третьим|третьем|третья|третьей|третью"
    r"|четвёртый|четвёртого|четвёртому|четвёртым|четвёртом"
    r"|пятый|пятого|пятому|пятым|пятом|пятая|пятой|пятую"
    r"|шестой|шестого|шестому|шестым|шестом"
    r"|седьмой|седьмого|седьмому|седьмым|седьмом"
    r"|восьмой|восьмого|восьмому|восьмым|восьмом"
    r"|девятый|девятого|девятому|девятым|девятом"
    r"|десятый|десятого|десятому|десятым|десятом)\s+"
)

# Прилагательные-определители (все падежи)
# Западный, Черноморский, Северный, Киевский, Белорусский, Украинский...
_ADJ_PREFIX = (
    r"[А-ЯЁ][а-яё]+"
    r"(?:ский|ского|скому|ским|ском|ской|скую"
    r"|зный|зного|зному|зным|зном|зной|зную"
    r"|дный|дного|дному|дным|дном|дной|дную"
    r"|рный|рного|рному|рным|рном|рной|рную"
    r"|жный|жного|жному|жным|жном|жной|жную"
    r"|вный|вного|вному|вным|вном|вной|вную"
    r"|чный|чного|чному|чным|чном|чной|чную"
    r"|йный|йного|йному|йным|йном|йной|йную)"
    r"(?:\s+[А-ЯЁ][а-яё]+"           # второе прилагательное (Киевский Особый)
    r"(?:ый|ого|ому|ым|ом|ой|ую|ою|ые|ых|ыми))?"
    r"\s+"
)

# Типы формирований — все падежи
_UNIT_TYPES = (
    r"(?:"
    r"арми(?:я|и|ю|ей|е|й)\b"
    r"|фронт(?:а|у|ом|е|ов)?\b"
    r"|корпус(?:а|у|ом|е|ов|ами)?\b"
    r"|дивизи(?:я|и|ю|ей|е|й)\b"
    r"|бригад(?:а|ы|е|у|ой|ою|ам|ами|ах)?\b"
    r"|(?<!\w)полк(?:а|у|ом|е|ов|ами)?\b"
    r"|батальон(?:а|у|ом|е|ов|ами)?\b"
    r"|эскадрил(?:ья|ьи|ье|ью|ей)\b"
    r"|флот(?:а|у|ом|е|ов|ами)?\b"
    r"|флотили(?:я|и|ю|ей|е|й)\b"
    r"|округ(?:а|у|ом|е|ов|ами)?\b"
    r"|штаб(?:а|у|ом|е|ов|ами)?\b"
    r"|отряд(?:а|у|ом|е|ов|ами)?\b"
    r"|группировк(?:а|и|е|у|ой|ою|ам|ах)?\b"
    r"|соединени(?:е|я|ю|ем|и|й)\b"
    r")"
)

_RE_UNIT = re.compile(
    r"((?:" + _NUM_PREFIX + r"|" + _ADJ_PREFIX + r")?" + _UNIT_ADJ + _UNIT_TYPES + r")",
    re.IGNORECASE | re.UNICODE,
)

# ─────────────────────────────────────────────
# ПАТТЕРН 4: CAP-SEQUENCES
#
# Расширяем до 5 слов (Киевский Особый военный округ,
# Народный комиссар обороны, начальник Генерального штаба).
# Первое слово — заглавная, остальные — любые (строчные ок).
# Не в начале предложения (после [.!?] пробел).
# ─────────────────────────────────────────────

_RE_CAP_SEQ = re.compile(
    r"\b([А-ЯЁ][а-яё]{2,}(?:\s+[а-яёА-ЯЁ][а-яё]{2,}){1,4})\b",
    re.UNICODE,
)

# Стоп-слова для cap-sequences
_CAP_STOPWORDS = {
    # служебные заголовки
    "Глава", "Часть", "Раздел", "Примечания", "Приложение",
    "Источники", "Литература", "Содержание", "Оглавление",
    "Введение", "Заключение", "Предисловие", "Послесловие",
    "Аннотация", "Указатель", "Именной", "Географический",
    # предлоги/союзы с заглавной
    "В", "На", "По", "За", "Из", "От", "До", "Со",
    "Для", "При", "Про", "Над", "Под", "Без", "Это",
    # местоимения
    "Все", "Они", "Нас", "Вас", "Его", "Её", "Их", "Мы", "Он", "Она",
    # частые начала предложений (глаголы/существительные не-термины)
    "Наши", "Наша", "Наш", "Наше",
    "Однако", "Поэтому", "Таким", "Такой", "Такая", "Такое",
    "Когда", "Тогда", "Здесь", "Там", "Тут",
    "После", "Перед", "Между", "Через",
    "Войска", "Командование", "Противник", "Враг",
    "Армия",   # без числа — слишком общее
}

# ─────────────────────────────────────────────
# НОРМАЛИЗАЦИЯ ПАДЕЖЕЙ → ИМЕНИТЕЛЬНЫЙ
#
# Без морфологических библиотек — таблица суффиксов.
# Покрывает прилагательные и основные типы формирований.
# ─────────────────────────────────────────────

_CASE_NORM = [
    # Прилагательные м.р. косвенные → именительный
    (r"(?<=\w)ского\b",  "ский"),
    (r"(?<=\w)скому\b",  "ский"),
    (r"(?<=\w)ским\b",   "ский"),
    (r"(?<=\w)ском\b",   "ский"),
    (r"(?<=\w)ской\b",   "ская"),
    (r"(?<=\w)скую\b",   "ская"),
    (r"(?<=\w)ского\b",  "ское"),
    # Прилагательные на -ный
    (r"(?<=\w)ного\b",   "ный"),
    (r"(?<=\w)ному\b",   "ный"),
    (r"(?<=\w)ным\b",    "ный"),
    (r"(?<=\w)ном\b",    "ный"),
    (r"(?<=\w)ной\b",    "ная"),
    (r"(?<=\w)ную\b",    "ная"),
    # Существительные — формирования
    (r"\bарми(?:и|ю|ей|е|й)\b",      "армия"),
    (r"\bфронта?\b",                  "фронт"),
    (r"\bфронт(?:у|ом|е)\b",         "фронт"),
    (r"\bкорпус[ауоме]\b",           "корпус"),
    (r"\bдивизи(?:и|ю|ей|е|й)\b",   "дивизия"),
    (r"\bбригад[ыеуойою]\b",         "бригада"),
    (r"\bполк[ауоме]\b",             "полк"),
    (r"\bбатальон[ауоме]\b",         "батальон"),
    (r"\bфлот[ауоме]\b",             "флот"),
    (r"\bокруг[ауоме]\b",            "округ"),
    (r"\bштаб[ауоме]\b",             "штаб"),
    # Фамилии в косвенных падежах (упрощённо: -ого/-ому/-ым/-ом → убираем окончание)
    # Жукова → Жуков, Тимошенко — не склоняется
    (r"([А-ЯЁ][а-яё]{3,})ого\b",    r"\1"),
    (r"([А-ЯЁ][а-яё]{3,})ому\b",    r"\1"),
    (r"([А-ЯЁ][а-яё]{3,})ым\b",     r"\1"),
    (r"([А-ЯЁ][а-яё]{3,})ом\b",     r"\1"),
    (r"([А-ЯЁ][а-яё]{3,})ему\b",    r"\1"),
    (r"([А-ЯЁ][а-яё]{3,})ем\b",     r"\1"),
]

def _normalize_case(term: str) -> str:
    """Приводит термин из косвенного падежа к именительному (приблизительно)."""
    result = term
    for pattern, replacement in _CASE_NORM:
        result = re.sub(pattern, replacement, result, flags=re.IGNORECASE)
    return result.strip()


# ─────────────────────────────────────────────
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ─────────────────────────────────────────────

def _get_base_url(url: str) -> str:
    parsed = urlparse(url)
    return f"{parsed.scheme}://{parsed.netloc}"


def _is_chapter_link(href: str, base_domain: str) -> bool:
    if not href:
        return False
    if href.startswith("#"):
        return False
    if href.startswith("mailto"):
        return False
    if href.startswith("http") and base_domain not in href:
        return False
    name = href.rstrip("/").split("/")[-1]
    return bool(re.match(r"^(\d+|[a-z]\d*|chapter\d*)\.html?$", name, re.IGNORECASE))


def _extract_author_from_html(soup: BeautifulSoup) -> list[str]:
    """Автор книги из <title> или <h1>/<h2>."""
    terms: list[str] = []
    title_tag = soup.find("title")
    if title_tag:
        raw = title_tag.get_text(" ", strip=True)
        parts = re.split(r"\s+[-–—]\s+", raw, maxsplit=1)
        if parts:
            candidate = _clean_term(parts[0])
            if candidate and _looks_like_person(candidate):
                terms.append(candidate)
    for tag in soup.select("h1, h2")[:3]:
        raw = tag.get_text(" ", strip=True)
        parts = re.split(r"\s+[-–—]\s+", raw, maxsplit=1)
        if parts:
            candidate = _clean_term(parts[0])
            if candidate and _looks_like_person(candidate) and candidate not in terms:
                terms.append(candidate)
                break
    return terms


def _extract_toc_terms(soup: BeautifulSoup) -> list[str]:
    """Топонимы и названия операций из оглавления."""
    terms: list[str] = []
    toc_links = soup.select("ul a, ol a, .toc a, td a")
    for a in toc_links:
        raw = a.get_text(" ", strip=True)
        if len(raw) < 4:
            continue
        cleaned = re.sub(r"^(?:Глава|Часть|Раздел)?\s*\d+[\.\)]\s*", "", raw).strip()
        term = _clean_term(cleaned)
        if term and not _is_stopword_term(term):
            terms.append(term)
    return terms


def _extract_rank_names(text: str) -> list[str]:
    """
    Паттерн 1: звание + ФИО.
    Форматы А (Фамилия [Имя Отчество]), Б (И.И. Фамилия), В (И.И. Фамилия без звания).
    """
    terms: list[str] = []

    # Формат А: звание + Фамилия
    for m in _RE_RANK_SURNAME_FIRST.finditer(text):
        name = m.group(1).strip()
        term = _normalize_case(_clean_term(name) or "")
        if term and _looks_like_person(term):
            terms.append(term)

    # Формат Б: звание + И.И. Фамилия
    for m in _RE_RANK_INITIALS_FIRST.finditer(text):
        name = m.group(1).strip()
        # Нормализуем: "С. К. Тимошенко" → убираем лишние пробелы вокруг точек
        name = re.sub(r"([А-ЯЁ])\.\s+([А-ЯЁ])\.", r"\1.\2.", name)
        term = _clean_term(name)
        if term:
            terms.append(term)

    # Формат В: И.И. Фамилия без явного звания (частый militera-стиль)
    for m in _RE_INITIALS_SURNAME.finditer(text):
        name = m.group(1).strip()
        name = re.sub(r"([А-ЯЁ])\.\s+([А-ЯЁ])\.", r"\1.\2.", name)
        term = _clean_term(name)
        if term:
            terms.append(term)

    return terms


def _extract_quoted_terms(text: str) -> list[str]:
    """Паттерн 2: текст в «кавычках»."""
    terms: list[str] = []
    for m in _RE_QUOTED.finditer(text):
        raw = m.group(1).strip()
        term = _clean_term(raw)
        if term and not _is_stopword_term(term):
            terms.append(term)
    return terms


def _extract_unit_names(text: str) -> list[str]:
    """Паттерн 3: воинские формирования (все падежи, числа и прилагательные)."""
    terms: list[str] = []
    for m in _RE_UNIT.finditer(text):
        raw = m.group(1).strip()
        if len(raw) < MIN_TERM_LEN:
            continue
        normalized = _normalize_case(_normalize_caps(raw))
        term = _clean_term(normalized)
        if term and len(term) >= MIN_TERM_LEN:
            terms.append(term)
    return terms


def _extract_cap_sequences(text: str) -> list[str]:
    """Паттерн 4: 2-5 слов с заглавной буквы, не начало предложения."""
    terms: list[str] = []
    for m in _RE_CAP_SEQ.finditer(text):
        raw = m.group(1).strip()
        words = raw.split()
        if len(words) < 2 or len(words) > 5:
            continue
        if words[0] in _CAP_STOPWORDS:
            continue
        term = _normalize_case(_clean_term(raw) or "")
        if term:
            terms.append(term)
    return terms


def _extract_all_patterns(text: str) -> list[str]:
    """Применяет все 4 паттерна к тексту главы."""
    all_terms: list[str] = []
    all_terms.extend(_extract_rank_names(text))
    all_terms.extend(_extract_quoted_terms(text))
    all_terms.extend(_extract_unit_names(text))
    all_terms.extend(_extract_cap_sequences(text))
    return all_terms


def _looks_like_person(term: str) -> bool:
    tokens = term.split()
    has_initials = bool(re.search(r"[А-ЯЁ]\.\s*[А-ЯЁ]\.", term))
    if len(tokens) < 2 and not has_initials:
        return False
    if not re.match(r"[А-ЯЁ]", tokens[0]):
        return False
    if tokens[0].isupper() and len(tokens[0]) > 4:
        return False
    return True


def _is_stopword_term(term: str) -> bool:
    words = term.split()
    return len(words) == 1 and words[0] in _CAP_STOPWORDS


# ─────────────────────────────────────────────
# MILITERA PARSER
# ─────────────────────────────────────────────

class MiliteraParser(BaseParser):
    """
    Парсер militera.lib.ru.
    Двухуровневый crawler: Level 0 (index) + Level 1 (главы).
    Rate limit: 2 сек/запрос.
    """

    def fetch(self) -> str:
        self.logger.info(f"fetch Level 0 → {self.url}")
        cached = get_cached(self.url)
        if cached is not None:
            self.logger.info(f"fetch → cache hit ({len(cached):,} символов)")
            return cached
        self.rate_limiter.wait(self.domain)
        html = fetch_with_retry(
            url=self.url,
            session=self.session,
            rate_limiter=self.rate_limiter,
            timeout=self.timeout,
            use_cache=False,
        )
        save_cache(self.url, html)
        self.logger.info(f"fetch Level 0 OK — {len(html):,} символов")
        return html

    def _fetch_chapter(self, url: str) -> str | None:
        cached = get_cached(url)
        if cached is not None:
            return cached
        try:
            self.rate_limiter.wait(self.domain)
            html = fetch_with_retry(
                url=url,
                session=self.session,
                rate_limiter=self.rate_limiter,
                timeout=self.timeout,
                use_cache=False,
            )
            save_cache(url, html)
            return html
        except Exception as exc:
            self.logger.warning(f"Не удалось скачать главу {url}: {exc}")
            return None

    def _get_chapter_urls(self, soup: BeautifulSoup) -> list[str]:
        base_domain = urlparse(self.url).netloc
        chapter_urls: list[str] = []
        seen: set[str] = set()
        for a in soup.find_all("a", href=True):
            href = a["href"].strip()
            if _is_chapter_link(href, base_domain):
                abs_url = urljoin(self.url, href)
                if abs_url not in seen:
                    seen.add(abs_url)
                    chapter_urls.append(abs_url)
                    if len(chapter_urls) >= MAX_CHAPTERS:
                        break
        self.logger.info(f"Найдено {len(chapter_urls)} страниц глав (max {MAX_CHAPTERS})")
        return chapter_urls

    def extract_terms(self, html: str) -> list[str]:
        soup = BeautifulSoup(html, "html.parser")
        all_terms: list[str] = []

        # Level 0
        author_terms = _extract_author_from_html(soup)
        toc_terms = _extract_toc_terms(soup)
        level0_terms = _dedupe_ordered(author_terms + toc_terms)
        self.logger.info(
            f"Level 0: автор={len(author_terms)}, toc={len(toc_terms)} → {len(level0_terms)} уникальных"
        )
        all_terms.extend(level0_terms)

        # Level 1
        chapter_urls = self._get_chapter_urls(soup)
        for i, ch_url in enumerate(chapter_urls, start=1):
            self.logger.info(f"Level 1 [{i}/{len(chapter_urls)}] → {ch_url}")
            ch_html = self._fetch_chapter(ch_url)
            if not ch_html:
                continue
            ch_soup = BeautifulSoup(ch_html, "html.parser")
            for tag in ch_soup.select("nav, .footnote, .note, script, style"):
                tag.decompose()
            text = ch_soup.get_text(" ", strip=True)
            chapter_terms = _dedupe_ordered(_extract_all_patterns(text))
            self.logger.info(f"  → {len(chapter_terms)} терминов из главы")
            all_terms.extend(chapter_terms)

        result = _dedupe_ordered(all_terms)
        self.logger.info(f"extract total (after dedup): {len(result)} терминов")
        return result


# ─────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="MiliteraParser — парсинг книги militera.lib.ru"
    )
    parser.add_argument("--url", required=True, help="URL index.html книги")
    parser.add_argument("--category", required=True, help="ID категории (1–16)")
    parser.add_argument("--output-dir", default="data/parsed")
    parser.add_argument("--no-cache", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    parser = MiliteraParser(
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
