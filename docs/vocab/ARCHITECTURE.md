# Vocab Module — Архитектура

## 🗂️ Структура модуля

scripts/vocab/
├── parse_docx.py # Этап 0: извлечение из DOCX (готов)
├── utils.py # инфраструктура (rate limit, cache, retry)
├── parsers/
│ ├── init.py
│ ├── base_parser.py # абстрактный BaseParser (Template Method)
│ ├── wiki_parser.py # Wikipedia ru+en (готов v17.21)
│ ├── militera_parser.py # militera.lib.ru (в разработке v17.22)
│ ├── rkka_parser.py
│ ├── iremember_parser.py
│ ├── warspot_parser.py
│ ├── pdf_parser.py # PyMuPDF для PDF-словарей
│ ├── api_parser.py # pamyat-naroda, podvignaroda (rate 0.5 req/s!)
│ └── generic_parser.py # fallback для простых сайтов
├── run_all_parsers.py # оркестратор (читает url_audit.csv)
├── build_raw_dicts.py # Этап 2: объединение parsed/ → raw_dicts/
├── clean_dicts.py # Этап 3: дедупликация, нормализация
└── load_vocab.py # Этап 4A: hotwords для Whisper

text

---

## 🔄 Этапы обработки

### Этап 0: Парсинг источников → `data/parsed/`

**Вход:** URL из `url_audit.csv`  
**Выход:** `data/parsed/{category_id}/{domain}.txt`

Каждый парсер:
1. Фетчит HTML/API (через `fetch_with_retry` + cache TTL 7 дней)
2. Извлекает термины (стратегии зависят от домена)
3. Нормализует (`_clean_term`, `_normalize_caps`)
4. Дедуплицирует (`_dedupe_ordered`, case-insensitive)
5. Сохраняет: 1 термин = 1 строка

**Структура:**
data/parsed/
├── 1/ ← СОВЕТСКИЕ КОМАНДИРЫ
│ ├── ru_wikipedia_org.txt
│ ├── militera_lib_ru.txt
│ └── rkka_ru.txt
├── 5/ ← ОПЕРАЦИИ
│ └── ru_wikipedia_org.txt
└── 7/ ← ТОПОНИМЫ
└── ru_wikipedia_org.txt

text

---

### Этап 1: (резерв — пока не используется)

---

### Этап 2: Объединение → `data/raw_dicts/`

**Вход:** `data/parsed/{1..13}/*.txt`  
**Выход:** `data/raw_dicts/base_*.txt` (13 файлов)

```bash
python scripts/vocab/build_raw_dicts.py
Логика:

Объединяет все parsed/{category}/ в один файл

Маппинг категорий → имена словарей (см. URL_AUDIT.md)

Сохраняет дубли между доменами (удалятся на этапе 3)

Пример:

text
data/raw_dicts/
├── base_ussr_commanders.txt    ← из категорий 1
├── base_operations.txt         ← из категорий 5
└── base_toponyms.txt           ← из категорий 7
Этап 3: Очистка → data/final_dicts/
Вход: data/raw_dicts/*.txt
Выход: data/final_dicts/*.txt

bash
python scripts/vocab/clean_dicts.py
Логика:

Case-insensitive дедупликация (сохраняет вариант с большими буквами)

Убирает короткие термины (< 3 символа)

Нормализует пробелы, убирает спецсимволы

Фильтрует стоп-слова (служебные: "Глава", "Часть", "Примечания")

Сортирует по частоте (если термин встречался в >1 источнике → приоритет)

Итог:

text
data/final_dicts/
├── base_ussr_commanders.txt    ← 200–300 уникальных ФИО
├── base_operations.txt         ← 100–150 операций
└── base_toponyms.txt           ← 150–200 топонимов
Этап 4A: Hotwords для Whisper
Вход: data/final_dicts/*.txt
Выход: data/hotwords/combined_vocab.txt

bash
python scripts/vocab/load_vocab.py
Логика:

Объединяет все final_dicts в один файл

Добавляет веса (частотность → boost для Whisper)

Формат: 1 термин = 1 строка, сортировка по весу

Использование:

python
# В scripts/transcribe.py
hotwords = load_hotwords("data/hotwords/combined_vocab.txt")
whisper_model.transcribe(audio, hotwords=hotwords)
Этап 4B: Постобработка транскрипции
См. scripts/corrections/correct.py (4-слойная коррекция терминов в уже готовой транскрипции).

🔧 Инфраструктура (utils.py)
Rate Limiting
python
from scripts.vocab.utils import get_default_rate_limiter

limiter = get_default_rate_limiter()
limiter.wait("militera.lib.ru")  # 2 сек между запросами к одному домену
Правила:

Wikipedia: 1 req/sec (по умолчанию)

militera, rkka, iremember: 2 sec/req (вежливость)

pamyat-naroda API: 0.5 req/sec (документация API)

Caching
python
from scripts.vocab.utils import get_cached, save_cache

html = get_cached(url)  # → str | None
if html is None:
    html = fetch_with_retry(session, url)
    save_cache(url, html)  # TTL 7 дней
Хранение: data/cache/{domain}/{md5(url)}.html

Очистка:

bash
find data/cache -type f -mtime +7 -delete  # удалить старше 7 дней
Retry Logic
python
from scripts.vocab.utils import fetch_with_retry

html = fetch_with_retry(
    session,
    url,
    max_retries=3,       # tenacity: 3 попытки
    backoff_factor=1.0   # 1 → 4 → 16 секунд
)
📊 Ожидаемые объёмы
Этап	Терминов	Файлов
parsed/ (после парсинга всех 138 URL)	~3000–4000	50–70
raw_dicts/ (после объединения)	~2500–3500	13
final_dicts/ (после дедупликации)	~2000–2700	13
hotwords/ (финал для Whisper)	~2000–2700	1
Версия: v17.21
Последнее обновление: 2026-03-04