#!/usr/bin/env python3
"""
tests/simulations/sim_bugV2_militera_chapter_link.py
БАГ V2: _is_chapter_link не распознаёт страницы энциклопедий militera.
Паттерн `^(\d+|[a-z]\d*|chapter\d*)\.html?$` пропускает zal01.html, part02.html, text03.html.

ROOT CAUSE: паттерн написан под мемуары (01.html, 02.html),
не покрывает энциклопедии (zal01.html, part01.html, text01.html).

FIX: расширить до `^([a-zA-Z]*\d+|chapter\d*|part\d*|text\d*)\.html?$`

Запуск: python tests/simulations/sim_bugV2_militera_chapter_link.py
"""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.vocab.parsers.militera_parser import _is_chapter_link

PASS = "✅"
FAIL = "❌"
results = []

def check(name: str, condition: bool):
    status = PASS if condition else FAIL
    results.append((status, name))
    print(f"{status} {name}")


BASE = "militera.lib.ru"

# ─── ТЕСТЫ: БАГОВОЕ поведение (ДО фикса) ─────────────────────────────────────
print("--- ДО ФИКСА ---")

check("БАГ: zal01.html → False (не распознаётся)",
      not _is_chapter_link("zal01.html", BASE))

check("БАГ: zal12.html → False",
      not _is_chapter_link("zal12.html", BASE))

check("БАГ: part01.html → False",
      not _is_chapter_link("part01.html", BASE))

check("БАГ: text03.htm → False",
      not _is_chapter_link("text03.htm", BASE))

# Что сейчас работает (мемуары)
check("OK сейчас: 01.html → True",
      _is_chapter_link("01.html", BASE))

check("OK сейчас: a1.html → True",
      _is_chapter_link("a1.html", BASE))


# ─── ФИКС: новая версия _is_chapter_link ─────────────────────────────────────

def _is_chapter_link_fixed(href: str, base_domain: str) -> bool:
    if not href or href.startswith("#") or href.startswith("mailto"):
        return False
    if href.startswith("http") and base_domain not in href:
        return False
    name = href.rstrip("/").split("/")[-1]
    return bool(re.match(
        r"^([a-zA-Z]*\d+|chapter\d*|part\d*|text\d*)\.html?$",
        name, re.IGNORECASE
    ))


# ─── ТЕСТЫ: ФИКС ─────────────────────────────────────────────────────────────
print("\n--- ПОСЛЕ ФИКСА ---")

# Энциклопедии (zalessky_ka05 и подобные)
check("FIX: zal01.html → True",
      _is_chapter_link_fixed("zal01.html", BASE))

check("FIX: zal12.html → True",
      _is_chapter_link_fixed("zal12.html", BASE))

check("FIX: part01.html → True",
      _is_chapter_link_fixed("part01.html", BASE))

check("FIX: part15.htm → True",
      _is_chapter_link_fixed("part15.htm", BASE))

check("FIX: text03.htm → True",
      _is_chapter_link_fixed("text03.htm", BASE))

check("FIX: text10.html → True",
      _is_chapter_link_fixed("text10.html", BASE))

# Мемуары — регрессия не сломана
check("REGRESSION: 01.html → True (мемуары)",
      _is_chapter_link_fixed("01.html", BASE))

check("REGRESSION: a1.html → True",
      _is_chapter_link_fixed("a1.html", BASE))

check("REGRESSION: chapter1.html → True",
      _is_chapter_link_fixed("chapter1.html", BASE))

check("REGRESSION: 15.htm → True",
      _is_chapter_link_fixed("15.htm", BASE))

# Ложные срабатывания НЕ должны проходить
check("NO false positive: index.html → False",
      not _is_chapter_link_fixed("index.html", BASE))

check("NO false positive: #anchor → False",
      not _is_chapter_link_fixed("#anchor", BASE))

check("NO false positive: внешний домен → False",
      not _is_chapter_link_fixed("http://external.com/zal01.html", BASE))

check("NO false positive: style.css → False",
      not _is_chapter_link_fixed("style.css", BASE))

check("NO false positive: пустая строка → False",
      not _is_chapter_link_fixed("", BASE))

# Абсолютная ссылка на тот же домен — должна работать
check("FIX: абсолютный URL того же домена с zal01.html → True",
      _is_chapter_link_fixed(
          "http://militera.lib.ru/enc/zalessky_ka05/zal01.html", BASE))

check("FIX: абсолютный URL того же домена с part02.htm → True",
      _is_chapter_link_fixed(
          "http://militera.lib.ru/enc/enc_vov1985/part02.htm", BASE))


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
