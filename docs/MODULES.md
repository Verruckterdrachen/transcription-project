# 📚 Справочник модулей и функций
# Обновлено: 2026-02-20

Полное описание всех функций проекта с параметрами и примерами использования.

---

## 📂 scripts/core/ - Базовая функциональность

### config.py

**Описание:** Конфигурация проекта и константы

```python
HF_TOKEN: str
    Hugging Face API токен для доступа к моделям

VERSION: str
    Текущая версия проекта (например: "17.9")

VERSION_NAME: str
    Кодовое имя версии
utils.py
seconds_to_hms(seconds: float) -> str
Конвертирует секунды в формат HH:MM:SS.mmm

python
seconds_to_hms(125.456)
# → "00:02:05.456"
parse_speaker_folder(folder_name: str) -> Tuple[str, str, str]
Парсит имя папки спикера

Параметры:

folder_name: Имя папки (формат: "Фамилия (ДД.ММ)")

Возвращает: (surname, date, full_name)

python
parse_speaker_folder("Исаев (29.01)")
# → ("Исаев", "29.01", "Исаев")
adaptive_vad_threshold(duration: float) -> float
Вычисляет адаптивный VAD threshold на основе длительности

python
if duration < 600:      # <10 мин → 0.3
elif duration < 1800:   # 10-30 мин → 0.4
else:                   # >30 мин → 0.5
gap_detector(segments: List[Dict], threshold: float = 3.0) -> List[Dict]
Обнаруживает паузы (gaps) между сегментами

Возвращает:

python
{
    "gap_hms_start": "00:05:30.000",
    "gap_hms_end": "00:05:35.000",
    "start": 330.0,
    "end": 335.0,
    "duration": 5.0
}
text_similarity(text1: str, text2: str) -> float
🆕 v16.5: Вычисляет семантическое сходство двух текстов

Алгоритм: Jaccard similarity на уровне слов

python
text_similarity("Добрый день", "Добрый вечер")
# → 0.67 (2 общих слова из 3)
diarization.py
diarize_audio(pipeline, audio_path: Path, min_speakers: int, max_speakers: int) -> Annotation
Выполняет диаризацию аудио файла

python
pipeline = Pipeline.from_pretrained("pyannote/speaker-diarization-3.1")
diarization = diarize_audio(pipeline, Path("audio.wav"), 2, 3)
compute_speaker_stats(diarization: Annotation) -> Dict[str, Dict]
Вычисляет статистику по каждому спикеру

Возвращает:

python
{
    "SPEAKER_00": {
        "total_time": 1234.5,
        "num_segments": 89
    }
}
identify_speaker_roles(stats: Dict, segments: List[Dict], speaker_surname: str = "") -> Dict[str, str]
🔧 v17.8: Идентифицирует роли спикеров (Журналист / Эксперт / Оператор)

Параметры:

stats: Статистика спикеров

segments: Список сегментов

speaker_surname: Фамилия главного спикера (добавлено v17.8, БАГ #26)

Возвращает:

python
{
    "SPEAKER_00": "Журналист",
    "SPEAKER_01": "Горбунов",   # ← speaker_surname, не "Спикер"
    "SPEAKER_02": "Оператор"    # если есть
}
Логика:

Минимальное время → Журналист

Максимальное время → speaker_surname (fallback: "Спикер" если не передан)

Дополнительный → Оператор

⚠️ БАГ #26 (v17.8): до фикса hardcoded "Спикер" вместо speaker_surname.

align_segment_to_diarization(segment: Dict, diarization: Annotation) -> str
Определяет спикера для одного сегмента

Возвращает: ID спикера ("SPEAKER_00", "SPEAKER_01", ...)

alignment.py
align_whisper_with_diarization(segments, diarization, speaker_surname, speaker_roles) -> List[Dict]
Связывает транскрипцию Whisper с диаризацией

Возвращает:

python
{
    "start": 0.0,
    "end": 5.3,
    "text": "Добрый день!",
    "speaker": "Журналист",
    "raw_speaker_id": "SPEAKER_00",
    "confidence": 0.95
}
transcription.py
transcribe_audio(model, audio_path, language, temperature, beam_size, vad_threshold) -> Dict
Транскрибирует аудио с помощью Whisper

Параметры:

temperature: 0.0 для детерминизма

beam_size: 5 для качества

force_transcribe_diar_gaps(model, audio_path, gaps, segments, speaker_surname) -> List[Dict]
🆕 v16.5: Заполняет пропуски (gaps) с умной атрибуцией

Алгоритм:

python
gap_text = transcribe_gap_audio()

similarity_prev = text_similarity(gap_text, prev_segment["text"])
similarity_next = text_similarity(gap_text, next_segment["text"])

if similarity_prev > similarity_next:
    speaker = prev_segment["speaker"]
else:
    speaker = next_segment["speaker"]

# Защита от запинок
if len(gap_text) < 10 or confidence < 0.6:
    speaker = diarization_speaker
📂 scripts/corrections/ - Коррекция результатов
hallucinations.py
filter_hallucination_segments(segments: List[Dict]) -> List[Dict]
Фильтрует галлюцинации Whisper

Критерии галлюцинации:

Повторяющийся текст (>3 раза)

Низкая confidence (<0.4)

Подозрительные паттерны

clean_hallucinations_from_text(text: str) -> str
Очищает текст от известных галлюцинаций

Примеры удаляемого:

"Субтитры сделал DimaTorzok"

"Подписывайтесь на канал"

Повторы фраз

speaker_classifier.py
apply_speaker_classification_v15(segments, speaker_surname, debug=False) -> Tuple[List[Dict], Dict]
Весовая классификация спикеров

Система весов:

python
{
    "duration":     0.30,
    "position":     0.15,
    "pattern":      0.25,
    "context":      0.20,
    "diarization":  0.10
}
boundary_fixer.py
boundary_correction_raw(segments, speaker_surname, speaker_roles) -> List[Dict]
Корректирует границы между сегментами

Что исправляет:

Перекрытия таймкодов

Слишком короткие/длинные паузы

Разрывы в диалоге

split_mixed_speaker_segments(segments, speaker_surname) -> List[Dict]
🔧 v16.4: Разделяет mixed-speaker сегменты с пересчётом таймкодов

python
# До:
[{"text": "Да, понятно. [вмешивается] Продолжу", "speaker": "Эксперт"}]

# После:
[
    {"text": "Да, понятно.",     "speaker": "Эксперт"},
    {"text": "вмешивается",      "speaker": "Журналист"},
    {"text": "Продолжу",         "speaker": "Эксперт"}
]
journalist_commands.py
detect_journalist_commands_cross_segment(segments, speaker_surname) -> Tuple[List[Dict], List[Dict]]
Детектирует команды Журналиста, приписанные Эксперту

Детектируемые паттерны:

python
["давайте", "пожалуйста", "расскажите", "можете", "объясните", "покажите"]
text_corrections.py
text_based_correction(segments, speaker_surname) -> List[Dict]
🔧 v16.4: Расширенная текстовая коррекция

python
# Context Window Protection
if in_long_monologue(segment, threshold=60):
    skip_correction()

# Confirmation Detection
if text in ["ну да", "да-да", "угу"] and duration < 2:
    force_journalist()

# Announcement vs Question
if text.startswith("давайте") and len(text) < 50:
    force_journalist()
📂 scripts/merge/ - Слияние и валидация
replica_merger.py
RUSSIAN_STOP_WORDS: set
🆕 v17.9: Множество из 104 грамматических слов русского языка.

Используется в _count_meaningful() для фильтрации N-грамм без семантической нагрузки.

python
RUSSIAN_STOP_WORDS = {
    "и", "в", "не", "на", "я", "что", "тот", "быть", "он",
    "с", "а", "как", "это", "но", "к", "у", "же", "из",
    "за", "то", "по", "все", "был", "была", "было", "были",
    "вот", "нет", "да", "уже", "ещё", "еще", "вы", "мы",
    # ... 104 слова
}
_count_meaningful(phrase: str) -> int
🆕 v17.9: Считает слова в фразе, не входящие в RUSSIAN_STOP_WORDS

Параметры:

phrase: Строка (N-грамма или произвольная фраза)

Возвращает: int — количество значимых слов

python
_count_meaningful("был. И вот")   # → 0  (все слова — стоп-слова)
_count_meaningful("немецкая артиллерия вправь")  # → 3
⚠️ Назначение: предотвращает добавление бессодержательных N-грамм
в seen[] внутри clean_loops() → исключает ложные срабатывания.

clean_loops(text: str) -> str
🔧 v17.9: Удаляет loop-артефакты (повторяющиеся N-граммы) из текста реплики

Параметры:

text: Текст одной реплики после merge

Возвращает: Очищенный текст

Алгоритм (v17.9):

python
MIN_MEANINGFUL_WORDS = 2

for ngram in sliding_window(text, N=4):
    meaningful_count = _count_meaningful(ngram)

    if meaningful_count < MIN_MEANINGFUL_WORDS:
        # Сохраняем в output, но НЕ добавляем в seen[]
        # → не может стать якорем для ложного fuzzy match
        output.append(ngram)
        continue

    if ngram in seen[] and fuzzy_sim(ngram, anchor) >= 0.75:
        # Реальный loop — удаляем
        skip()
    else:
        seen[ngram] = ngram
        output.append(ngram)
Граничный кейс (БАГ #27):

python
# До v17.9 — ОШИБКА:
# "не был. И вот немцы" → "не немцы" (удалено "был.")
# N-грамма "был. И вот" → sim=0.80 с якорем "было. и, в" → ложный loop

# После v17.9 — ПРАВИЛЬНО:
# "был. И вот" → _count_meaningful=0 → в seen[] не добавляется → не удаляется
Симуляция: tests/simulations/sim_bug27_clean_loops.py

merge_replicas(segments: List[Dict]) -> List[Dict]
Объединяет короткие реплики одного спикера

Условия слияния:

python
same_speaker and
pause < 3.0 and
same_raw_speaker_id and   # v16.0+
total_duration < 60
deduplicator.py
remove_cross_speaker_text_duplicates(segments: List[Dict]) -> List[Dict]
Удаляет дубликаты текста между разными спикерами

python
# До:
Журналист: "Да-да, понятно, да"
Эксперт:   "Да, понятно"  ← дубликат

# После:
Журналист: "Да-да, понятно, да"
Эксперт:   ""  ← удалён
deduplicate_segments(segments: List[Dict]) -> List[Dict]
Удаляет полностью идентичные сегменты

validator.py
validate_adjacent_same_speaker(segments: List[Dict]) -> List[Tuple[int, int]]
Проверяет смежные сегменты одного спикера

python
errors = validate_adjacent_same_speaker(segments)
# → [(5, 6), (12, 13)]
auto_merge_adjacent_same_speaker(segments: List[Dict]) -> List[Dict]
🔧 v16.0: Автоматически сливает смежные сегменты

python
if (same_speaker and
    same_raw_speaker_id and   # ← защита от неверного слияния
    pause < 3.0):
    merge()
generate_validation_report(segments: List[Dict], speaker_surname: str) -> Dict
Генерирует финальный отчёт валидации

Возвращает:

python
{
    "total_segments": 241,
    "speakers": {
        "Журналист": 152,
        "Эксперт":   89
    },
    "total_duration": "01:53:47",
    "avg_segment_duration": {
        "Журналист": 5.2,
        "Эксперт":   18.7
    },
    "errors_found": 0,
    "warnings": ["Long pause at 00:15:32 (15s)"]
}
📂 scripts/export/ - Экспорт данных
json_export.py
export_to_json(json_path, segments_raw, segments_merged, file_info, speaker_roles, validation_report, corrections_log)
Экспортирует данные в JSON

txt_export.py
export_to_txt(txt_path: Path, segments: List[Dict])
Экспортирует сегменты в TXT

Формат:

text
[HH:MM:SS.mmm] Спикер: Текст
jsons_to_txt(json_files: List[Path], txt_path: Path, speaker_surname: str)
Объединяет несколько JSON в один TXT

Последнее обновление: 2026-02-20