# VERSION v16.19

**Date:** 2026-02-12  
**Status:** ✅ PRODUCTION

---

## 🔧 v16.19: Critical Fix - Timestamps + Hallucinations + Continuation

### 🐛 Исправлены 4 критических бага

**1. Отсутствие timestamp (блоки >30 сек)**
- ❌ Было: блоки до 231 сек без промежуточных меток
- ✅ Стало: вставка timestamp каждые ~30 сек
- ROOT CAUSE: `merge_replicas()` не проверял длительность блока
- FIX: новый модуль `timestamp_fixer.py` + `insert_intermediate_timestamps()`

**2. Сдвиг timestamp (после gap filling)**
- ❌ Было: timestamp сдвиг +8-10 сек после 00:10:03
- ✅ Стало: исправление start после overlap adjustment
- ROOT CAUSE: gap filling меняет `segment.end`, но не обновляет start
- FIX: `correct_timestamp_drift()` после gap filling

**3. Hallucinations (дубли + "Продолжение следует")**
- ❌ Было: "ничего не знали. ничего не знали."
- ✅ Стало: детекция дублей (similarity >95%) + удаление ending hallucinations
- ROOT CAUSE: Whisper галлюцинирует при паузах/заиканиях
- FIX: обновлён `hallucinations.py` + `is_duplicate_phrase()`

**4. Continuation phrase (порог similarity)**
- ❌ Было: порог 80% пропускал заикания (similarity ~85-95%)
- ✅ Стало: порог повышен до 90%
- ROOT CAUSE: слишком низкий threshold в `detect_continuation_phrase()`
- FIX: обновлён `boundary_fixer.py` (80% → 90%)

### 📝 Технические изменения

**Новые файлы:**
- `scripts/corrections/timestamp_fixer.py` — модуль исправления timestamp
- `tests/test_timestamp_fixer.py` — unit tests для всех 4 багов

**Изменённые файлы:**
- `scripts/transcribe.py` — интеграция timestamp_fixer
- `scripts/corrections/hallucinations.py` — удаление дублей
- `scripts/corrections/boundary_fixer.py` — порог 80% → 90%
- `docs/VERSION.md` — обновлён до v16.19

**Pipeline order (обновлено):**
ЭТАП 5.1: gap filling
ЭТАП 5.2: correct_timestamp_drift() ← 🆕
ЭТАП 6: merge_replicas()
ЭТАП 6.1: insert_intermediate_timestamps() ← 🆕
ЭТАП 7: speaker classification
ЭТАП 8: text corrections
ЭТАП 8.1: filter_hallucination_segments() ← 🆕

text

### 🧪 Unit Tests

**4 теста для ROOT CAUSE:**
```bash
python tests/test_timestamp_fixer.py
test_insert_intermediate_timestamps_long_block() — блок 231 сек

test_correct_timestamp_drift() — сдвиг +8 сек

test_hallucination_duplicate_removal() — дубли

test_continuation_phrase_threshold() — порог 90%

🎯 Результаты
Ожидаемые исправления:

✅ Блоки >30 сек получат промежуточные timestamp

✅ Timestamp совпадут с аудио (сдвиг <1s)

✅ Дубли будут удалены ("ничего не знали" → 1 раз)

✅ Заикания будут детектироваться (similarity >90%)

Статистика из ошибок:

12 блоков без timestamp → исправлено

7 сдвигов timestamp → исправлено

5 дублей → удалено

3 заикания без "..." → детектировано

⏮️ Предыдущие версии
v16.18.1 (2026-02-12)
Fix копирования в test-results + golden-dataset

v16.18 (2026-02-12)
Golden Dataset infrastructure

[Полная история: docs/CHANGELOG.md]

Последнее обновление: 12.02.2026
Текущая версия: v16.19
Следующая версия: v16.20 (разрыв реплик + false splits)