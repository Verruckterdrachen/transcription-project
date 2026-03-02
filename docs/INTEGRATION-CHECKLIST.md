# INTEGRATION-CHECKLIST.md — Чеклист интеграции
# Обновлено: 2026-02-20

Используется ПЕРЕД тем, как отправлять изменение в чат (AI → человек) и перед коммитом.

---

## 0. ⚠️ КРИТИЧНО: Порядок отправки

**ПРОБЛЕМА:** AI обновлял VERSION.md ДО real test → вводил в заблуждение.

### Шаг 1: ДО REAL TEST (AI → человек)

Присылаю **ТОЛЬКО КОД**:
- ✅ `scripts/*.py` — файлы с фиксом (полностью)
- ✅ `tests/simulations/sim_bug{NN}_{func}.py` — если текстовый баг
- ✅ DEBUG OUTPUT — что должно измениться в логе
- ✅ ОЖИДАЕМЫЙ РЕЗУЛЬТАТ — что проверить в TXT/JSON
- ✅ VALIDATION.md чеклист — какие пункты проверить

**НЕ присылаю:**
- ❌ `docs/VERSION.md` — обновление ПОСЛЕ GREEN
- ❌ Описание «РЕШЕНО» — может быть ещё RED
- ❌ Git команды — коммит ПОСЛЕ GREEN

⚡ Сначала ты запускаешь:
  python scripts/validate.py   ← пункты 1,2,3,5,7 должны быть GREEN
  (пункты 4,6,8 — вручную по VALIDATION.md)

Затем AI присылает ДОКУМЕНТАЦИЮ + GIT:
- ✅ `docs/VERSION.md` (полностью, ~30 строк)
- ✅ `docs/KNOWN-ISSUES.md` (полностью)
- ✅ `docs/CHANGELOG.md` (только новый блок — prepend в начало)
- ✅ Git команды для коммита

### Шаг 3: ПОСЛЕ REAL TEST RED (AI продолжает)

- 🔄 Анализирую новый лог
- 🔄 5 Whys (возможно новый ROOT CAUSE)
- 🔄 Обновляю код / симуляцию
- 🔄 Возвращаюсь к Шагу 1

**ФОРМАТ НАПОМИНАНИЯ:**

━━━ РЕШЕНИЕ v17.X ━━━

━━━ scripts/file.py ━━━
[КОД]

━━━ tests/simulations/sim_bugNN_func.py ━━━ ← если текстовый баг
[КОД СИМУЛЯЦИИ]

━━━ ПЕРЕД КОММИТОМ: REAL TEST! ━━━

python scripts/transcribe.py

Проверь VALIDATION.md (8 пунктов) — полный список в docs/VALIDATION.md

━━━ ПОСЛЕ REAL TEST ━━━
✅ Если GREEN → присылай лог, я отправлю VERSION.md + git команды
❌ Если RED → присылай лог с ошибкой, продолжим DEBUG

text

---

## 1. Общий принцип

1. **Real test ОБЯЗАТЕЛЕН** — `python scripts/transcribe.py` на реальном аудио
2. **Проверь 8 пунктов `VALIDATION.md`** — коммитить только при 8/8 GREEN
3. **Документация синхронизирована** — если менялся пайплайн → обнови `docs/*`
4. **VERSION.md обновляется ТОЛЬКО после GREEN test**

---

## 2. Чеклист интеграции

### 2.1. Debugging / Root Cause
- [ ] Применена методология из `DEBUGGING.md`
- [ ] Debug-лог приложен или описан
- [ ] 5 Whys выполнен, ROOT CAUSE сформулирован

### 2.2. Симуляция (если текстовый баг)
- [ ] Создан `tests/simulations/sim_bug{NN}_{func}.py`
- [ ] Содержит OLD + NEW версию функции
- [ ] TEST_CASES из реальных debug-логов
- [ ] Все тесты GREEN перед отправкой кода

### 2.3. Debug checkpoints
- [ ] Для всех функций, меняющих `seg["text"]` или `start/end`:
  добавлен `debug_checkpoint(..., stage_name=...)` после функции
- [ ] В `process_audio_file()` есть checkpoint'ы на этапах:
  AFTER ALIGNMENT, AFTER BOUNDARY CORRECTION, AFTER DEDUPLICATION,
  AFTER GAP FILLING, AFTER TIMESTAMP CORRECTION, AFTER MERGE,
  AFTER TIMESTAMP INJECTION, AFTER CLASSIFICATION, AFTER SPLIT,
  AFTER TEXT CORRECTION, AFTER HALLUCINATION REMOVAL,
  AFTER AUTO-MERGE, BEFORE EXPORT (FINAL)

### 2.4. VERSION.md
- [ ] ⚠️ Обновляется ТОЛЬКО после GREEN real test
- [ ] Новая версия, дата, ROOT CAUSE, краткий FIX

### 2.5. ARCHITECTURE.md
Если менялся пайплайн (новая функция, новый этап):
- [ ] Обновлена таблица этапов
- [ ] Обновлена схема data flow (если нужно)

### 2.6. TESTING-STRATEGY.md
Если добавлена новая изолированная утилита:
- [ ] Отражены новые правила для unit-тестов

### 2.7. Проверка зависимостей между файлами
- [ ] Все imports проверены на существование через MCP
- [ ] Если функция отсутствует → добавлена в том же решении
- [ ] Зависимость явно указана в сообщении (⚠️ ЗАВИСИМОСТЬ: ...)

### 2.8. Формат отправки файлов (AI → человек)

**Файлы, которые AI присылает ПОЛНОСТЬЮ (заменяешь целиком):**
- ✅ `scripts/*.py` — любой размер, всегда полностью
- ✅ `tests/simulations/sim_bug{NN}_{func}.py` — полностью
- ✅ `docs/VERSION.md` — специально короткий (~30 строк)
- ✅ `docs/KNOWN-ISSUES.md` — ~50 строк

**Файлы, в которые AI присылает ТОЛЬКО НОВЫЙ БЛОК:**
- ✅ `docs/CHANGELOG.md` — блок `[vX.X]` prepend в самое начало

---

## 3. Итоговый чеклист перед коммитом

- [ ] ROOT CAUSE найден и описан (5 Whys)
- [ ] DEBUG OUTPUT есть и понятен
- [ ] Debug checkpoints на всех text-критичных этапах
- [ ] При текстовом баге: симуляция GREEN
- [ ] ⚠️ REAL TEST выполнен и GREEN
- [ ] ⚠️ `python scripts/validate.py` — GREEN (пункты 1,2,3,5,7)
- [ ] Пункты 4,6,8 VALIDATION.md — проверены вручную
- [ ] ⚠️ VERSION.md обновлён ПОСЛЕ GREEN test
- [ ] KNOWN-ISSUES.md обновлён
- [ ] CHANGELOG.md — новый блок prepend
- [ ] При необходимости обновлены ARCHITECTURE.md, TESTING-STRATEGY.md
- [ ] 8 пунктов VALIDATION.md — GREEN (полный список → docs/VALIDATION.md)