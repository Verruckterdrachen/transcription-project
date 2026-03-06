Вот полностью обновлённый WORKFLOW.md:

text
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
data/raw_dicts/combined_all.txt ← Этап 2
↓
clean_dicts.py
↓
data/final_dicts/combined_all.txt ← Этап 3
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

5. Объединить в сырой словарь
bash
python scripts/vocab/build_raw_dicts.py
Что делает:

Рекурсивно читает все data/parsed/{1..16}/*.txt

Объединяет в один файл (без категоризации)

Сохраняет дубли между доменами (удалятся на этапе 3)

Логирует пустые файлы + детальную статистику

Результат:

text
data/raw_dicts/combined_all.txt  ← 159,340 строк (с дублями между доменами)
Проверка:

bash
wc -l data/raw_dicts/combined_all.txt
head -50 data/raw_dicts/combined_all.txt
Ожидаемо: 150,000–200,000 строк (зависит от кол-ва распарсенных URL).

6. Очистить и дедуплицировать
bash
python scripts/vocab/clean_dicts.py
Что делает (6 слоёв фильтрации):

Длина: 3-100 символов

Стоп-слова: местоимения, союзы, предлоги, наречия, Wikipedia-шаблоны (~150 слов)

Префиксы предложений: глаголы прош. времени ("был", "начал"), наречия ("только", "уже")

Родительный падеж: "Германии было важно" → REJECT (окончания: -ии, -ей, -ов, -ям)

Паттерны: HTML, URL, даты, глаголы в середине строки (regex)

Дедупликация: case-insensitive с сохранением Title Case

Результат:

text
data/final_dicts/combined_all.txt  ← 85,904 уникальных термина (46% сокращение)
Проверка:

bash
wc -l data/final_dicts/combined_all.txt
head -100 data/final_dicts/combined_all.txt

# Проверка важных терминов
grep -i 'цитадель' data/final_dicts/combined_all.txt
grep -i 'багратион' data/final_dicts/combined_all.txt
grep -i 'днепр' data/final_dicts/combined_all.txt

# Проверка дублей (должно быть пусто)
sort -f data/final_dicts/combined_all.txt | uniq -di
Статистика (пример):

text
Входных терминов:        159,340
После фильтрации:        138,014
После дедупликации:      85,904
Отклонено (общее):       21,326
  - род. падеж:          12,222
  - другое:              9,104
Дубликатов удалено:      52,110
Итоговое сокращение:     46.1%
Ожидаемо: ~80,000–100,000 уникальных терминов.

7. Собрать hotwords для Whisper
bash
python scripts/vocab/load_vocab.py
Что делает:

Читает data/final_dicts/combined_all.txt

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
# Первые 100 терминов
head -100 data/final_dicts/combined_all.txt

# Случайная выборка
shuf -n 50 data/final_dicts/combined_all.txt

# Поиск конкретного термина
grep -i "жуков" data/final_dicts/combined_all.txt
3. Дубли (не должно быть после clean)
bash
sort -f data/final_dicts/combined_all.txt | uniq -di
Ожидаемо: пустой вывод.

4. Мусор
bash
# Короткие термины (< 3 chr)
awk 'length($0) < 3' data/final_dicts/*.txt

# Только цифры
grep -E '^[0-9]+$' data/final_dicts/*.txt

# HTML-теги
grep -E '<[^>]+>' data/final_dicts/*.txt

# Предложения (>80 символов)
awk 'length($0) > 80' data/final_dicts/*.txt | head -20

# Родительный падеж в начале строки
grep -E '^[А-ЯЁ][а-яё]+(ии|ей|ов|ям) ' data/final_dicts/*.txt | head -20
Ожидаемо: пустой вывод или минимальное кол-во строк.

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

4. Много мусора после clean_dicts.py
Симптом: в final_dicts/ остались предложения, фрагменты текста.

Решение:

Проверь образцы: shuf -n 50 data/final_dicts/combined_all.txt

Если мусора >20% — добавь фильтры в clean_dicts.py (STOPWORDS, PATTERNS_TO_REJECT)

Или используй load_vocab.py с white-list паттернами (следующий этап)

5. Rate limit 429 Too Many Requests
Причина: слишком быстрый парсинг.

Решение: увеличить интервал в utils.py:

python
RATE_LIMITS = {
    "wikipedia.org": 2.0,  # было 1.0
    "militera.lib.ru": 3.0,  # было 2.0
}
📈 Ожидаемые объёмы данных
Этап	Файл	Объём (строк)	Качество
0. Парсинг	data/parsed/*/*.txt	150,000–200,000	⭐ (много мусора)
2. Объединение	data/raw_dicts/combined_all.txt	150,000–200,000	⭐ (дубли + мусор)
3. Очистка	data/final_dicts/combined_all.txt	80,000–100,000	⭐⭐⭐ (чисто, но есть мусор)
4A. Hotwords	data/hotwords/combined_vocab.txt	80,000–100,000	⭐⭐⭐ (для Whisper)
Версия: v17.24
Последнее обновление: 2026-03-06