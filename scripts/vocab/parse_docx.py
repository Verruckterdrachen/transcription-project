#!/usr/bin/env python3
"""
scripts/vocab/parse_docx.py
Этап 0: Разбор .docx с URL-базой ВОВ/ВМВ и HEAD-аудит всех ссылок.

Запуск:
    python scripts/vocab/parse_docx.py --input WWII_links_all.docx
    python scripts/vocab/parse_docx.py --input WWII_links_all.docx --output data/dictionaries/url_audit.csv
    python scripts/vocab/parse_docx.py --input WWII_links_all.docx --workers 20 --timeout 8
"""

from __future__ import annotations

import argparse
import csv
import logging
import re
import time
from collections import defaultdict
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path
from threading import Lock
from urllib.parse import urlparse

import requests
from docx import Document
from tenacity import retry, stop_after_attempt, wait_exponential
from tqdm import tqdm

# ─────────────────────────────────────────────
# КОНФИГУРАЦИЯ
# ─────────────────────────────────────────────

LOG_FILE = "vocab_parser.log"

# Домены с HIGH/MED/LOW приоритетом
PRIORITY_HIGH = {
    "pamyat-naroda.ru",
    "podvignaroda.ru",
    "obd-memorial.ru",
    "militera.lib.ru",
    "rkka.ru",
    "iremember.ru",
}
PRIORITY_MED = {
    "ru.wikipedia.org",
    "en.wikipedia.org",
    "warspot.ru",
    "histrf.ru",
    "armedman.ru",
}

# Домены, требующие JS (selenium)
JS_DOMAINS = {
    "warspot.ru",
    "waralbum.ru",
    "allaces.ru",
}

# Домены с REST API
API_DOMAINS = {
    "pamyat-naroda.ru",
    "podvignaroda.ru",
}

# Домены, которые всегда → manual (авторизация / captcha)
MANUAL_DOMAINS = {
    "t.me",
    "telegram.me",
}

# Паттерн для шаблонных URL (не проверяем HEAD)
TEMPLATE_PATTERN = re.compile(r"[\$\{]")

# Паттерн для извлечения URL из текста
URL_PATTERN = re.compile(r"https?://[^\s\]>\"\'<\)]+")

# Паттерн для определения категории из заголовка
CATEGORY_PATTERN = re.compile(
    r"КАТЕГОРИЯ\s+(\d+[бБ]?)\s*[:\-–—]?\s*(.+)", re.IGNORECASE
)

USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/122.0.0.0 Safari/537.36"
)

# ─────────────────────────────────────────────
# ЛОГИРОВАНИЕ
# ─────────────────────────────────────────────

def setup_logging() -> logging.Logger:
    logger = logging.getLogger("parse_docx")
    logger.setLevel(logging.INFO)
    fmt = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s", "%H:%M:%S")

    # Файл
    fh = logging.FileHandler(LOG_FILE, encoding="utf-8")
    fh.setFormatter(fmt)
    logger.addHandler(fh)

    # Консоль
    ch = logging.StreamHandler()
    ch.setFormatter(fmt)
    logger.addHandler(ch)

    return logger


logger = setup_logging()

# ─────────────────────────────────────────────
# ПАРСИНГ .DOCX
# ─────────────────────────────────────────────

def _clean_text(text: str) -> str:
    """Убираем лишние пробелы и нулевые символы."""
    return re.sub(r"\s+", " ", text).strip()


def _detect_category(text: str) -> tuple[str, str] | None:
    """
    Возвращает (category_id, category_name) если строка — заголовок категории.
    Пример: 'КАТЕГОРИЯ 3б: ФОРМА, ОБМУНДИРОВАНИЕ...' → ('3б', 'ФОРМА, ОБМУНДИРОВАНИЕ...')
    """
    m = CATEGORY_PATTERN.search(text)
    if m:
        cat_id = m.group(1).strip().upper()
        cat_name = _clean_text(m.group(2))
        # Обрезаем мусор после имени (описание через ---)
        cat_name = cat_name.split("---")[0].split("—")[0].strip().rstrip(".")
        return cat_id, cat_name
    return None


def _extract_urls_from_text(text: str) -> list[str]:
    """Извлекаем URL из сырого текста параграфа."""
    urls = URL_PATTERN.findall(text)
    # Чистим хвостовые знаки препинания
    cleaned = []
    for url in urls:
        url = url.rstrip(".,;:!?)\"'\\")
        if url:
            cleaned.append(url)
    return cleaned


def extract_urls_from_docx(docx_path: Path) -> list[dict]:
    """
    Читает .docx, возвращает список записей:
    [{"category_id": str, "category_name": str, "url": str, "is_template": bool}, ...]
    """
    doc = Document(str(docx_path))
    records: list[dict] = []

    current_cat_id = "UNKNOWN"
    current_cat_name = "Unknown"

    # Используем set для дедупликации URL внутри категории
    seen_urls: set[str] = set()

    for para in doc.paragraphs:
        raw = _clean_text(para.text)
        if not raw:
            continue

        # 1. Проверяем: это заголовок категории?
        cat = _detect_category(raw)
        if cat:
            current_cat_id, current_cat_name = cat
            seen_urls = set()  # сбрасываем дедупликацию для новой категории
            logger.info(f"  Категория {current_cat_id}: {current_cat_name}")
            continue

        # 2. Извлекаем URL из текста параграфа
        urls_in_para = _extract_urls_from_text(raw)

        for url in urls_in_para:
            if url in seen_urls:
                continue
            seen_urls.add(url)
            is_template = bool(TEMPLATE_PATTERN.search(url))
            records.append({
                "category_id": current_cat_id,
                "category_name": current_cat_name,
                "url": url,
                "is_template": is_template,
            })

    logger.info(f"Извлечено записей из .docx: {len(records)}")
    return records


# ─────────────────────────────────────────────
# ОПРЕДЕЛЕНИЕ ПРИОРИТЕТА И МЕТОДА ПАРСИНГА
# ─────────────────────────────────────────────

def get_domain(url: str) -> str:
    try:
        return urlparse(url).netloc.lower().lstrip("www.")
    except Exception:
        return ""


def get_priority(domain: str) -> str:
    if domain in PRIORITY_HIGH:
        return "HIGH"
    if domain in PRIORITY_MED:
        return "MED"
    return "LOW"


def determine_parseable(
    domain: str,
    status_code: int | None,
    content_type: str,
    is_template: bool,
) -> str:
    """Определяет метод парсинга по набору признаков."""
    if is_template:
        return "manual"
    if domain in MANUAL_DOMAINS:
        return "manual"
    if domain in API_DOMAINS:
        return "api"
    if status_code is None:
        return "dead"
    if status_code in (404, 410):
        return "dead"
    if status_code in (401, 403):
        return "manual"
    if status_code >= 500:
        return "dead"
    if "application/pdf" in content_type:
        return "pymupdf"
    if domain in JS_DOMAINS:
        return "selenium"
    if status_code == 200 and "text/html" in content_type:
        return "requests+bs4"
    # 200 но content-type неизвестный
    if status_code == 200:
        return "requests+bs4"
    return "manual"


# ─────────────────────────────────────────────
# HEAD-АУДИТ С RATE LIMITING
# ─────────────────────────────────────────────

class DomainRateLimiter:
    """Per-domain rate limiter: не более 1 запроса в секунду на домен."""

    def __init__(self, min_interval: float = 1.0):
        self._last_call: dict[str, float] = {}
        self._lock = Lock()
        self._min_interval = min_interval

    def wait(self, domain: str) -> None:
        with self._lock:
            now = time.monotonic()
            last = self._last_call.get(domain, 0.0)
            delta = now - last
            if delta < self._min_interval:
                time.sleep(self._min_interval - delta)
            self._last_call[domain] = time.monotonic()


_rate_limiter = DomainRateLimiter(min_interval=1.0)


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=16),
    reraise=False,
)
def _head_request(url: str, timeout: int) -> requests.Response:
    """HEAD-запрос с retry через tenacity."""
    headers = {"User-Agent": USER_AGENT}
    resp = requests.head(
        url,
        timeout=timeout,
        allow_redirects=True,
        headers=headers,
    )
    return resp


def audit_url(record: dict, timeout: int) -> dict:
    """
    Проверяет один URL через HEAD.
    Возвращает дополненный record с полями аудита.
    """
    url = record["url"]
    domain = get_domain(url)
    is_template = record["is_template"]

    status_code: int | None = None
    content_type = ""
    notes = ""

    # Шаблонные URL и Telegram — не проверяем
    if is_template:
        notes = "template URL — HEAD skipped"
        parseable = "manual"
    elif domain in MANUAL_DOMAINS:
        notes = "Telegram/manual — HEAD skipped"
        parseable = "manual"
    else:
        try:
            _rate_limiter.wait(domain)
            resp = _head_request(url, timeout)
            status_code = resp.status_code
            content_type = resp.headers.get("Content-Type", "").split(";")[0].strip()

            # Некоторые сервера не отвечают на HEAD, пробуем GET с stream
            if status_code in (405, 501):
                _rate_limiter.wait(domain)
                resp2 = requests.get(
                    url,
                    timeout=timeout,
                    allow_redirects=True,
                    headers={"User-Agent": USER_AGENT},
                    stream=True,
                )
                resp2.close()
                status_code = resp2.status_code
                content_type = resp2.headers.get("Content-Type", "").split(";")[0].strip()
                notes = "HEAD→405, fallback GET"

        except requests.exceptions.Timeout:
            notes = "timeout"
        except requests.exceptions.ConnectionError as e:
            notes = f"connection error: {str(e)[:60]}"
        except Exception as e:
            notes = f"error: {str(e)[:60]}"

        parseable = determine_parseable(domain, status_code, content_type, is_template)

    priority = get_priority(domain)

    return {
        "category_id": record["category_id"],
        "category_name": record["category_name"],
        "url": url,
        "status_code": status_code if status_code is not None else "",
        "content_type": content_type,
        "parseable": parseable,
        "priority": priority,
        "notes": notes,
    }


def run_audit(
    records: list[dict],
    timeout: int,
    max_workers: int,
) -> list[dict]:
    """Параллельный HEAD-аудит всех URL через ThreadPoolExecutor."""
    results: list[dict] = []

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_record = {
            executor.submit(audit_url, rec, timeout): rec
            for rec in records
        }

        with tqdm(total=len(records), desc="HEAD audit", unit="url") as pbar:
            for future in as_completed(future_to_record):
                try:
                    result = future.result()
                    results.append(result)
                except Exception as e:
                    rec = future_to_record[future]
                    logger.error(f"Unhandled error for {rec['url']}: {e}")
                    results.append({
                        "category_id": rec["category_id"],
                        "category_name": rec["category_name"],
                        "url": rec["url"],
                        "status_code": "",
                        "content_type": "",
                        "parseable": "dead",
                        "priority": get_priority(get_domain(rec["url"])),
                        "notes": f"unhandled: {str(e)[:60]}",
                    })
                pbar.update(1)

    # Восстанавливаем исходный порядок (category_id, url)
    order = {(r["category_id"], r["url"]): i for i, r in enumerate(records)}
    results.sort(key=lambda r: order.get((r["category_id"], r["url"]), 9999))

    return results


# ─────────────────────────────────────────────
# СОХРАНЕНИЕ CSV
# ─────────────────────────────────────────────

CSV_FIELDS = [
    "category_id",
    "category_name",
    "url",
    "status_code",
    "content_type",
    "parseable",
    "priority",
    "notes",
]


def save_csv(results: list[dict], output_path: Path) -> None:
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with open(output_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(results)
    logger.info(f"CSV сохранён: {output_path}")


# ─────────────────────────────────────────────
# ИТОГОВАЯ СВОДКА
# ─────────────────────────────────────────────

def print_summary(results: list[dict]) -> None:
    total = len(results)

    # По статусу
    status_counts: dict[str, int] = defaultdict(int)
    for r in results:
        sc = r["status_code"]
        if sc == "":
            key = "timeout/error"
        elif int(sc) == 200:
            key = "200"
        elif int(sc) == 404:
            key = "404"
        elif int(sc) in (301, 302, 307, 308):
            key = f"redirect({sc})"
        else:
            key = str(sc)
        status_counts[key] += 1

    # По методу парсинга
    parse_counts: dict[str, int] = defaultdict(int)
    for r in results:
        parse_counts[r["parseable"]] += 1

    # По категориям
    cat_counts: dict[str, int] = defaultdict(int)
    for r in results:
        cat_counts[r["category_id"]] += 1

    # По приоритетам
    prio_counts: dict[str, int] = defaultdict(int)
    for r in results:
        prio_counts[r["priority"]] += 1

    sep = "─" * 56
    print(f"\n{sep}")
    print(f"  ИТОГИ АУДИТА URL — WWII HOTWORDS BASE v2.0")
    print(sep)
    print(f"  Всего URL проверено : {total}")

    print(f"\n  📊 По HTTP-статусу:")
    for k, v in sorted(status_counts.items()):
        bar = "█" * min(v, 30)
        print(f"    {k:>15}  {v:>4}  {bar}")

    print(f"\n  🔧 По методу парсинга:")
    method_labels = {
        "requests+bs4": "requests+bs4 (статич. HTML)",
        "selenium":     "selenium     (JS-рендеринг)",
        "pymupdf":      "pymupdf      (PDF)",
        "api":          "api          (REST API)",
        "manual":       "manual       (авторизация/капча/шаблон)",
        "dead":         "dead         (404/timeout/error)",
    }
    for k in ["requests+bs4", "selenium", "pymupdf", "api", "manual", "dead"]:
        v = parse_counts.get(k, 0)
        label = method_labels.get(k, k)
        icon = "✅" if k not in ("dead", "manual") else ("❌" if k == "dead" else "⚠️")
        print(f"    {icon}  {label:<42}  {v:>4}")

    print(f"\n  ⭐ По приоритету:")
    for k in ["HIGH", "MED", "LOW"]:
        v = prio_counts.get(k, 0)
        stars = {"HIGH": "★★★", "MED": "★★ ", "LOW": "★  "}[k]
        print(f"    {stars}  {k:<6}  {v:>4}")

    print(f"\n  📁 По категориям:")
    print(f"    {'Кат':>5}  {'URL':>5}  {'requests':>9}  {'api':>4}  {'dead':>5}  {'manual':>7}")
    print(f"    {'':>5}  {'─'*5}  {'─'*9}  {'─'*4}  {'─'*5}  {'─'*7}")

    for cat_id in sorted(cat_counts.keys(), key=lambda x: x.replace("Б", "b").replace("б", "b")):
        cat_results = [r for r in results if r["category_id"] == cat_id]
        n_req = sum(1 for r in cat_results if r["parseable"] == "requests+bs4")
        n_api = sum(1 for r in cat_results if r["parseable"] == "api")
        n_dead = sum(1 for r in cat_results if r["parseable"] == "dead")
        n_manual = sum(1 for r in cat_results if r["parseable"] == "manual")
        total_cat = len(cat_results)
        print(f"    {cat_id:>5}  {total_cat:>5}  {n_req:>9}  {n_api:>4}  {n_dead:>5}  {n_manual:>7}")

    print(sep)

    # Финальная строка статистики
    dead = parse_counts.get("dead", 0)
    manual = parse_counts.get("manual", 0)
    parseable = total - dead - manual
    flagged = manual

    print(f"\n  ✅ Доступно для парсинга  : {parseable}")
    print(f"  ⚠️  Требуют ручной проверки: {flagged}")
    print(f"  ❌ Недоступны (dead)       : {dead}")
    print(f"{sep}\n")


# ─────────────────────────────────────────────
# ТОЧКА ВХОДА
# ─────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Этап 0: Разбор .docx с URL-базой ВОВ/ВМВ и HEAD-аудит"
    )
    parser.add_argument(
        "--input", "-i",
        required=True,
        type=Path,
        help="Путь к .docx файлу (например: WWII_links_all.docx)",
    )
    parser.add_argument(
        "--output", "-o",
        type=Path,
        default=Path("data/dictionaries/url_audit.csv"),
        help="Путь для сохранения CSV (по умолчанию: data/dictionaries/url_audit.csv)",
    )
    parser.add_argument(
        "--workers", "-w",
        type=int,
        default=10,
        help="Количество потоков для HEAD-запросов (по умолчанию: 10)",
    )
    parser.add_argument(
        "--timeout", "-t",
        type=int,
        default=5,
        help="Timeout HEAD-запроса в секундах (по умолчанию: 5)",
    )
    parser.add_argument(
        "--no-audit",
        action="store_true",
        help="Только извлечь URL без HEAD-проверки (быстро, для отладки)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()

    logger.info("=" * 56)
    logger.info("parse_docx.py — старт")
    logger.info(f"  Input  : {args.input}")
    logger.info(f"  Output : {args.output}")
    logger.info(f"  Workers: {args.workers}")
    logger.info(f"  Timeout: {args.timeout}s")

    # 1. Проверяем входной файл
    if not args.input.exists():
        logger.error(f"Файл не найден: {args.input}")
        raise SystemExit(1)

    # 2. Извлекаем URL из .docx
    logger.info("Шаг 1/3: Извлечение URL из .docx...")
    records = extract_urls_from_docx(args.input)

    if not records:
        logger.error("URL не найдены в документе. Проверьте структуру .docx.")
        raise SystemExit(1)

    logger.info(f"Найдено URL: {len(records)} "
                f"(шаблонных: {sum(1 for r in records if r['is_template'])})")

    # 3. HEAD-аудит (или пропускаем)
    if args.no_audit:
        logger.info("Шаг 2/3: HEAD-аудит ПРОПУЩЕН (--no-audit)")
        results = []
        for rec in records:
            domain = get_domain(rec["url"])
            results.append({
                "category_id": rec["category_id"],
                "category_name": rec["category_name"],
                "url": rec["url"],
                "status_code": "",
                "content_type": "",
                "parseable": "manual" if rec["is_template"] else "unknown",
                "priority": get_priority(domain),
                "notes": "audit skipped",
            })
    else:
        logger.info(f"Шаг 2/3: HEAD-аудит {len(records)} URL "
                    f"(workers={args.workers}, timeout={args.timeout}s)...")
        results = run_audit(records, timeout=args.timeout, max_workers=args.workers)

    # 4. Сохраняем CSV
    logger.info(f"Шаг 3/3: Сохранение CSV → {args.output}")
    save_csv(results, args.output)

    # 5. Итоговая сводка
    print_summary(results)

    logger.info("parse_docx.py — завершён успешно")


if __name__ == "__main__":
    main()
