#!/usr/bin/env python3
"""
tests/simulations/sim_militera_parser.py
Симуляция militera_parser.py — 100% offline, без сети.

Запуск:
  python tests/simulations/sim_militera_parser.py
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.vocab.parsers.militera_parser import (
    MiliteraParser,
    _extract_author_from_html,
    _extract_cap_sequences,
    _extract_quoted_terms,
    _extract_rank_names,
    _extract_toc_terms,
    _extract_unit_names,
    _is_chapter_link,
    _looks_like_person,
)
from bs4 import BeautifulSoup

PASS = 0
FAIL = 0


def check(name: str, condition: bool, detail: str = "") -> None:
    global PASS, FAIL
    if condition:
        PASS += 1
        print(f"  ✅ {name}")
    else:
        FAIL += 1
        print(f"  ❌ {name}" + (f" — {detail}" if detail else ""))


# ─────────────────────────────────────────────
# HTML-фрагменты
# ─────────────────────────────────────────────

INDEX_HTML = """
<html><head>
<title>Рокоссовский К.К. - Солдатский долг</title>
</head><body>
<h1>Рокоссовский К.К. — Солдатский долг</h1>
<h2>Оглавление</h2>
<ul>
  <li><a href="01.html">Глава 1. На Волоколамском направлении</a></li>
  <li><a href="02.html">Глава 2. Сталинград</a></li>
  <li><a href="03.html">Глава 3. Курская дуга</a></li>
  <li><a href="04.html">Глава 4. Операция Багратион</a></li>
  <li><a href="05.html">Глава 5. На Висле</a></li>
  <li><a href="mailto:info@militera.lib.ru">Написать нам</a></li>
  <li><a href="http://other.ru/page">Внешняя ссылка</a></li>
</ul>
</body></html>
"""

INDEX_HTML_NO_CHAPTERS = """
<html><head><title>Исаев А.В. - Когда внезапности уже не было</title></head>
<body>
<h1>Исаев А.В. — Когда внезапности уже не было</h1>
<ul>
  <li><a href="../../index.html">Назад</a></li>
  <li><a href="#contents">Оглавление</a></li>
</ul>
</body></html>
"""

CHAPTER_HTML = """
<html><body>
<p>Маршал С. К. Тимошенко тепло принял меня.</p>
<p>Генерала армии Г. К. Жукова направили в Москву.</p>
<p>Генерал-майор Н. А. Новиков командовал 35-й танковой дивизией.</p>
<p>Полковник М. Е. Катуков вёл в бои 20-ю танковую дивизию.</p>
<p>Генерал-майор Алексей Гаврилович Маслов держал штаб корпуса хорошо.</p>
<p>Адмирал Н. Г. Кузнецов руководил Черноморским флотом.</p>
<p>Наши войска удерживали «Волоколамский плацдарм» в течение недели.</p>
<p>«Операция Уран» началась 19 ноября 1942 года.</p>
<p>Западный фронт получил подкрепление из резервов Ставки.</p>
<p>В составе Киевского Особого военного округа действовала 5-я общевойсковая армия.</p>
<p>9-й механизированный корпус был направлен к Ровно.</p>
<p>Курская дуга стала переломным моментом войны.</p>
<p>Днепровский плацдарм был захвачен в сентябре 1943 года.</p>
<p>Народный комиссар обороны отдал приказ.</p>
<p>Начальник Генерального штаба генерал М. А. Пуркаев сообщил обстановку.</p>
<p>Комкор Белов прорвал оборону противника.</p>
</body></html>
"""

# ─────────────────────────────────────────────
# ТЕСТ 1: _is_chapter_link
# ─────────────────────────────────────────────

print("\n📋 ТЕСТ 1: _is_chapter_link")
check("01.html → True",           _is_chapter_link("01.html", "militera.lib.ru"))
check("01.htm → True",            _is_chapter_link("01.htm", "militera.lib.ru"))
check("chapter1.html → True",     _is_chapter_link("chapter1.html", "militera.lib.ru"))
check("#anchor → False",          not _is_chapter_link("#anchor", "militera.lib.ru"))
check("../../index.html → False", not _is_chapter_link("../../index.html", "militera.lib.ru"))
check("http://other.ru → False",  not _is_chapter_link("http://other.ru/page", "militera.lib.ru"))
check("mailto → False",           not _is_chapter_link("mailto:x@x.ru", "militera.lib.ru"))
check("empty → False",            not _is_chapter_link("", "militera.lib.ru"))

# ─────────────────────────────────────────────
# ТЕСТ 2: _extract_author_from_html
# ─────────────────────────────────────────────

print("\n📋 ТЕСТ 2: _extract_author_from_html")
soup_index = BeautifulSoup(INDEX_HTML, "html.parser")
authors = _extract_author_from_html(soup_index)
check("Автор извлечён",            len(authors) >= 1, f"got: {authors}")
check("Рокоссовский в авторах",    any("Рокоссовский" in a for a in authors), f"got: {authors}")

soup_isaev = BeautifulSoup(INDEX_HTML_NO_CHAPTERS, "html.parser")
authors_isaev = _extract_author_from_html(soup_isaev)
check("Исаев извлечён",            any("Исаев" in a for a in authors_isaev), f"got: {authors_isaev}")

# ─────────────────────────────────────────────
# ТЕСТ 3: _extract_toc_terms
# ─────────────────────────────────────────────

print("\n📋 ТЕСТ 3: _extract_toc_terms")
toc = _extract_toc_terms(soup_index)
check("TOC не пустой",             len(toc) >= 2, f"got: {toc}")
check("Сталинград в TOC",          any("Сталинград" in t for t in toc), f"got: {toc}")
check("Курская дуга в TOC",        any("Курская" in t for t in toc), f"got: {toc}")
check("Багратион в TOC",           any("Багратион" in t for t in toc), f"got: {toc}")

# ─────────────────────────────────────────────
# ТЕСТ 4: _get_chapter_urls (через экземпляр класса)
# ─────────────────────────────────────────────

print("\n📋 ТЕСТ 4: _get_chapter_urls (метод класса, offline)")

class NoNetworkParser(MiliteraParser):
    """Мок: блокирует все сетевые вызовы."""
    def fetch(self) -> str:
        return INDEX_HTML
    def _fetch_chapter(self, url: str) -> str | None:
        return CHAPTER_HTML

mock_for_urls = NoNetworkParser(
    url="http://militera.lib.ru/memo/russian/rokossovsky/index.html",
    category="1",
    output_dir="/tmp/test_parsed",
    use_cache=False,
)
chapter_urls = mock_for_urls._get_chapter_urls(soup_index)
check("Найдены главы >= 4",        len(chapter_urls) >= 4, f"got: {len(chapter_urls)}")
check("Абсолютные URL",            all(u.startswith("http") for u in chapter_urls))
check("Нет внешних (other.ru)",    all("other.ru" not in u for u in chapter_urls))
check("Нет #anchor",               all("#" not in u for u in chapter_urls))
check("Нет mailto",                all("mailto" not in u for u in chapter_urls))

# ─────────────────────────────────────────────
# ТЕСТ 5: _extract_rank_names
# ─────────────────────────────────────────────

print("\n📋 ТЕСТ 5: _extract_rank_names — все форматы")
soup_ch = BeautifulSoup(CHAPTER_HTML, "html.parser")
text = soup_ch.get_text(" ", strip=True)
rank_terms = _extract_rank_names(text)
flat = " ".join(rank_terms)
check("Тимошенко (формат Б: И.И. Фамилия)",  "Тимошенко" in flat, f"got: {rank_terms}")
check("Жуков (формат Б)",                    "Жуков" in flat,      f"got: {rank_terms}")
check("Новиков (формат Б)",                  "Новиков" in flat,    f"got: {rank_terms}")
check("Катуков (формат Б)",                  "Катуков" in flat,    f"got: {rank_terms}")
check("Маслов (формат А: полное ФИО)",       "Маслов" in flat,     f"got: {rank_terms}")
check("Кузнецов (формат Б)",                 "Кузнецов" in flat,   f"got: {rank_terms}")
check("Белов (формат А)",                    "Белов" in flat,      f"got: {rank_terms}")
check("Пуркаев (формат В: без звания)",      "Пуркаев" in flat,    f"got: {rank_terms}")

# ─────────────────────────────────────────────
# ТЕСТ 6: _extract_quoted_terms
# ─────────────────────────────────────────────

print("\n📋 ТЕСТ 6: _extract_quoted_terms")
quoted = _extract_quoted_terms(text)
check("«Волоколамский плацдарм»",  any("Волоколамский" in t for t in quoted), f"got: {quoted}")
check("«Операция Уран»",           any("Уран" in t for t in quoted), f"got: {quoted}")
check("Кол-во цитат >= 2",         len(quoted) >= 2, f"got: {quoted}")

# ─────────────────────────────────────────────
# ТЕСТ 7: _extract_unit_names
# ─────────────────────────────────────────────

print("\n📋 ТЕСТ 7: _extract_unit_names — падежи + прилагательные")
units = _extract_unit_names(text)
flat_u = " ".join(units)
check("Западный фронт",                       "фронт" in flat_u.lower(),   f"got: {units}")
check("5-я армия (или армия)",                "армия" in flat_u.lower(),   f"got: {units}")
check("Черноморский флот (или флот)",         "флот" in flat_u.lower(),    f"got: {units}")
check("9-й механизированный корпус",          "корпус" in flat_u.lower(),  f"got: {units}")
check("Киевский Особый военный округ (округ)", "округ" in flat_u.lower(), f"got: {units}")
check("9-й мех. корпус", any("корпус" in t.lower() for t in units), f"got: {units}")

# ─────────────────────────────────────────────
# ТЕСТ 8: _extract_cap_sequences
# ─────────────────────────────────────────────

print("\n📋 ТЕСТ 8: _extract_cap_sequences")
caps = _extract_cap_sequences(text)
check("Курская дуга",              any("Курская" in t for t in caps), f"got: {caps}")
check("Днепровский плацдарм",      any("Днепровский" in t for t in caps), f"got: {caps}")

# ─────────────────────────────────────────────
# ТЕСТ 9: _looks_like_person
# ─────────────────────────────────────────────

print("\n📋 ТЕСТ 9: _looks_like_person")
check("Жуков Г.К. → True",        _looks_like_person("Жуков Г.К."))
check("Рокоссовский К.К. → True", _looks_like_person("Рокоссовский К.К."))
check("Иван Конев → True",        _looks_like_person("Иван Конев"))
check("Жуков → False",            not _looks_like_person("Жуков"))
check("СССР → False",             not _looks_like_person("СССР"))
check("ЖУКОВ → False",            not _looks_like_person("ЖУКОВ"))

# ─────────────────────────────────────────────
# ТЕСТ 10: MiliteraParser.extract_terms() — полный offline
# ─────────────────────────────────────────────

print("\n📋 ТЕСТ 10: MiliteraParser.extract_terms() — offline")

class MockMiliteraParser(MiliteraParser):
    """Мок: index.html и все главы — из констант выше."""
    def _fetch_chapter(self, url: str) -> str | None:
        return CHAPTER_HTML
    def _get_chapter_urls(self, soup) -> list[str]:
        return [
            "http://militera.lib.ru/memo/russian/rokossovsky/01.html",
            "http://militera.lib.ru/memo/russian/rokossovsky/02.html",
        ]

mock = MockMiliteraParser(
    url="http://militera.lib.ru/memo/russian/rokossovsky/index.html",
    category="1",
    output_dir="/tmp/test_parsed",
    use_cache=False,
)
terms = mock.extract_terms(INDEX_HTML)
check("extract_terms не пустой",   len(terms) >= 10, f"got: {len(terms)}")
check("Жуков в результате",        any("Жуков" in t for t in terms), f"got: {terms[:20]}")
check("Рокоссовский в результате", any("Рокоссовский" in t for t in terms), f"got: {terms[:20]}")
check("Курская дуга в результате", any("Курская" in t for t in terms), f"got: {terms[:20]}")
check("Нет дублей (case-insensitive)",
      len(terms) == len(set(t.lower() for t in terms)),
      f"дублей: {len(terms) - len(set(t.lower() for t in terms))}")
check("Нет пустых строк",          all(t.strip() for t in terms))
check("Нет слишком коротких (<3)", all(len(t) >= 3 for t in terms))
check("Нет слишком длинных (>80)", all(len(t) <= 80 for t in terms))

# ─────────────────────────────────────────────
# ИТОГ
# ─────────────────────────────────────────────

print(f"\n{'='*50}")
total = PASS + FAIL
print(f"ИТОГ: {PASS}/{total} GREEN")
if FAIL == 0:
    print("✅ ALL GREEN")
else:
    print(f"❌ FAIL: {FAIL} тестов не прошли")
    sys.exit(1)
