#!/usr/bin/env python3
"""
scripts/vocab/run_all_parsers.py
Оркестратор батч-парсинга: читает url_audit.csv → выбирает парсер → запускает.

CLI:
    python scripts/vocab/run_all_parsers.py --all
    python scripts/vocab/run_all_parsers.py --priority HIGH
    python scripts/vocab/run_all_parsers.py --categories 1,5
    python scripts/vocab/run_all_parsers.py --parsers wiki,militera
    python scripts/vocab/run_all_parsers.py --url "https://..." --category 1
    python scripts/vocab/run_all_parsers.py --dry-run --all

Версия: v17.24
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import re
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import urlparse

# ← ДОБАВИТЬ ЭТУ СТРОКУ (до импортов из scripts.*)
sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from scripts.vocab.parsers.militera_parser import MiliteraParser
from scripts.vocab.parsers.rkka_parser import RkkaParser
from scripts.vocab.parsers.wiki_parser import WikiParser
from scripts.vocab.utils import get_default_rate_limiter, setup_logger

# ─────────────────────────────────────────────
# КОНСТАНТЫ
# ─────────────────────────────────────────────

URL_AUDIT_CSV = Path("data/dictionaries/url_audit.csv")
OUTPUT_DIR = Path("data/parsed")

# Маппинг: фрагмент домена → (parseable-тег, класс парсера)
DOMAIN_PARSER_MAP: dict[str, tuple[str, type]] = {
    "wikipedia.org": ("requests+bs4", WikiParser),
    "militera.lib.ru": ("requests+bs4", MiliteraParser),
    "rkka.ru": ("requests+bs4", RkkaParser),
}

# Теги, которые run_all_parsers умеет обрабатывать
SUPPORTED_PARSEABLE = {"requests+bs4"}

# Теги, которые всегда пропускаются
SKIP_PARSEABLE = {"dead", "manual", "api", "pymupdf", "selenium"}

# Алиасы для --parsers CLI
PARSER_ALIASES: dict[str, str] = {
    "wiki": "wikipedia.org",
    "militera": "militera.lib.ru",
    "rkka": "rkka.ru",
}


# ─────────────────────────────────────────────
# СТРУКТУРА СТРОКИ CSV
# ─────────────────────────────────────────────

@dataclass
class UrlEntry:
    category_id: str
    category_name: str
    url: str
    status_code: str
    content_type: str
    parseable: str
    priority: str
    notes: str

    def domain_key(self) -> str:
        """Возвращает ключ из DOMAIN_PARSER_MAP, которому соответствует URL."""
        netloc = urlparse(self.url).netloc.lower().lstrip("www.")
        for key in DOMAIN_PARSER_MAP:
            if key in netloc:
                return key
        return ""

    def parser_class(self) -> type | None:
        key = self.domain_key()
        if key:
            return DOMAIN_PARSER_MAP[key][1]
        return None

    def output_filename(self) -> str:
        """
        Уникальное имя файла для data/parsed/{cat}/{filename}.txt
        Формат: {domain_safe}__{url_hash8}.txt
        Позволяет батч-парсить несколько URL одного домена в одну категорию.
        """
        netloc = urlparse(self.url).netloc.lower().lstrip("www.")
        domain_safe = re.sub(r"[^a-z0-9]", "_", netloc)
        url_hash = hashlib.md5(self.url.encode("utf-8")).hexdigest()[:8]
        return f"{domain_safe}__{url_hash}"


# ─────────────────────────────────────────────
# ЧТЕНИЕ url_audit.csv
# ─────────────────────────────────────────────

def load_entries(csv_path: Path) -> list[UrlEntry]:
    entries = []
    with open(csv_path, encoding="utf-8", newline="") as f:
        reader = csv.DictReader(f)
        for row in reader:
            entries.append(UrlEntry(
                category_id=row.get("category_id", "").strip(),
                category_name=row.get("category_name", "").strip(),
                url=row.get("url", "").strip(),
                status_code=row.get("status_code", "").strip(),
                content_type=row.get("content_type", "").strip(),
                parseable=row.get("parseable", "").strip().lower(),
                priority=row.get("priority", "").strip().upper(),
                notes=row.get("notes", "").strip(),
            ))
    return entries


# ─────────────────────────────────────────────
# ФИЛЬТРАЦИЯ
# ─────────────────────────────────────────────

def filter_entries(
    entries: list[UrlEntry],
    priority: str | None = None,
    categories: list[str] | None = None,
    parsers: list[str] | None = None,
    single_url: str | None = None,
    single_category: str | None = None,
) -> list[UrlEntry]:
    """
    Применяет фильтры по приоритету, категориям, типам парсеров.
    Всегда пропускает dead/manual/api/pymupdf/selenium.
    """
    result = []
    for e in entries:
        # Пропустить неподдерживаемые parseable-теги
        if e.parseable in SKIP_PARSEABLE:
            continue
        if e.parseable not in SUPPORTED_PARSEABLE:
            continue
        # Пропустить если нет класса парсера для этого домена
        if e.parser_class() is None:
            continue
        # Пропустить пустые URL
        if not e.url:
            continue

        if priority and e.priority != priority:
            continue
        if categories and e.category_id not in categories:
            continue
        if parsers:
            domain_key = e.domain_key()
            allowed_domains = {PARSER_ALIASES.get(p, p) for p in parsers}
            if domain_key not in allowed_domains:
                continue

        result.append(e)

    # Режим одного URL
    if single_url:
        cat = single_category or "unknown"
        # Найти по URL или создать синтетическую запись
        matched = [e for e in result if e.url == single_url]
        if matched:
            return matched
        # URL не в csv — попытаться определить парсер по домену
        netloc = urlparse(single_url).netloc.lower().lstrip("www.")
        for key in DOMAIN_PARSER_MAP:
            if key in netloc:
                return [UrlEntry(
                    category_id=cat, category_name="", url=single_url,
                    status_code="", content_type="text/html",
                    parseable="requests+bs4", priority="MED", notes="ad-hoc",
                )]
        return []

    return result


# ─────────────────────────────────────────────
# ЗАПУСК ПАРСЕРОВ
# ─────────────────────────────────────────────

def run_parsers(
    entries: list[UrlEntry],
    output_dir: Path = OUTPUT_DIR,
    dry_run: bool = False,
    no_cache: bool = False,
) -> dict:
    """
    Запускает парсер для каждой записи.
    Возвращает статистику: {total, success, failed, skipped, terms_total}.
    """
    logger = setup_logger("run_all_parsers")
    rate_limiter = get_default_rate_limiter()

    stats = {
        "total": len(entries),
        "success": 0,
        "failed": 0,
        "skipped": 0,
        "terms_total": 0,
        "errors": [],  # list of (url, error_msg)
    }

    logger.info(f"▶ Запуск: {len(entries)} URL")
    start_all = time.monotonic()

    for idx, entry in enumerate(entries, 1):
        ParserClass = entry.parser_class()
        if ParserClass is None:
            logger.warning(f"[{idx}/{len(entries)}] Нет парсера для {entry.url} — пропуск")
            stats["skipped"] += 1
            continue

        logger.info(
            f"[{idx}/{len(entries)}] {ParserClass.__name__} "
            f"cat={entry.category_id} {entry.url}"
        )

        if dry_run:
            logger.info("  DRY-RUN — пропуск реального запроса")
            stats["skipped"] += 1
            continue

        # Создаём парсер с уникальным output_filename
        parser = ParserClass(
            url=entry.url,
            category=entry.category_id,
            output_dir=str(output_dir),
            rate_limiter=rate_limiter,
            use_cache=not no_cache,
        )

        # Переопределяем domain для уникального имени файла
        # (чтобы несколько URL одного домена не затирали друг друга)
        parser.domain = entry.output_filename()

        terms = parser.run()

        if terms:
            stats["success"] += 1
            stats["terms_total"] += len(terms)
            logger.info(f"  ✅ {len(terms)} терминов")
        else:
            stats["failed"] += 1
            stats["errors"].append((entry.url, "0 терминов или исключение"))
            logger.warning(f"  ❌ 0 терминов: {entry.url}")

    elapsed = time.monotonic() - start_all
    logger.info(
        f"─── ИТОГ ───────────────────────────────────\n"
        f"  Всего:    {stats['total']}\n"
        f"  Успешно:  {stats['success']}\n"
        f"  Ошибки:   {stats['failed']}\n"
        f"  Пропуски: {stats['skipped']}\n"
        f"  Терминов: {stats['terms_total']:,}\n"
        f"  Время:    {elapsed:.0f} сек\n"
        f"────────────────────────────────────────────"
    )

    if stats["errors"]:
        logger.warning("Ошибочные URL:")
        for url, msg in stats["errors"]:
            logger.warning(f"  ✗ {url} — {msg}")

    return stats


# ─────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Батч-парсинг url_audit.csv → data/parsed/",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Примеры:
  python scripts/vocab/run_all_parsers.py --all
  python scripts/vocab/run_all_parsers.py --priority HIGH
  python scripts/vocab/run_all_parsers.py --categories 1,5
  python scripts/vocab/run_all_parsers.py --parsers wiki,militera
  python scripts/vocab/run_all_parsers.py --url "http://rkka.ru/hist/f.htm" --category 5
  python scripts/vocab/run_all_parsers.py --dry-run --all
        """,
    )
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--all", action="store_true", help="Все живые URL (parseable=requests+bs4)")
    mode.add_argument("--priority", choices=["HIGH", "MED", "LOW"], help="Фильтр по приоритету")
    mode.add_argument("--categories", help="Категории через запятую: 1,5,7")
    mode.add_argument("--parsers", help="Парсеры через запятую: wiki,militera,rkka")
    mode.add_argument("--url", help="Один URL (требует --category)")

    p.add_argument("--category", help="Категория для --url режима")
    p.add_argument("--csv", default=str(URL_AUDIT_CSV), help="Путь к url_audit.csv")
    p.add_argument("--output-dir", default=str(OUTPUT_DIR), help="Директория для data/parsed/")
    p.add_argument("--dry-run", action="store_true", help="Показать план без реального парсинга")
    p.add_argument("--no-cache", action="store_true", help="Игнорировать кэш (свежий fetch)")
    return p


def main() -> None:
    ap = build_parser()
    args = ap.parse_args()

    logger = setup_logger("run_all_parsers")

    # Загрузка CSV
    csv_path = Path(args.csv)
    if not csv_path.exists():
        logger.error(f"Файл не найден: {csv_path}")
        sys.exit(1)

    all_entries = load_entries(csv_path)
    logger.info(f"Загружено {len(all_entries)} строк из {csv_path}")

    # Определить фильтры
    priority = args.priority or None
    categories = [c.strip() for c in args.categories.split(",")] if args.categories else None
    parsers = [p.strip() for p in args.parsers.split(",")] if args.parsers else None
    single_url = args.url or None
    single_category = args.category or None

    if single_url and not single_category:
        logger.error("--url требует --category")
        sys.exit(1)

    if not any([args.all, args.priority, args.categories, args.parsers, args.url]):
        ap.print_help()
        sys.exit(0)

    # Фильтрация
    entries = filter_entries(
        all_entries,
        priority=priority,
        categories=categories,
        parsers=parsers,
        single_url=single_url,
        single_category=single_category,
    )

    logger.info(f"После фильтрации: {len(entries)} URL к обработке")

    if args.dry_run:
        logger.info("=== DRY-RUN: план выполнения ===")
        for idx, e in enumerate(entries, 1):
            logger.info(
                f"  {idx:3}. [{e.category_id}] {e.parser_class().__name__:<20} "
                f"P={e.priority} {e.url}"
            )
        logger.info(f"Итого: {len(entries)} URL (dry-run, реального парсинга нет)")
        return

    # Запуск
    output_dir = Path(args.output_dir)
    run_parsers(entries, output_dir=output_dir, no_cache=args.no_cache)


if __name__ == "__main__":
    main()
