# 🐛 DEBUGGING.md — стратегия отладки
# Обновлено: 2026-02-20

Документ описывает, как искать и устранять баги в транскрибационном пайплайне.

Основная философия:

- **Real tests > Simulations > Integration > Unit**
- **Debug output + 5 Whys → ROOT CAUSE → Simulation GREEN → FIX → Real test**
- Симуляции — при каждом текстовом баге (см. TESTING-STRATEGY.md)
- Unit tests — только для изолированных утилит (regex, парсинг, форматирование)

---

## 1. Базовые принципы отладки

1. **Documentation First**
   Перед изменениями кода:
   - прочитай `VERSION.md` (последняя версия, известные баги и фиксы);
   - загляни в `ARCHITECTURE.md` (где именно в пайплайне твой этап).

2. **GitHub as Source**
   Используй код из репозитория как единственный источник истины.
   Перед правкой любого файла — читай его через MCP.

3. **Debug First, Fix Later**
   Перед любым фиксом:
   - включи/добавь debug‑логирование;
   - убедись, что можешь увидеть баг на уровне конкретных сегментов/timestamp'ов.

4. **Root Cause Analysis (5 Whys)**
   Не останавливайся на симптоме:
   - 5 раз спроси «почему?» до настоящей причины;
   - зафиксируй ROOT CAUSE в `VERSION.md`.

5. **Real test ПЕРЕД коммитом**
   Обязательно:
   - запусти `python scripts/transcribe.py` на реальном аудио;
   - проверь 8 пунктов из `VALIDATION.md`.

---

## 2. Алгоритм отладки (pipeline‑баг)

1. Зафиксируй **симптом** (что именно не так в TXT/JSON):
   - пропала фраза;
   - неверный спикер;
   - дубли timestamps;
   - странные паузы и т.п.

2. Определи **где в пайплайне** мог возникнуть эффект:
   - смотри `ARCHITECTURE.md` — этапы 1–10;
   - найди функции, которые модифицируют `seg['text']`, `start`, `end`.

3. Включи/добавь **debug checkpoints** (см. раздел 4).

4. Сравни **checkpoint "ДО" и "ПОСЛЕ"**:
   - ищи, на каком этапе изменился текст/спикер/timestamp;
   - зафиксируй точный этап (например, «Этап 6.1 — clean_loops»).

5. Прочитай код функций этого этапа через MCP:
   - найди место, где данные портятся;
   - сформулируй ROOT CAUSE через 5 Whys.

6. **Если текстовый баг** — создай симуляцию ПЕРЕД фиксом:
   - `tests/simulations/sim_bug{NN}_{func}.py`
   - OLD версия функции (воспроизводит баг) → RED
   - NEW версия функции (после фикса) → GREEN
   - TEST_CASES из реальных debug-логов (минимум 3)
   - Симуляция должна быть GREEN до отправки кода

7. Придумай и реализуй **FIX**:
   - минимальный по объёму;
   - без побочных эффектов на соседние этапы;
   - одна причина за раз.

8. Запусти **Real test**:
   - на реальном интервью;
   - с полным пайплайном, а не только функцией.

9. Обнови документацию:
   - `VERSION.md` — новая версия + ROOT CAUSE + FIX;
   - `KNOWN-ISSUES.md` — закрыть баг;
   - при необходимости — `ARCHITECTURE.md`, `TESTING-STRATEGY.md`.

---

## 3. Debug output

### 3.1. Общие правила

- Логи должны:
  - показывать ключевые решения (слияние, разбиение, смена спикера);
  - содержать timestamp, speaker, длины текста.
- Не спамить всем подряд — логируй только критичные места.

### 3.2. Примеры полезного debug‑вывода

**Merge реплик:**
```python
print(f"🔗 MERGE {i} + {j} → [{merged['time']}] "
      f"{merged['speaker']} ({len(merged['text'].split())} слов)")
clean_loops:

python
print(f"🔁 LOOP SKIP: ngram='{ngram}' sim={sim:.2f} "
      f"meaningful={_count_meaningful(ngram)} anchor='{anchor}'")
Split mixed‑speaker сегмента:

python
print(f"✂️ SPLIT [{seg['time']}] {seg['speaker']} → "
      f"{len(new_segments)} частей")
Hallucination filter:

python
print(f"🧹 HALLUCINATION REMOVE: [{seg['time']}] "
      f"{seg['speaker']} → '{seg['text'][:80]}...'")
4. Debug checkpoints (v16.28+)
Урок БАГ #3:
Половина времени ушла на то, чтобы понять, что текст обрезается именно на этапе
insert_intermediate_timestamps() — до этого не было системных checkpoint'ов.

### 4.1. Стандартная функция checkpoint'а (v17.19)

Функция находится в `scripts/transcribe.py`.
Параметризована через две модульные переменные — задай их в `main()` при отладке:

```python
# Задать в начале main() для конкретного бага:
global _DEBUG_TARGET_TIMESTAMPS, _DEBUG_TARGET_PHRASE
_DEBUG_TARGET_TIMESTAMPS = ["00:02:26"]        # нужные HH:MM:SS
_DEBUG_TARGET_PHRASE     = "прорыв блокады"    # целевая фраза (или None)
Для обычного прогона (без отладки конкретного бага) — оставить пустыми:

python
_DEBUG_TARGET_TIMESTAMPS = []
_DEBUG_TARGET_PHRASE     = None
Тогда debug_checkpoint выводит только счётчик сегментов на каждом этапе — без спама.

Сигнатура (не менять):

python
def debug_checkpoint(segments, stage_name,
                     target_timestamps=None, target_phrase=None):
Приоритет параметров: явные аргументы при вызове → модульные переменные.
Это позволяет одновременно отлаживать два разных timestamp в разных частях пайплайна.

4.2. Где ОБЯЗАТЕЛЬНО вызывать checkpoint
В process_audio_file():

python
debug_checkpoint(segments_raw,    "AFTER ALIGNMENT")
debug_checkpoint(segments_raw,    "AFTER JOURNALIST COMMANDS")
debug_checkpoint(segments_raw,    "AFTER BOUNDARY CORRECTION")
debug_checkpoint(segments_raw,    "AFTER CROSS-SPEAKER DEDUP")
debug_checkpoint(segments_raw,    "AFTER DEDUPLICATION")
debug_checkpoint(segments_raw,    "AFTER GAP FILLING")           # если были gaps
debug_checkpoint(segments_raw,    "AFTER TIMESTAMP CORRECTION")

debug_checkpoint(segments_merged, "AFTER MERGE")
debug_checkpoint(segments_merged, "AFTER TIMESTAMP INJECTION")
debug_checkpoint(segments_merged, "AFTER CLASSIFICATION")
debug_checkpoint(segments_merged, "AFTER SPLIT")
debug_checkpoint(segments_merged, "AFTER TEXT CORRECTION")
debug_checkpoint(segments_merged, "AFTER HALLUCINATION REMOVAL")
debug_checkpoint(segments_merged, "AFTER AUTO-MERGE")            # если был auto-merge
debug_checkpoint(segments_merged, "BEFORE EXPORT (FINAL)")

```markdown
Правило v17.19:
Для обычного прогона все 14 checkpoint'ов выводят только счётчики — это бесплатно.
Для отладки конкретного бага — задать _DEBUG_TARGET_TIMESTAMPS в main().
Не удалять checkpoint'ы после закрытия бага.
Правило v16.28:
Если функция меняет seg["text"] или границы (start / end), checkpoint обязателен сразу после неё.

5. 5 Whys (Root Cause)
Шаблон для любого бага:

Почему проявился симптом?

Почему этот эффект вообще возможен в коде?

Почему это не поймали тесты/валидаторы?

Почему стратегия тестирования позволила багу пройти?

Какое корневое организационное/архитектурное решение привело к этому?

Пример — БАГ #27 (v17.9):

Почему удалилось "был."?
→ N-грамма "был. И вот" дала sim=0.80 с якорем в seen[]

Почему sim высокое при отсутствии смысла?
→ Обе N-граммы состоят из грамматических слов (форма «быть» + союзы)

Почему порог 0.75 не защитил?
→ Порог настроен на семантические повторы, не учитывает грамматические слова

Почему в seen[] попал бессодержательный якорь?
→ Не было фильтра по значимости N-граммы перед добавлением в seen[]

ROOT CAUSE: отсутствие проверки семантической значимости N-граммы
перед fuzzy matching

Пример — БАГ #3 (v16.28):

Почему пропала фраза?
→ insert_intermediate_timestamps() обрезала последнее предложение

Почему обрезала?
→ range(0, len(sentences)-1, 2) пропускал последний элемент

Почему не поймали?
→ Не было unit‑теста на парсинг предложений

Почему не сделали unit‑test?
→ Не отделили парсер предложений в тестируемую утилиту

ROOT CAUSE: ошибка в утилите парсинга + отсутствие unit‑теста на неё

6. Чеклист перед фиксом
Перед тем как править код:

 Понимаю, на каком этапе pipeline появляется баг (по checkpoint'ам)

 Есть debug‑логи до и после проблемного этапа

 Записан симптом + пример (timestamp + текст)

 Прочитал код целевой функции через MCP (не предполагаю)

 Если текстовый баг → создан tests/simulations/sim_bug{NN}_{func}.py и GREEN

 Планирую минимум изменений (1 функция / 1 модуль)

 Понимаю, как буду проверять фикс (Real test + VALIDATION.md)

После фикса:

 Обновлён VERSION.md (версия + ROOT CAUSE + FIX)

 Обновлён KNOWN-ISSUES.md (баг закрыт)

 При необходимости обновлены ARCHITECTURE.md, TESTING-STRATEGY.md

 Реальный тест пройден, 8 пунктов VALIDATION.md — GREEN