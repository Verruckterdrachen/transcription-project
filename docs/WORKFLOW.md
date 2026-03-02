# WORKFLOW.md — Процесс работы
# Обновлено: 2026-02-20

Единственный источник правды о том, как мы работаем.
Без unit-тестов. Только реальное аудио, логи, golden-dataset.

---

## 5 ПРАВИЛ (соблюдать всегда)

**#1 BASELINE AUDIO**
Каждый фикс тестируется на реальном аудио.
Текущий baseline: `NW_Uckpa0001_01` (Исаев 27.05)
Новые спикеры тестируются на своём аудио до добавления в golden-dataset.
Перед каждым коммитом: real test → 8 пунктов VALIDATION.md → сравнение с golden-dataset.

**#2 ФОРМАТ КОММИТА**
🔧 v17.X: FIX БАГ #N [AUDIO_FILE] - описание

Обязательно: номер бага + название аудио-файла (не хардкод — реальный файл теста).

**#3 DOCS — ПОСЛЕДНИМИ**
Баг → Debug → Fix → Simulation GREEN → Real Test → ✅ GREEN → Docs → Commit

VERSION.md и KNOWN-ISSUES.md обновляются ТОЛЬКО после GREEN.

**#4 DEBUG ПЕРВЫМ**
Перед любым фиксом: добавить debug output → 5 Whys → ROOT CAUSE.
Без ROOT CAUSE фикс не начинается.

**#5 NO COMMIT БЕЗ GREEN**
8/8 GREEN ✅ → коммитить.
Хоть 1 RED ❌ → фиксить сначала.

---

## ЗАПРЕЩЕНО

❌ Говорить «готово» без проверки 8 пунктов VALIDATION.md
❌ Обновлять docs/ до GREEN real test
❌ Фиксить баг без ROOT CAUSE (5 Whys)
❌ Создавать unit-тесты для багов взаимодействия модулей
❌ Создавать ветки/PR — только main
❌ Коммитить самому — только код в чат
❌ Выдумывать названия файлов (deduplicate.py вместо deduplicator.py)
❌ Предполагать расположение функций без проверки через MCP
❌ Предлагать 2+ варианта без анализа ЗА/ПРОТИВ и без simulation-скрипта

---

## ⚡ ОБЯЗАТЕЛЬНО ПРИ ПРЕДЛОЖЕНИИ ВАРИАНТОВ ФИКСА

Перед тем как предложить решение, AI ОБЯЗАН:

1. Прочитать код целевой функции через MCP (не предполагать)
2. Для каждого варианта оценить риски:
   - Какие N-граммы / паттерны затронет?
   - Может ли вариант создать ложные срабатывания?
   - Есть ли в tests/simulations/ похожий кейс?
3. Рекомендовать ОДИН вариант с явным обоснованием ЗА/ПРОТИВ
4. Сразу предложить simulation-скрипт для проверки

❌ ЗАПРЕЩЕНО: «Есть вариант A и вариант B — выбери сам»
✅ ОБЯЗАТЕЛЬНО: «Рекомендую вариант B, вот почему, вот симуляция»

---

## 🧪 СИМУЛЯЦИИ (при текстовых багах)

Симуляция — это не unit-тест. Это прогон реального текста через реальную функцию.

**Когда создавать:**
При каждом баге в текстовой обработке:
`clean_loops`, `hallucinations`, `deduplicator`, `join_texts_deduplicated`.

**Где хранить:**
`tests/simulations/sim_bug{NN}_{функция}.py`

**Что должна содержать:**
- OLD версию функции (до фикса) — для регрессии
- NEW версию функции (после фикса)
- TEST_CASES из реальных debug-логов + `tests/corpus/`
- Проверку вспомогательных функций (`_count_meaningful` и аналогов)

**Правило:**
❌ ЗАПРЕЩЕНО удалять симуляции после закрытия бага —
они становятся регрессионными тестами для будущих фиксов.

---

## 🔍 ПРОВЕРКА СТРУКТУРЫ ПРОЕКТА (ОБЯЗАТЕЛЬНО ПЕРЕД КОДОМ)

**Перед изменением любого файла в `scripts/`:**

### 1. Проверь структуру папки (GitHub MCP)
```bash
get_file_contents(path="scripts/")
get_file_contents(path="scripts/core/")
get_file_contents(path="scripts/merge/")
get_file_contents(path="scripts/corrections/")
get_file_contents(path="scripts/export/")
2. Найди функцию через поиск
bash
search_code(query="repo:Verruckterdrachen/transcription-project function_name")
3. Прочитай файл целиком
bash
get_file_contents(path="scripts/путь/к/файлу.py")
✅ ТОЛЬКО ПОСЛЕ ПРОВЕРКИ: пиши полный путь: scripts/merge/deduplicator.py
❌ НИКОГДА: называть файл без проверки, импортировать из несуществующих модулей

ОСНОВНОЙ ЦИКЛ (фикс бага)
bash
git pull origin main
Читай KNOWN-ISSUES.md → выбери баг

🔍 Проверь структуру проекта (см. раздел выше)

Добавь debug output → найди этап через ARCHITECTURE.md

5 Whys → сформулируй ROOT CAUSE

Если текстовый баг → создай tests/simulations/sim_bug{NN}_{func}.py

Исправь код (минимально, одна причина за раз)

Simulation GREEN ✅

python scripts/transcribe.py на реальном аудио
python scripts/validate.py   ← автоматические пункты 1,2,3,5,7
Проверь 8 пунктов VALIDATION.md (4,6,8 — вручную)


✅ Все GREEN → обнови VERSION.md + KNOWN-ISSUES.md + CHANGELOG.md

Коммит: 🔧 v17.X: FIX БАГ #N [AUDIO_FILE] - описание

bash
git push origin main
РОЛИ
Ты (человек):

Запускаешь пайплайн, смотришь JSON/TXT/LOG

Проверяешь 8 пунктов VALIDATION.md

Коммитишь, когда всё GREEN

AI:

Читает docs/ перед каждой сессией (порядок: VERSION.md → KNOWN-ISSUES.md → WORKFLOW.md → BUG_REGISTRY.md)

Проверяет структуру scripts/ через MCP перед изменением кода

ДО real test: присылает только scripts/*.py + симуляцию (полностью)

ПОСЛЕ GREEN: присылает:

docs/VERSION.md (полностью, ~30 строк)

docs/KNOWN-ISSUES.md (полностью)

docs/CHANGELOG.md (только новый блок — prepend в начало)

Git команды для коммита

НЕ коммитит сам, НЕ пишет unit-тесты, НЕ обновляет docs/ до GREEN

Подробный формат отправки → см. INTEGRATION-CHECKLIST.md раздел 2.8

## ЗАПУСК ПАЙПЛАЙНА

cd scripts
python transcribe.py     ← основной пайплайн, результаты → test-results/latest/
python validate.py        ← сразу после: автопроверка пунктов 1,2,3,5,7
                            Если RED → чинить ДО ручных проверок 4,6,8

Интерактивно:

Путь к папке спикера (Спикер (ДД.ММ)/)

Режим: [точный] (по умолчанию)

Результат:

JSON → .../json/

TXT → .../txt/

Лог → transcription_debug.log (локально, не в git)

Копия → test-results/latest/

СТРУКТУРА ТЕСТОВ
tests/
  simulations/   ← sim_bug{NN}_{func}.py — регрессионные симуляции
  unit/          ← только изолированные утилиты (regex, парсинг)
  corpus/        ← реальные текстовые фрагменты для симуляций


СВЯЗАННЫЕ ДОКУМЕНТЫ
| Когда читать            | Документ                         |
| ----------------------- | -------------------------------- |
| Начало сессии           | VERSION.md → KNOWN-ISSUES.md     |
| Выбор бага              | KNOWN-ISSUES.md                  |
| Открытие нового бага    | BUG_REGISTRY.md (проверить номер)|
| Поиск этапа в пайплайне | ARCHITECTURE.md                  |
| Методология отладки     | DEBUGGING.md                     |
| Перед изменением кода   | WORKFLOW.md (раздел 🔍 ПРОВЕРКА) |
| Перед отправкой кода    | INTEGRATION-CHECKLIST.md         |
| Перед коммитом          | VALIDATION.md                    |
| История версий          | CHANGELOG.md                     |