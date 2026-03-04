# Vocab Module — Полный цикл работы

## 🔄 Workflow: От URL до Whisper

URL в url_audit.csv
↓
Парсер (wiki/militera/rkka...)
↓
data/parsed/{category}/{domain}.txt ← Этап 0
↓
build_raw_dicts.py
↓
data/raw_dicts/base_.txt ← Этап 2
↓
clean_dicts.py
↓
data/final_dicts/base_.txt ← Этап 3
↓
load_vocab.py
↓
data/hotwords/combined_vocab.txt ← Этап 4A (для Whisper)
↓
scripts/transcribe.py (использует hotwords)
↓
scripts/corrections/correct.py ← Этап 4B (постобработка)

text

---

## 📋 Шаг за шагом

### 1. Добавить URL в url_audit.csv

```csv
5,ОПЕРАЦИИ И СРАЖЕНИЯ,https://ru.wikipedia.org/wiki/Операция_Багратион,200,text/html,requests+bs4,HIGH,
См. URL_AUDIT.md для деталей.

2. Запустить парсер (один URL — тест)
bash
python scripts/vocab/parsers/wiki_parser.py \
    --url "https://ru.wikipedia.org/wiki/Операция_Багратион" \
    --category 5 \
    --output-dir data/parsed
Результат:

text
data/parsed/5/ru_wikipedia_org.txt
Содержимое (пример):

text
Операция Багратион
Белорусская операция
1-й Белорусский фронт
Рокоссовский
Жуков
группа армий Центр
...
Проверка:

bash
wc -l data/parsed/5/ru_wikipedia_org.txt
cat data/parsed/5/ru_wikipedia_org.txt | head -20
Ожидаемо: 40–100 строк, нет мусора (HTML, цифр, служебных слов).

3. Запустить парсер (все URL одной категории)
bash
python scripts/vocab/run_all_parsers.py --categories 5
Что делает:

Читает url_audit.csv

Фильтрует строки: category_id=5 AND parseable NOT IN ('dead','manual')

Для каждого URL:

Определяет парсер по домену (wikipedia → wiki_parser)

Вызывает parser.run()

Сохраняет в data/parsed/5/{domain}.txt

Логирует прогресс + ошибки

Время: ~5–10 минут (зависит от кол-ва URL × rate limit).

4. Запустить парсер (ВСЕ живые URL)
bash
python scripts/vocab/run_all_parsers.py --all
Фильтр: parseable NOT IN ('dead', 'manual')
Итого: 138 URL
Время: ~20–25 минут

Или только HIGH-priority:

bash
python scripts/vocab/run_all_parsers.py --priority HIGH
58 URL, ~12 минут.

5. Объединить в сырые словари
bash
python scripts/vocab/build_raw_dicts.py
Что делает:

Читает все data/parsed/{1..13}/*.txt

Объединяет файлы одной категории

Сохраняет в data/raw_dicts/base_*.txt

Маппинг: см. таблицу в URL_AUDIT.md.

Результат:

text
data/raw_dicts/
├── base_ussr_commanders.txt    ← категория 1
├── base_operations.txt         ← категория 5
├── base_toponyms.txt           ← категория 7
...
Проверка:

bash
wc -l data/raw_dicts/*.txt
Ожидаемо: 2500–3500 строк (с дублями между доменами).

6. Очистить и дедуплицировать
bash
python scripts/vocab/clean_dicts.py
Что делает:

Case-insensitive дедупликация (сохраняет вариант с большими буквами)

Убирает короткие термины (< 3 символа)

Фильтрует стоп-слова ("Глава", "Часть", "Раздел")

Нормализует пробелы

Сортирует по частоте (термины из >1 источника → приоритет)

Результат:

text
data/final_dicts/
├── base_ussr_commanders.txt    ← 200–300 уникальных
├── base_operations.txt         ← 100–150
├── base_toponyms.txt           ← 150–200
...
Проверка:

bash
wc -l data/final_dicts/*.txt
diff data/raw_dicts/base_ussr_commanders.txt data/final_dicts/base_ussr_commanders.txt | head
Ожидаемо: ~20–30% сокращение (дедупликация).

7. Собрать hotwords для Whisper
bash
python scripts/vocab/load_vocab.py
Что делает:

Читает все data/final_dicts/*.txt

Объединяет в один файл

Добавляет веса (частотность → boost)

Сохраняет в data/hotwords/combined_vocab.txt

Формат:

text
Жуков:5
Рокоссовский:4
Операция Багратион:3
1-й Белорусский фронт:2
...
Использование в транскрипции:

python
# scripts/transcribe.py
hotwords = load_hotwords("data/hotwords/combined_vocab.txt")
result = whisper_model.transcribe(audio, hotwords=hotwords)
8. (Опционально) Постобработка транскрипции
После того как транскрипция готова, запускается 4-слойная коррекция:

bash
python scripts/corrections/correct.py \
    --input test-results/latest/json/ \
    --dicts data/final_dicts/
4 слоя:

Exact match (без учёта регистра)

Fuzzy match (Levenshtein distance ≤ 2)

Phonetic match (русский soundex)

Context-aware (биграммы, титулы + имена)

См. scripts/corrections/correct.py для деталей.

🔁 Обновление словарей (при добавлении новых URL)
Быстрый путь (только новые URL)
bash
# 1. Добавь URL в url_audit.csv
# 2. Парсинг только этого URL
python scripts/vocab/parsers/wiki_parser.py \
    --url "https://..." --category X

# 3. Пересборка словарей
python scripts/vocab/build_raw_dicts.py
python scripts/vocab/clean_dicts.py
python scripts/vocab/load_vocab.py
Время: 2–3 минуты.

Полный путь (переспарсить всё)
bash
# 1. Удали кэш (если нужны свежие данные)
rm -rf data/cache/

# 2. Переспарсить всё
python scripts/vocab/run_all_parsers.py --all

# 3. Пересборка
python scripts/vocab/build_raw_dicts.py
python scripts/vocab/clean_dicts.py
python scripts/vocab/load_vocab.py
Время: ~25 минут (парсинг) + 2 минуты (сборка).

📊 Проверка качества
1. Кол-во терминов
bash
wc -l data/parsed/*/*.txt      # после парсинга
wc -l data/raw_dicts/*.txt     # после объединения
wc -l data/final_dicts/*.txt   # после очистки
2. Образцы терминов
bash
# Первые 20 терминов из категории КОМАНДИРЫ
head -20 data/final_dicts/base_ussr_commanders.txt

# Поиск конкретного термина
grep -i "жуков" data/final_dicts/base_ussr_commanders.txt
3. Дубли (не должно быть после clean)
bash
sort data/final_dicts/base_ussr_commanders.txt | uniq -d
Ожидаемо: пустой вывод.

4. Мусор
bash
# Короткие термины (< 3 chr)
awk 'length($0) < 3' data/final_dicts/*.txt

# Цифры
grep -E '^[0-9]+$' data/final_dicts/*.txt

# HTML-теги
grep -E '<[^>]+>' data/final_dicts/*.txt
Ожидаемо: пустой вывод.

🚨 Частые проблемы
1. Парсер падает с SSL error
Причина: самоподписанный сертификат (militera, rkka).

Решение: в utils.py уже есть verify=False для этих доменов.

2. Парсер возвращает 0 терминов
Причина: изменилась структура HTML.

Решение:

Фетчнуть HTML вручную: curl "URL" > test.html

Открыть в браузере, найти CSS-селекторы

Обновить стратегии в парсере

3. Дубли между доменами
Симптом: "Жуков" встречается в 5 файлах parsed/1/.

Решение: это нормально, clean_dicts.py удалит дубли на этапе 3.

4. Rate limit 429 Too Many Requests
Причина: слишком быстрый парсинг.

Решение: увеличить интервал в utils.py:

python
RATE_LIMITS = {
    "wikipedia.org": 2.0,  # было 1.0
    "militera.lib.ru": 3.0,  # было 2.0
}
Версия: v17.21
Последнее обновление: 2026-03-04