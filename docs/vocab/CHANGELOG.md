# Vocab Module — История версий

## v17.24 (2026-03-06) — build_raw_dicts.py + clean_dicts.py ✅

### Добавлено
- `scripts/vocab/build_raw_dicts.py` — объединение всех parsed/{1..16}/*.txt в один файл
- `scripts/vocab/clean_dicts.py` — фильтрация мусора + дедупликация case-insensitive

### build_raw_dicts.py — ключевые решения
- Рекурсивный обход `data/parsed/*/*.txt` (все категории)
- Выход: один файл `data/raw_dicts/combined_all.txt` (вместо 13 файлов по категориям)
- Статистика: 327 файлов → 159,340 строк (без дедупликации)
- Логирование пустых файлов + детальная статистика по каждому

### clean_dicts.py — ключевые решения
- **6 слоёв фильтрации:**
  1. Длина: 3-100 символов
  2. Стоп-слова: местоимения, союзы, предлоги, наречия, Wikipedia-шаблоны (~150 слов)
  3. Префиксы предложений: глаголы прош. времени, наречия в начале строки
  4. **Фильтр родительного падежа:** "Германии было важно" → REJECT (12,222 строки)
  5. Паттерны: HTML, URL, даты, глаголы в середине строки
  6. Дедупликация case-insensitive с сохранением Title Case

### Результат
- **Вход:** 159,340 строк (raw)
- **Фильтрация:** 138,014 строк (отклонено 21,326)
  - Род. падеж: 12,222
  - Другое: 9,104
- **Дедупликация:** 85,904 уникальных термина (удалено 52,110 дублей)
- **Итоговое сокращение:** 46.1%

### Известные проблемы
- Остаётся мусор, не подпадающий под фильтры (предложения без глаголов/род. падежа)
- Решение: следующий этап — `load_vocab.py` с white-list паттернами + частотный фильтр

### Коммит
🔧 v17.24: ADD build_raw_dicts + clean_dicts [159K→86K terms] - объединение + фильтрация

---

## v17.23 (2026-03-06) — rkka_parser.py ✅

### Добавлено
- `scripts/vocab/parsers/rkka_parser.py` — двухуровневый crawler rkka.ru
- `tests/simulations/sim_rkka_parser.py` — 27/27 GREEN

### rkka_parser — ключевые решения
- Кодировка windows-1251 явно (не autodetect)
- Level 0: текст ссылок (названия операций) + заголовки разделов из <td>
- Level 1: таблицы + rank_names + unit_names + quoted_terms (импорт из militera_parser)
- _is_content_link(): фильтр по .htm/.html, без внешних доменов/якорей/CSS
- _clean_link_text(): фильтр кириллицы + стоп-слова начала строки
- MAX_PAGES=60, rate limit 2 сек/запрос
- Баги найденные в симуляции: _clean_link_text без проверки кириллицы (FIX), _extract_quoted_terms не вызывался (FIX)

### Real test результаты
- `http://rkka.ru/oper.htm` → 3486 терминов ✅

### Симуляция
- `tests/simulations/sim_rkka_parser.py` — 27/27 GREEN

## 2026-03-05

### FIX: wiki_parser._clean_term — строчная кириллица

**Проблема:**
- Регекс `[А-ЯA-Za-zёЁ]` содержал только заглавную кириллицу `А-Я`
- Строчная кириллица `а-я` отсутствовала → все строчные термины дропались как "строки без букв"
- Симптом: `militera_parser` возвращал только термины с заглавными буквами (Черноморский флот ✅, армия ❌)

**ROOT CAUSE:**
- Опечатка при написании character class — забыли `а-я`
- `militera_parser` импортирует `_clean_term` из `wiki_parser` → наследовал баг

**FIX:**

# БЫЛО:
if not re.search(r"[А-ЯA-Za-zёЁ]", t):
# СТАЛО:
if not re.search(r"[А-ЯЁа-яёA-Za-z]", t):

Тест:

sim_militera_parser.py: 53/53 GREEN

Real test: 3765 терминов извлечено (включая "армия", "корпус", "5-я армия")

Файлы:

scripts/vocab/parsers/wiki_parser.py (строка 113)

## v17.21 (2026-03-04) — wiki_parser.py ✅

### Добавлено
- `scripts/vocab/utils.py` — инфраструктура (rate limit, cache, retry)
- `scripts/vocab/parsers/__init__.py`
- `scripts/vocab/parsers/base_parser.py` — Template Method
- `scripts/vocab/parsers/wiki_parser.py` — Wikipedia ru+en

### wiki_parser — ключевые решения
- Три стратегии: wikitable → ul/li → h2/h3
- `_clean_term()`: убирает [[...]], сноски[1], скобки с рус. текстом
- `_normalize_caps()`: ЖУКОВ → Жуков, но ГДР/СССР ≤4 chr не трогать
- en.wikipedia:
  - Primary: кириллица из скобок "(Георгий Жуков)"
  - Secondary: латиница ТОЛЬКО техника/аббревиатуры (Panzer-IV, StuG)
  - Discard: транслитерации (Georgy Zhukov)
- `_is_useful_latin()`: фильтр латиницы (цифры + буквы, римские, не стоп-слова)

### Real test результаты
- `ru/Список_Маршалов_Советского_Союза` → 42 термина ✅
- `en/Marshal_of_the_Soviet_Union` → 0 (нет кириллицы — ожидаемо)
- `ru/Герой_Советского_Союза` → 61 ✅

### Симуляции
- `tests/simulations/sim_utils_base.py` — 14/14 GREEN
- `tests/simulations/sim_bug_wiki_parser.py` — 60/60 GREEN

### Документация
- `docs/vocab/README.md` — входная точка
- `docs/vocab/ARCHITECTURE.md` — структура, этапы 0-4
- `docs/vocab/PARSERS.md` — как писать парсеры
- `docs/vocab/URL_AUDIT.md` — работа с url_audit.csv
- `docs/vocab/WORKFLOW.md` — полный цикл URL → dict → Whisper

### Коммит
🔧 v17.21: ADD wiki_parser [real test 3 URLs] - Wikipedia ru+en parser

---

## v17.22 (planned) — militera_parser.py

### План
- Двухуровневый crawler (index.html + chapters)
- Level 0: автор + TOC (топонимы из названий глав)
- Level 1: 4 паттерна без NER (rank+name, quotes, units, cap-sequences)
- Real test: isaev_av3, rokossovsky → ~500 терминов/книга
- Симуляция: `sim_militera_parser.py`

---

## v17.23 (planned) — rkka_parser.py

### План
- Парсинг таблиц командиров, списков операций
- Real test: `rkka.ru/oper.htm`, `rkka.ru/hist/f.htm`

---

## v17.24 (planned) — run_all_parsers.py

### План
- Оркестратор: читает url_audit.csv → выбирает парсер → батч-парсинг
- CLI: `--all`, `--priority HIGH`, `--categories 1,5`, `--parsers wiki`
- Логирование: прогресс + ошибки

---

## Backlog

- [ ] `iremember_parser.py` (воспоминания ветеранов)
- [ ] `api_parser.py` (pamyat-naroda, podvignaroda, rate 0.5 req/s)
- [ ] `pdf_parser.py` (PyMuPDF для PDF-словарей)
- [ ] `build_raw_dicts.py` (Этап 2)
- [ ] `clean_dicts.py` (Этап 3)
- [ ] `load_vocab.py` (Этап 4A)
- [ ] `correct.py` (Этап 4B, 4-слойная постобработка)

---

**Последнее обновление:** 2026-03-04