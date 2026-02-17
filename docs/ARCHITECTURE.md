# 🧩 ARCHITECTURE.md — архитектура пайплайна v16.x

Документ описывает структуру проекта и последовательность этапов обработки аудио → JSON → TXT.

---

## 1. Общее устройство проекта

Директории:

- `scripts/`
  - `transcribe.py` — главный entry‑point пайплайна.
  - `core/` — базовые функции (диаризация, транскрибация, выравнивание, utils).
  - `corrections/` — исправления текста, границ, спикеров, hallucinations.
  - `merge/` — слияние, дедупликация и валидация сегментов.
  - `export/` — экспорт JSON и TXT.
- `docs/` — документация (workflow, debugging, testing, architecture и т.д.).
- `test-results/` — артефакты real tests (`latest/` → последние результаты).

Главный сценарий: `scripts/transcribe.py`.

---

## 2. Ключевые этапы пайплайна

Пайплайн обрабатывает **один WAV‑файл** в `process_audio_file()` следующим образом.

### Таблица этапов

| Этап | Назначение | Функция | Файл | Checkpoint | Меняет `text`? |
|------|-----------|---------|------|-----------|----------------|
| 1 | Диаризация (спикеры) | `diarize_audio` | `core/diarization.py` | нет | ❌ |
| 2 | Транскрибация (Whisper) | `transcribe_audio` | `core/transcription.py` | нет | ❌ |
| 3 | Выравнивание Whisper+diar | `align_whisper_with_diarization` | `core/alignment.py` | AFTER ALIGNMENT | ❌ |
| 4.1 | Команды журналиста | `detect_journalist_commands_cross_segment` | `corrections/journalist_commands.py` | AFTER JOURNALIST COMMANDS | ✅ |
| 4.2 | Исправление границ | `boundary_correction_raw` | `corrections/boundary_fixer.py` | AFTER BOUNDARY CORRECTION | в основном `start/end` |
| 4.3 | Cross‑speaker dedup | `remove_cross_speaker_text_duplicates` | `merge/deduplicator.py` | AFTER CROSS-SPEAKER DEDUP | ✅ |
| 4.4 | Дедупликатор сегментов | `deduplicate_segments` | `merge/deduplicator.py` | AFTER DEDUPLICATION | ✅ |
| 5 | Заполнение GAP'ов | `force_transcribe_diar_gaps` | `core/transcription.py` | AFTER GAP FILLING | ✅ (для новых сегментов) |
| 5.2 | Drift timestamp'ов | `correct_timestamp_drift` | `corrections/timestamp_fixer.py` | AFTER TIMESTAMP CORRECTION | `start/time` |
| 6 | Merge реплик | `merge_replicas` | `merge/replica_merger.py` | AFTER MERGE | ✅ |
| 7 | Весовая классификация спикеров | `apply_speaker_classification_v15` | `corrections/speaker_classifier.py` | AFTER CLASSIFICATION | может менять `speaker` |
| 🔥 **8** | 🔥 **Split mixed‑speaker** | `split_mixed_speaker_segments` | `corrections/boundary_fixer.py` | AFTER SPLIT | ✅ |
| 🔥 **8.1** | 🔥 **Вставка inner timestamps** | `insert_intermediate_timestamps` | `corrections/timestamp_fixer.py` | AFTER TIMESTAMP INJECTION | ✅ |
| 8.2 | Text‑based corrections | `text_based_correction` | `corrections/text_corrections.py` | AFTER TEXT CORRECTION | ✅ |
| 8.3 | Удаление hallucinations | `filter_hallucination_segments` | `corrections/hallucinations.py` | AFTER HALLUCINATION REMOVAL | ✅ |
| 9 | Auto‑merge смежных | `auto_merge_adjacent_same_speaker` | `merge/validator.py` | AFTER AUTO-MERGE | ✅ |
| 10 | Экспорт JSON | `export_to_json` | `export/json_export.py` | BEFORE EXPORT (FINAL) | ❌ |
| 10 | Экспорт TXT | `jsons_to_txt` / `export_to_txt` | `export/txt_export.py` | после TXT | ❌ |

### 🔥 v16.40: КРИТИЧЕСКОЕ ИЗМЕНЕНИЕ ПОРЯДКА ЭТАПОВ

**БЫЛО v16.39:**
6: merge_replicas
6.1: insert_intermediate_timestamps ← Timestamp injection ДО split!
7: classification
8: split_mixed_speaker_segments

text

**СТАЛО v16.40:**
6: merge_replicas
7: classification
8: split_mixed_speaker_segments ← Split ПЕРВЫЙ!
8.1: insert_intermediate_timestamps ← Timestamp injection ПОСЛЕ split!

text

**ROOT CAUSE v16.39:**
- Timestamp injection ДО split → вставка ВНУТРИ длинного merged text
- Ищет точку в радиусе 100 символов → 8/19 вставлены БЕЗ точки
- Timestamp попадает в начало предложения: "00:16:06 Несмотря..."
- Ломает continuation patterns: `r'^несмотря\b'` НЕ срабатывает

**РЕШЕНИЕ v16.40:**
- Split ПЕРВЫЙ → разбивает на предложения с точками
- Timestamp injection ВТОРЫМ → вставляет МЕЖДУ предложениями
- Результат: timestamp ВСЕГДА после точки, continuation patterns работают

---

## 3. Поток данных (схема)

```text
WAV
 └─► Whisper (segments)                    [core/transcription.py]
      └─► Diarization (speakers)           [core/diarization.py]
           └─► Alignment (text+speaker)    [core/alignment.py]
                └─► Corrections (4.x)      [corrections/*]
                     └─► Gap filling       [core/transcription.py]
                          └─► Timestamp drift fix  [corrections/timestamp_fixer.py]
                               └─► Merge replicas  [merge/replica_merger.py]
                                    └─► Classification  [corrections/speaker_classifier.py]
                                         🔥 └─► SPLIT (v16.40)  [corrections/boundary_fixer.py]
                                              🔥 └─► TIMESTAMP INJECT (v16.40)  [corrections/timestamp_fixer.py]
                                                   └─► Text+Hallucinations [corrections/*]
                                                        └─► Auto‑merge + Validation [merge/validator.py]
                                                             └─► Export JSON+TXT   [export/*]
4. Критичные места (могут «съесть» текст)
Функции, где особенно важно иметь debug checkpoints и быть осторожным:

merge_replicas

Склеивает несколько сегментов в один;

может потерять часть текста при ошибках логики слияния.

🔥 insert_intermediate_timestamps (v16.40: УПРОЩЁН)

Вставляет timestamps внутрь существующего текста.

v16.39: БАГ #11 - неверный range(...) + поиск точки в радиусе 100 символов → потеря последнего предложения + вставка БЕЗ точки.

v16.40: УПРОЩЁН - split УЖЕ разбил на предложения → просто вставляем timestamp МЕЖДУ ними.

split_mixed_speaker_segments

Делит один сегмент на несколько;

риск: неверный спикер / обрезка текста.

text_based_correction

Правит текст по шаблонам (журналист/эксперт, контекст);

риск: случайное удаление фрагментов.

filter_hallucination_segments

Может удалить целый сегмент как галлюцинацию.

Правило:
Если баг связан с пропажей текста, проверяй сперва эти 5 функций.

5. Как использовать ARCHITECTURE.md при отладке
Сценарий: пропала фраза
Нашёл в TXT, что при HH:MM:SS нет ожидаемой фразы.

Используешь debug_checkpoint(..., target_timestamps=["HH:MM:SS"]) на всех ключевых этапах.

Смотришь, на каком этапе фраза есть, а на следующем — нет.

По таблице выше определяешь:

этап (номер и смысл),

функцию,

файл.

Открываешь файл → читаешь код → ищешь ROOT CAUSE.

Пример БАГ #11 (v16.40):
AFTER SPLIT: фраза есть, "Несмотря на все..." в начале предложения

AFTER TIMESTAMP INJECTION: "00:16:06 Несмотря..." ← timestamp в начале!

Continuation pattern: r'^несмотря\b' НЕ срабатывает (timestamp перед текстом)

ARCHITECTURE: этап 8.1 → insert_intermediate_timestamps → corrections/timestamp_fixer.py

ROOT CAUSE: Timestamp injection ДО split → вставка между словами

РЕШЕНИЕ: Поменять порядок: split ПЕРВЫМ, timestamp injection ВТОРЫМ

6. Требования при изменении архитектуры
Если ты:

добавляешь новый этап пайплайна;

выносишь часть логики в новый модуль;

начинаешь модифицировать seg["text"] в новой функции;

ОБЯЗАТЕЛЬНО:

Обнови таблицу в этом файле (этап, функция, файл, checkpoint, меняет ли text).

Добавь/обнови debug checkpoint в process_audio_file().

При необходимости обнови TESTING-STRATEGY.md (нужен ли unit‑test).

Отрази изменения в VERSION.md.