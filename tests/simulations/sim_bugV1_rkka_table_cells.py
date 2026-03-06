#!/usr/bin/env python3
"""
tests/simulations/sim_bugV1_rkka_table_cells.py
БАГ V1: _extract_table_cells пропускает <td> с <a> → guard.htm/ibibl.htm дают 0 терминов.

ROOT CAUSE: `if td.find("a"): continue` отбрасывает все ячейки со ссылками,
но на guard.htm / ibibl.htm весь контент именно в <td><a>Текст</a></td>.

FIX: убрать условие `if td.find("a"): continue` — брать get_text() в любом случае.

Запуск: python tests/simulations/sim_bugV1_rkka_table_cells.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from bs4 import BeautifulSoup
from scripts.vocab.parsers.rkka_parser import _extract_table_cells

PASS = "✅"
FAIL = "❌"
results = []

def check(name: str, condition: bool):
    status = PASS if condition else FAIL
    results.append((status, name))
    print(f"{status} {name}")


# ─── HTML-фрагменты реального типа guard.htm / ibibl.htm ─────────────────────
# guard.htm: таблица гвардейских частей — все данные в <td><a href>Название</a></td>
HTML_GUARD = """
<html><body>
<table>
  <tr>
    <td><a href="guard/1gvA.htm">1-я гвардейская армия</a></td>
    <td><a href="guard/2gvA.htm">2-я гвардейская армия</a></td>
  </tr>
  <tr>
    <td><a href="guard/1gvTK.htm">1-й гвардейский танковый корпус</a></td>
    <td><a href="guard/3gvTK.htm">3-й гвардейский танковый корпус</a></td>
  </tr>
  <tr>
    <td><a href="guard/1gvKK.htm">1-й гвардейский кавалерийский корпус</a></td>
    <td>Состав на 1943 год</td>
  </tr>
</table>
</body></html>
"""

# ibibl.htm: библиография — авторы и названия в <td><a>...</a></td>
HTML_IBIBL = """
<html><body>
<table>
  <tr>
    <td><a href="bibl/zhukov.htm">Жуков Г.К. Воспоминания и размышления</a></td>
  </tr>
  <tr>
    <td><a href="bibl/rokoss.htm">Рокоссовский К.К. Солдатский долг</a></td>
  </tr>
  <tr>
    <td><a href="bibl/vasilevsky.htm">Василевский А.М. Дело всей жизни</a></td>
  </tr>
  <tr>
    <td>Примечания</td>
  </tr>
</table>
</body></html>
"""

# hist/f.htm: список фронтов — <td><a href="1-bf.htm">1-й Белорусский фронт</a></td>
HTML_HIST_F = """
<html><body>
<table>
  <tr>
    <td><a href="hist/1-bf.htm">1-й Белорусский фронт</a></td>
    <td><a href="hist/2-bf.htm">2-й Белорусский фронт</a></td>
  </tr>
  <tr>
    <td><a href="hist/1-uf.htm">1-й Украинский фронт</a></td>
    <td><a href="hist/2-uf.htm">2-й Украинский фронт</a></td>
  </tr>
  <tr>
    <td><a href="hist/zf.htm">Западный фронт</a></td>
    <td>Период: 1941–1945</td>
  </tr>
</table>
</body></html>
"""

# ─── ТЕСТЫ: БАГОВОЕ поведение (ДО фикса) ─────────────────────────────────────
# Демонстрируем, что БЕЗ фикса guard.htm/ibibl.htm дают 0 терминов

soup_guard = BeautifulSoup(HTML_GUARD, "html.parser")
soup_ibibl = BeautifulSoup(HTML_IBIBL, "html.parser")
soup_hist_f = BeautifulSoup(HTML_HIST_F, "html.parser")

terms_guard_buggy = _extract_table_cells(soup_guard)
terms_ibibl_buggy = _extract_table_cells(soup_ibibl)
terms_hist_f_buggy = _extract_table_cells(soup_hist_f)

print("\n--- ДО ФИКСА (ожидаем 0 из <td><a>) ---")
check("БАГ guard: <td><a>1-я гвардейская армия</a></td> → НЕ извлекается (текущее поведение)",
      "1-я гвардейская армия" not in terms_guard_buggy)

check("БАГ ibibl: <td><a>Жуков Г.К.</a></td> → НЕ извлекается (текущее поведение)",
      not any("Жуков" in t for t in terms_ibibl_buggy))

check("БАГ hist/f: <td><a>1-й Белорусский фронт</a></td> → НЕ извлекается (текущее поведение)",
      not any("Белорусский" in t for t in terms_hist_f_buggy))

check("БАГ guard: ячейка без <a> ('Состав на 1943 год') всё же извлекается",
      any("Состав" in t for t in terms_guard_buggy))


# ─── ФИКС: новая версия _extract_table_cells ─────────────────────────────────

import re
from scripts.vocab.parsers.wiki_parser import _clean_term, _normalize_caps
from scripts.vocab.parsers.militera_parser import _is_stopword_term

MIN_TERM_LEN = 3
MAX_TERM_LEN = 80

def _extract_table_cells_fixed(soup: BeautifulSoup) -> list[str]:
    """
    FIX: убрано `if td.find("a"): continue`.
    Берём get_text() из любой <td>, независимо от наличия <a>.
    """
    terms: list[str] = []
    for td in soup.find_all("td"):
        raw = td.get_text(" ", strip=True)
        raw = re.sub(r"\s+", " ", raw).strip()
        if len(raw) < MIN_TERM_LEN or len(raw) > MAX_TERM_LEN:
            continue
        if not re.search(r"[а-яёА-ЯЁ]", raw):
            continue
        term = _clean_term(_normalize_caps(raw))
        if term and not _is_stopword_term(term):
            terms.append(term)
    return terms


# ─── ТЕСТЫ: ФИКС ─────────────────────────────────────────────────────────────

print("\n--- ПОСЛЕ ФИКСА ---")

terms_guard_fixed = _extract_table_cells_fixed(soup_guard)
terms_ibibl_fixed = _extract_table_cells_fixed(soup_ibibl)
terms_hist_f_fixed = _extract_table_cells_fixed(soup_hist_f)

# guard.htm
check("FIX guard: '1-я гвардейская армия' извлекается",
      any("гвардейская армия" in t for t in terms_guard_fixed))

check("FIX guard: '1-й гвардейский танковый корпус' извлекается",
      any("танковый корпус" in t for t in terms_guard_fixed))

check("FIX guard: '1-й гвардейский кавалерийский корпус' извлекается",
      any("кавалерийский" in t for t in terms_guard_fixed))

check("FIX guard: мусор 'Состав на 1943 год' тоже проходит (ok, clean_dicts уберёт)",
      any("Состав" in t for t in terms_guard_fixed))

# ibibl.htm
check("FIX ibibl: 'Жуков' извлекается",
      any("Жуков" in t for t in terms_ibibl_fixed))

check("FIX ibibl: 'Рокоссовский' извлекается",
      any("Рокоссовский" in t for t in terms_ibibl_fixed))

check("FIX ibibl: 'Василевский' извлекается",
      any("Василевский" in t for t in terms_ibibl_fixed))

# hist/f.htm
check("FIX hist/f: '1-й Белорусский фронт' извлекается",
      any("Белорусский фронт" in t for t in terms_hist_f_fixed))

check("FIX hist/f: '1-й Украинский фронт' извлекается",
      any("Украинский фронт" in t for t in terms_hist_f_fixed))

check("FIX hist/f: 'Западный фронт' извлекается",
      any("Западный фронт" in t for t in terms_hist_f_fixed))

# ─── Нет регрессии: ячейки без кириллицы не проходят ─────────────────────────
HTML_NOTEXT = """
<html><body><table>
  <tr><td><a href="img/map.jpg">map</a></td></tr>
  <tr><td>123</td></tr>
  <tr><td>  </td></tr>
</table></body></html>
"""
soup_notext = BeautifulSoup(HTML_NOTEXT, "html.parser")
terms_notext = _extract_table_cells_fixed(soup_notext)

check("REGRESSION: ячейки без кириллицы не извлекаются",
      len(terms_notext) == 0)

check("FIX guard: результат не пустой (>= 5 терминов)",
      len(terms_guard_fixed) >= 5)

check("FIX hist/f: результат не пустой (>= 3 терминов)",
      len(terms_hist_f_fixed) >= 3)


# ─── ИТОГ ────────────────────────────────────────────────────────────────────

total = len(results)
passed = sum(1 for s, _ in results if s == PASS)
failed = total - passed

print()
print(f"{'='*55}")
print(f"Результат: {passed}/{total} GREEN")
if failed:
    print(f"FAILED ({failed}):")
    for s, name in results:
        if s == FAIL:
            print(f"  {FAIL} {name}")
    sys.exit(1)
else:
    print("✅ ALL GREEN")
