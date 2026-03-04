#!/usr/bin/env python3
"""
tests/simulations/sim_utils_base.py
Симуляция: проверка utils.py + base_parser.py без реальных запросов.
Все 12 тестов должны быть GREEN.
"""

import sys
import time
import tempfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.vocab.utils import (
    DomainRateLimiter,
    get_domain,
    normalize_url,
    get_cached,
    save_cache,
    make_session,
    setup_logger,
)
from scripts.vocab.parsers.base_parser import BaseParser

results = []


def check(name: str, condition: bool, detail: str = "") -> None:
    status = "GREEN ✅" if condition else "RED  ❌"
    msg = f"  [{status}] {name}"
    if detail:
        msg += f" — {detail}"
    print(msg)
    results.append(condition)


# ─── TEST 1: DomainRateLimiter ────────────────────────────────────────────────
print("\nTEST 1: DomainRateLimiter")
rl = DomainRateLimiter(default_interval=0.1, min_interval_map={"slow.ru": 0.3})
rl.wait("fast.ru")
t0 = time.monotonic()
rl.wait("fast.ru")
elapsed_fast = time.monotonic() - t0

rl.wait("slow.ru")
t0 = time.monotonic()
rl.wait("slow.ru")
elapsed_slow = time.monotonic() - t0

check("fast.ru соблюдает 0.1с", 0.09 <= elapsed_fast <= 0.25,
      f"elapsed={elapsed_fast:.3f}s")
check("slow.ru соблюдает 0.3с", 0.28 <= elapsed_slow <= 0.5,
      f"elapsed={elapsed_slow:.3f}s")


# ─── TEST 2: URL-утилиты ──────────────────────────────────────────────────────
print("\nTEST 2: URL-утилиты")
check("get_domain — www убирается",
      get_domain("https://www.militera.lib.ru/enc/") == "militera.lib.ru")
check("get_domain — без www",
      get_domain("http://rkka.ru/abbr.htm") == "rkka.ru")
check("normalize_url — trailing slash",
      normalize_url("https://iremember.ru/") == "https://iremember.ru")
check("normalize_url — fragment убирается",
      normalize_url("https://site.ru/page#section") == "https://site.ru/page")


# ─── TEST 3: Дисковый кэш ────────────────────────────────────────────────────
print("\nTEST 3: Дисковый кэш")
import scripts.vocab.utils as utils_mod

with tempfile.TemporaryDirectory() as tmpdir:
    orig_cache_dir = utils_mod.CACHE_DIR
    utils_mod.CACHE_DIR = Path(tmpdir)

    test_url = "https://ru.wikipedia.org/wiki/Test"
    test_html = "<html><body>Test content</body></html>"

    check("get_cached — miss (нет файла)", get_cached(test_url) is None)
    save_cache(test_url, test_html)
    cached = get_cached(test_url)
    check("get_cached — hit после save_cache",
          cached == test_html,
          f"len={len(cached) if cached else 0}")

    utils_mod.CACHE_DIR = orig_cache_dir


# ─── TEST 4: make_session ─────────────────────────────────────────────────────
print("\nTEST 4: make_session")
sess = make_session()
check("User-Agent содержит Mozilla",
      "Mozilla" in sess.headers.get("User-Agent", ""))
check("Accept-Language содержит ru",
      "ru" in sess.headers.get("Accept-Language", ""))


# ─── TEST 5: BaseParser.run() — mock HTTP ────────────────────────────────────
print("\nTEST 5: BaseParser.run() — mock HTTP")

PATCH_TARGET = "scripts.vocab.parsers.base_parser.fetch_with_retry"


class DummyParser(BaseParser):
    def extract_terms(self, html: str) -> list[str]:
        return ["Жуков", "Рокоссовский", "Конев"]


with tempfile.TemporaryDirectory() as tmpdir:
    with patch(PATCH_TARGET, return_value="<html>mock</html>"):
        parser = DummyParser(
            url="https://ru.wikipedia.org/wiki/Marshal_of_the_Soviet_Union",
            category="1",
            output_dir=tmpdir,
        )
        terms = parser.run()

    check("run() вернул термины",
          terms == ["Жуков", "Рокоссовский", "Конев"], str(terms))

    # Точки → подчёркивания (поведение save() в base_parser.py)
    out_file = Path(tmpdir) / "1" / "ru_wikipedia_org.txt"
    check("файл создан", out_file.exists(), str(out_file))

    if out_file.exists():
        content = out_file.read_text(encoding="utf-8").strip().splitlines()
        check("файл содержит 3 термина", len(content) == 3, str(content))
    else:
        check("файл содержит 3 термина", False, "файл не существует")

# ─── TEST 6: BaseParser.run() — ошибка не роняет скрипт ──────────────────────
print("\nTEST 6: BaseParser.run() — обработка ошибки")


class FailingParser(BaseParser):
    def fetch(self) -> str:
        raise ConnectionError("Timeout simulated")

    def extract_terms(self, html: str) -> list[str]:
        return []


fp = FailingParser(url="https://dead.example.com/", category="1")
fail_result = fp.run()
check("run() вернул [] при ошибке", fail_result == [], str(fail_result))


# ─── ИТОГ ────────────────────────────────────────────────────────────────────
print(f"\n{'─' * 50}")
total = len(results)
passed = sum(results)
print(f"  Итого: {passed}/{total} GREEN")
if passed == total:
    print("  ✅ ALL GREEN — utils.py + base_parser.py готовы")
else:
    print("  ❌ ЕСТЬ ОШИБКИ — смотри выше")
print(f"{'─' * 50}\n")
