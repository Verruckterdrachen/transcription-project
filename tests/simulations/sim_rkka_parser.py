#!/usr/bin/env python3
"""
tests/simulations/sim_rkka_parser.py
Симуляция rkka_parser — без сетевых запросов.
Запуск: python tests/simulations/sim_rkka_parser.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from bs4 import BeautifulSoup
from scripts.vocab.parsers.rkka_parser import (
    _clean_link_text,
    _extract_level0_link_texts,
    _extract_table_cells,
    _extract_page_terms,
    _is_content_link,
)

PASS = "✅"
FAIL = "❌"
results = []

def check(name: str, condition: bool):
    status = PASS if condition else FAIL
    results.append((status, name, condition))
    print(f"{status} {name}")


# ─── 1. _is_content_link ─────────────────────────────────────────────────────

check("is_content_link: oper/smol/main.htm → True",
      _is_content_link("oper/smol/main.htm", "rkka.ru"))

check("is_content_link: oper/finn/begin.htm → True",
      _is_content_link("oper/finn/begin.htm", "rkka.ru"))

check("is_content_link: #anchor → False",
      not _is_content_link("#anchor", "rkka.ru"))

check("is_content_link: css/rkka.css → False",
      not _is_content_link("css/rkka.css", "rkka.ru"))

check("is_content_link: http://external.com → False",
      not _is_content_link("http://external.com/page.htm", "rkka.ru"))

check("is_content_link: пустая строка → False",
      not _is_content_link("", "rkka.ru"))

check("is_content_link: oper/186sd/186sd.html → True",
      _is_content_link("oper/186sd/186sd.html", "rkka.ru"))

# ─── 2. _clean_link_text ─────────────────────────────────────────────────────

check("clean_link_text: 'Ельнинская наступательная операция 1941 г.' → not None",
      _clean_link_text("Ельнинская наступательная операция 1941 г.") is not None)

check("clean_link_text: 'Оборона Моонзундских островов' → not None",
      _clean_link_text("Оборона Моонзундских островов") is not None)

check("clean_link_text: 'В' → None (стоп-слово)",
      _clean_link_text("В") is None)

check("clean_link_text: 'На северных подступах к Ленинграду' → None (стоп-слово 'На')",
      _clean_link_text("На северных подступах к Ленинграду") is None)

check("clean_link_text: многострочный текст нормализуется",
      _clean_link_text("Боевые действия\n        войск 4-й армии") is not None)

check("clean_link_text: слишком короткий → None",
      _clean_link_text("Бой") is None)

# ─── 3. _extract_level0_link_texts ───────────────────────────────────────────

HTML_INDEX = """
<html><body>
<table>
  <tr><td>Предвоенный период</td></tr>
  <tr><td><a href="oper/tambov/main.htm">Вандея в Черноземье</a></td></tr>
  <tr><td>Зимняя война</td></tr>
  <tr><td><a href="oper/finn/begin.htm">Первый месяц войны</a></td></tr>
  <tr><td><a href="oper/elnya/main.htm">Ельнинская наступательная операция 1941 г.</a></td></tr>
  <tr><td><a href="oper/moon/main.htm">Оборона Моонзундских островов</a></td></tr>
  <tr><td><a href="oper/smol/main.htm">На смоленско-московском стратегическом направлении</a></td></tr>
  <tr><td><a href="css/rkka.css">stylesheet</a></td></tr>
  <tr><td><a href="#top">Наверх</a></td></tr>
</table>
</body></html>
"""

soup_index = BeautifulSoup(HTML_INDEX, "html.parser")
link_terms = _extract_level0_link_texts(soup_index)

check("level0_links: содержит 'Вандея в Черноземье'",
      "Вандея в Черноземье" in link_terms)

check("level0_links: содержит 'Ельнинская наступательная операция 1941 г.'",
      any("Ельнинская" in t for t in link_terms))

check("level0_links: содержит 'Оборона Моонзундских островов'",
      "Оборона Моонзундских островов" in link_terms)

check("clean_link_text: 'stylesheet' → None (нет кириллицы)",
      _clean_link_text("stylesheet") is None)

# ─── 4. _extract_table_cells ─────────────────────────────────────────────────

section_terms = _extract_table_cells(soup_index)

check("table_cells: содержит 'Предвоенный период'",
      any("Предвоенный" in t for t in section_terms))

check("table_cells: содержит 'Зимняя война'",
      any("Зимняя война" in t for t in section_terms))

check("table_cells: НЕ содержит ячейки со ссылкой (они пропускаются)",
      not any("Вандея" in t for t in section_terms))

# ─── 5. _extract_page_terms — нарратив ───────────────────────────────────────

HTML_PAGE = """
<html><body>
<h1>Ельнинская операция 1941</h1>
<p>
Командующий генерал-лейтенант Рокоссовский К.К. получил приказ.
Войска 24-й армии перешли в наступление. Г.К. Жуков лично контролировал
ход операции. В районе Ельни действовала 19-я стрелковая дивизия.
Танки группы армий «Центр» были остановлены под Ельней.
</p>
<table>
  <tr><td>Командующий</td><td>Рокоссовский К.К.</td></tr>
  <tr><td>Состав</td><td>24-я армия</td></tr>
  <tr><td>Период</td><td>30 августа — 8 сентября 1941</td></tr>
</table>
</body></html>
"""

soup_page = BeautifulSoup(HTML_PAGE, "html.parser")
page_terms = _extract_page_terms(soup_page)

check("page_terms: содержит 'Рокоссовский' (через rank_names или таблицу)",
      any("Рокоссовский" in t for t in page_terms))

check("page_terms: содержит '24-я армия' или упоминание армии",
      any("арми" in t.lower() or "Армия" in t for t in page_terms))

check("page_terms: содержит упоминание 'Жуков'",
      any("Жуков" in t for t in page_terms))

check("page_terms: содержит термин из кавычек — 'Центр'",
      any("Центр" in t for t in page_terms))

check("page_terms: список не пустой",
      len(page_terms) > 0)

# ─── 6. Дубли ────────────────────────────────────────────────────────────────

from scripts.vocab.parsers.wiki_parser import _dedupe_ordered

duped = ["Рокоссовский", "Жуков", "рокоссовский", "ЖУКОВ", "24-я армия", "Жуков"]
deduped = _dedupe_ordered(duped)

check("dedupe: нет дублей после _dedupe_ordered",
      len(deduped) == len(set(t.lower() for t in deduped)))

check("dedupe: сохранён порядок первого вхождения",
      deduped[0] == "Рокоссовский")

# ─── ИТОГ ────────────────────────────────────────────────────────────────────

total = len(results)
passed = sum(1 for s, _, _ in results if s == PASS)
failed = total - passed

print()
print(f"{'='*50}")
print(f"Результат: {passed}/{total} GREEN")
if failed:
    print(f"FAILED ({failed}):")
    for s, name, _ in results:
        if s == FAIL:
            print(f"  {FAIL} {name}")
    sys.exit(1)
else:
    print("✅ ALL GREEN")
