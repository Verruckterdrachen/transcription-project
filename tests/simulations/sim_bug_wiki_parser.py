#!/usr/bin/env python3
"""
tests/simulations/sim_bug_wiki_parser.py
Симуляция WikiParser без реальных HTTP-запросов.
Все 8 тестов должны быть GREEN.
"""

import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.vocab.parsers.wiki_parser import (
    WikiParser,
    _clean_term,
    _extract_from_tables,
    _extract_from_lists,
    _extract_from_headings,
    _extract_cyrillic_from_cells,
    _is_useful_latin,
    _get_lang,
    _get_page_title,
)
from bs4 import BeautifulSoup

results = []


def check(name: str, condition: bool, detail: str = "") -> None:
    status = "GREEN ✅" if condition else "RED  ❌"
    msg = f"  [{status}] {name}"
    if detail:
        msg += f" — {detail}"
    print(msg)
    results.append(condition)


# ─── TEST 1: _get_lang и _get_page_title ─────────────────────────────────────
print("\nTEST 1: URL-утилиты")
check("_get_lang ru",
      _get_lang("https://ru.wikipedia.org/wiki/Жуков") == "ru")
check("_get_lang en",
      _get_lang("https://en.wikipedia.org/wiki/Marshal") == "en")
check("_get_page_title простой",
      _get_page_title("https://ru.wikipedia.org/wiki/Жуков") == "Жуков")
check("_get_page_title с подчёркиваниями",
      _get_page_title(
          "https://ru.wikipedia.org/wiki/Список_Маршалов_Советского_Союза"
      ) == "Список_Маршалов_Советского_Союза")


# ─── TEST 2: _clean_term — нормализация ──────────────────────────────────────
print("\nTEST 2: _clean_term — нормализация")
check("обычное имя",
      _clean_term("Жуков Георгий Константинович") == "Жуков Георгий Константинович")
check("убирает сноску [1]",
      _clean_term("Рокоссовский[1]") == "Рокоссовский")
check("убирает русские скобки",
      _clean_term("Ленинград (ныне Санкт-Петербург)") == "Ленинград")
check("сохраняет латинские скобки",
      _clean_term("Т-34 (T-34)") == "Т-34 (T-34)")
check("None для числа",
      _clean_term("1941") is None)
check("None для слишком короткого",
      _clean_term("АБ") is None)
check("None для пустой строки",
      _clean_term("") is None)
check("убирает trailing знаки препинания",
      _clean_term("Сталинград.") == "Сталинград")


# ─── TEST 3: _extract_from_tables ────────────────────────────────────────────
print("\nTEST 3: Извлечение из wikitable")
HTML_TABLE = """
<table class="wikitable">
  <tr><th>Маршал</th><th>Дата</th></tr>
  <tr><td>Жуков Г.К.[1]</td><td>1943</td></tr>
  <tr><td>Рокоссовский К.К.</td><td>1944</td></tr>
  <tr><td>Конев И.С.</td><td>1944</td></tr>
  <tr><td>Василевский А.М.</td><td>1943</td></tr>
</table>
"""
soup = BeautifulSoup(HTML_TABLE, "html.parser")
terms = _extract_from_tables(soup)
check("4 маршала из таблицы", len(terms) == 4, str(terms))
check("сноска [1] убрана", "Жуков Г.К" in terms, str(terms))


# ─── TEST 4: _extract_from_lists ─────────────────────────────────────────────
print("\nTEST 4: Извлечение из ul/li")
HTML_LIST = """
<div>
  <ul>
    <li>Операция «Багратион» — наступательная операция 1944</li>
    <li>Сталинградская битва — 1942–1943</li>
    <li>Курская битва — 1943</li>
  </ul>
  <div class="navbox"><ul><li>навигация</li></ul></div>
</div>
"""
soup = BeautifulSoup(HTML_LIST, "html.parser")
terms = _extract_from_lists(soup)
check("3 операции из списка", len(terms) == 3, str(terms))
check("часть после тире отрезана",
      "Операция Багратион" in terms, str(terms))
check("navbox не попал в термины",
      "навигация" not in terms, str(terms))


# ─── TEST 5: _extract_from_headings ──────────────────────────────────────────
print("\nTEST 5: Извлечение из заголовков")
HTML_HEADS = """
<div>
  <h2>Маршалы Советского Союза</h2>
  <h3>Командующие фронтами</h3>
  <h2>Примечания</h2>
  <h2>Ссылки</h2>
</div>
"""
soup = BeautifulSoup(HTML_HEADS, "html.parser")
terms = _extract_from_headings(soup)
check("служебные заголовки пропущены",
      "Примечания" not in terms and "Ссылки" not in terms,
      str(terms))
check("содержательные заголовки извлечены",
      len(terms) == 2, str(terms))


# ─── TEST 6: WikiParser.extract_terms — полный HTML ──────────────────────────
print("\nTEST 6: WikiParser.extract_terms — комбинированный HTML")
HTML_COMBINED = """
<div>
  <table class="wikitable">
    <tr><th>Маршал</th></tr>
    <tr><td>Жуков Г.К.</td></tr>
    <tr><td>Конев И.С.</td></tr>
  </table>
  <ul>
    <li>Рокоссовский К.К. — Маршал Советского Союза</li>
    <li>Жуков Г.К. — дубль, должен быть удалён</li>
  </ul>
</div>
"""
import tempfile
with tempfile.TemporaryDirectory() as tmpdir:
    with patch("scripts.vocab.parsers.base_parser.fetch_with_retry",
               return_value=HTML_COMBINED):
        parser = WikiParser(
            url="https://ru.wikipedia.org/wiki/Test",
            category="1",
            output_dir=tmpdir,
        )
        terms = parser.extract_terms(HTML_COMBINED)

check("дедупликация работает",
      terms.count("Жуков Г.К") == 1, str(terms))
check("итого уникальных терминов == 3",
      len(terms) == 3, str(terms))


# ─── TEST 7: WikiParser.run() — graceful fail (dead URL) ─────────────────────
print("\nTEST 7: run() — graceful fail на dead URL")
import requests

with tempfile.TemporaryDirectory() as tmpdir:
    parser = WikiParser(
        url="https://ru.wikipedia.org/wiki/Несуществующая_страница_XYZ123",
        category="1",
        output_dir=tmpdir,
        use_cache=False,
    )
    # Мокаем API — возвращает ошибку как Wikipedia
    api_error = {"error": {"code": "missingtitle", "info": "The page does not exist"}}
    with patch.object(parser.session, "get") as mock_get:
        mock_resp = mock_get.return_value.__enter__ = mock_get.return_value
        mock_get.return_value.raise_for_status = lambda: None
        mock_get.return_value.json = lambda: api_error
        result = parser.run()

check("run() вернул [] для несуществующей страницы",
      result == [], str(result))


# ─── TEST 8: _clean_term — edge cases ────────────────────────────────────────
print("\nTEST 8: _clean_term — edge cases")
check("множественные пробелы схлопываются",
      _clean_term("Жуков  Г.К.") == "Жуков Г.К", "")
check("HTML entity убирается",
      _clean_term("Сталинград&nbsp;битва") == "Сталинград битва")
check("только знаки препинания → None",
      _clean_term("...") is None)
check("латиница сохраняется (иностранные имена)",
      _clean_term("Манштейн (Manstein)") == "Манштейн (Manstein)")

# ─── TEST 9: FIX A — нумерованная таблица (имя в cells[1]) ──────────────────
print("\nTEST 9: FIX A — нумерованная таблица")
HTML_NUMBERED = """
<table class="wikitable">
  <tr><th>№</th><th>Маршал</th><th>Дата</th></tr>
  <tr><td>1</td><td>Жуков Г.К.</td><td>1943</td></tr>
  <tr><td>2</td><td>Конев И.С.</td><td>1944</td></tr>
  <tr><td>3</td><td>Рокоссовский К.К.</td><td>1944</td></tr>
</table>
"""
soup = BeautifulSoup(HTML_NUMBERED, "html.parser")
terms = _extract_from_tables(soup)
check("FIX A: 3 маршала из нумерованной таблицы", len(terms) == 3, str(terms))
check("FIX A: порядковые номера не попали", "1" not in terms, str(terms))
check("FIX A: имя из cells[1] извлечено", "Жуков Г.К" in terms, str(terms))


# ─── TEST 10: FIX B — кириллица из en.wikipedia ──────────────────────────────
print("\nTEST 10: FIX B — кириллица из en.wikipedia ячеек")
HTML_EN_WIKI = """
<table class="wikitable">
  <tr><th>Name</th><th>Date</th></tr>
  <tr><td>Georgy Zhukov (Георгий Жуков)</td><td>1943</td></tr>
  <tr><td>Ivan Konev (Иван Конев)</td><td>1944</td></tr>
</table>
"""
soup = BeautifulSoup(HTML_EN_WIKI, "html.parser")
cyrillic = _extract_cyrillic_from_cells(soup)
check("FIX B: кириллица найдена в en-ячейках", len(cyrillic) >= 2, str(cyrillic))
check("FIX B: Жуков извлечён", any("Жуков" in t for t in cyrillic), str(cyrillic))
check("FIX B: Конев извлечён", any("Конев" in t for t in cyrillic), str(cyrillic))

# ─── TEST 11: _is_useful_latin — фильтр латиницы ─────────────────────────────
print("\nTEST 11: _is_useful_latin — фильтр")
from scripts.vocab.parsers.wiki_parser import _is_useful_latin

# Полезные — техника
check("Panzer-IV полезен",      _is_useful_latin("Panzer-IV"))
check("Bf-109 полезен",         _is_useful_latin("Bf-109"))
check("Tiger I полезен",        _is_useful_latin("Tiger I"))
check("StuG полезен",           _is_useful_latin("StuG"))
check("Wehrmacht полезен",      _is_useful_latin("Wehrmacht"))
check("Timeline → discard",          not _is_useful_latin("Timeline"))
check("Bibliography → discard",      not _is_useful_latin("Bibliography"))
check("1935 1940 and 1943 → discard", not _is_useful_latin("1935 1940 and 1943"))
check("1941-1945 → discard",         not _is_useful_latin("1941-1945"))

# ─── TEST 12: _normalize_caps ─────────────────────────────────────────────────
print("\nTEST 12: _normalize_caps — нормализация КАПСЛОКА")
from scripts.vocab.parsers.wiki_parser import _normalize_caps

check("ВОРОШИЛОВ → Ворошилов",
      _normalize_caps("ВОРОШИЛОВ") == "Ворошилов")
check("КЛИМЕНТ ЕФРЕМОВИЧ ВОРОШИЛОВ → Климент Ефремович Ворошилов",
      _normalize_caps("КЛИМЕНТ ЕФРЕМОВИЧ ВОРОШИЛОВ") == "Климент Ефремович Ворошилов")
check("смешанный регистр не трогаем",
      _normalize_caps("СБД-2") == "СБД-2")
check("уже нормальный регистр не меняем",
      _normalize_caps("Жуков Г.К") == "Жуков Г.К")

# Мусор — транслитерации
check("Georgy Zhukov → discard",
      not _is_useful_latin("Georgy Zhukov"))
check("Aleksandr Vasilevsky → discard",
      not _is_useful_latin("Aleksandr Vasilevsky"))
check("Semyon Budyonny → discard",
      not _is_useful_latin("Semyon Budyonny"))
check("Ivan Stepanovich Konev → discard",
      not _is_useful_latin("Ivan Stepanovich Konev"))

# В TEST 12 заменить последние два check:
check("ЖУКОВ → Жуков (длина 5 > 4)",
      _normalize_caps("ЖУКОВ") == "Жуков")
check("ГДР не трогаем (аббревиатура ≤ 4)",
      _normalize_caps("ГДР") == "ГДР")
check("ЧССР не трогаем (аббревиатура ≤ 4)",
      _normalize_caps("ЧССР") == "ЧССР")
check("СССР не трогаем (аббревиатура ≤ 4)",
      _normalize_caps("СССР") == "СССР")
check("НКВД не трогаем (аббревиатура ≤ 4)",
      _normalize_caps("НКВД") == "НКВД")
check("Герой ГДР — итоговая строка корректна",
      _normalize_caps("Герой ГДР") == "Герой ГДР")

# ─── TEST 13: FIX БАГ 2 — кириллица только в скобках ─────────────────────────
print("\nTEST 13: _extract_cyrillic_from_cells — только в скобках")
from scripts.vocab.parsers.wiki_parser import _RE_CYRILLIC_IN_PARENS

HTML_EN_MIXED = """
<table class="wikitable">
  <tr><th>Name</th><th>Info</th></tr>
  <tr><td>Georgy Zhukov (Георгий Жуков)</td><td>1896</td></tr>
  <tr><td>Ivan Konev (Иван Конев)</td><td>1897</td></tr>
  <tr><td>Semyon Budyonny</td><td>Выстрел</td></tr>
  <tr><td>Some article with Военная энциклопедия в тексте</td><td></td></tr>
</table>
"""
soup = BeautifulSoup(HTML_EN_MIXED, "html.parser")
cyrillic = _extract_cyrillic_from_cells(soup)
check("только имена из скобок (2 шт)",  len(cyrillic) == 2, str(cyrillic))
check("Жуков извлечён",   any("Жуков" in t for t in cyrillic), str(cyrillic))
check("Конев извлечён",   any("Конев" in t for t in cyrillic), str(cyrillic))
check("Выстрел НЕ попал", all("Выстрел" not in t for t in cyrillic), str(cyrillic))
check("Военная энциклопедия НЕ попала",
      all("энциклопедия" not in t for t in cyrillic), str(cyrillic))

# ─── ИТОГ ────────────────────────────────────────────────────────────────────
print(f"\n{'─' * 50}")
total = len(results)
passed = sum(results)
print(f"  Итого: {passed}/{total} GREEN")
if passed == total:
    print("  ✅ ALL GREEN — wiki_parser.py готов к real test")
else:
    print("  ❌ ЕСТЬ ОШИБКИ — смотри выше")
print(f"{'─' * 50}\n")
