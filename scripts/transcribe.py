#!/usr/bin/env python3
"""
transcribe_v16.py - Главный файл пайплайна транскрибации v16.21

🔥 v16.21: Fix continuation phrase position check (90% → in-split check)
- Проверка позиции continuation phrase теперь ДО is_continuation_phrase()
- Исправлен баг: накопленный текст (current_text) должен включать текущее предложение
- Добавлен debug output: показ позиции и расстояния до конца
- Порог: если фраза ближе к началу (≤30% от длины) → считаем "началом"

🔥 v16.19: КРИТИЧЕСКИЙ FIX - Timestamps + Hallucinations + Continuation
- Вставка промежуточных timestamp в блоки >30 сек (insert_intermediate_timestamps)
- Исправление сдвига timestamp после gap filling (correct_timestamp_drift)
- Удаление дублей + "Продолжение следует" (filter_hallucination_segments)
- Порог continuation phrase: 80% → 90% (boundary_fixer.py)

🔥 v16.16: КРИТИЧЕСКИЙ FIX - Word Boundary в regex паттернах!
- Добавлен \\b (word boundary) в начале всех regex паттернов
- Исправлен баг: 'вы\\s+' ловил "вы " внутри слов (Невы, совы, кровы)
- Теперь поиск только целых слов: '\\bвы\\s+', '\\bрасскажите\\b' и т.д.
- Предотвращение FALSE POSITIVE в is_journalist_phrase() и is_expert_phrase()
- Исправлена ошибка: "То есть с небольшого пространства земли на восточном берегу Невы..." → Journalist=False ✅

🔥 v16.15: DEBUG OUTPUT ДЛЯ SPLIT - находим виновника!
- Детальный debug output для каждого предложения в split
- Показ результатов is_journalist_phrase, is_expert_phrase, is_continuation
- Логирование смены current_speaker с причиной
- Поможет найти КАКОЕ предложение ошибочно меняет спикера

🔥 v16.14: КРИТИЧЕСКИЙ FIX REPLICA MERGER - SPEAKER ОТ САМОГО ДЛИННОГО
- replica_merger теперь берёт speaker/raw_speaker_id от САМОГО ДЛИННОГО сегмента
- Исправлен баг: первый короткий сегмент "заражал" всю склейку
- Добавлен debug output с выбором доминирующего сегмента

🔥 v16.13: КРИТИЧЕСКИЙ FIX RAW_SPEAKER_ID SYNC В CLASSIFICATION
- speaker_classifier теперь синхронизирует raw_speaker_id при изменении speaker
- Передача speaker_roles в apply_speaker_classification_v15
- Исправлен баг: TXT выводил старый speaker после классификации
- Аналогичный фикс v16.12, но для этапа 7 (классификация)

🔥 v16.12: КРИТИЧЕСКИЙ FIX RAW_SPEAKER_ID + VERSION В JSON
- При split обновляется не только speaker, но и raw_speaker_id
- Добавлено поле "pipeline_version" в JSON metadata
- Исправлен баг: TXT выводил старый speaker вместо нового
- Передача speaker_roles в split_mixed_speaker_segments

🔥 v16.11: ПРАВИЛЬНАЯ ЛОГИКА CONTINUATION PHRASE FIX
- Исправлена логика проверки контекста в split_mixed_speaker_segments
- Continuation phrase проверяется ВНУТРИ текущего split (не предыдущий сегмент)
- Если накоплено >80 слов → continuation сохраняет текущего спикера
- Защита от смены спикера внутри длинного монолога

🔥 v16.8: DEBUG LOG + LONG MONOLOGUE FIX
- Автоматическое логирование всего pipeline в файл
- Monologue context protection для длинных монологов >60s
- Continuation phrase detection
- GAP overlap protection

🔥 v16.7: AUTO TEST-RESULTS COPY
- Автоматическое копирование результатов в test-results/latest/
- Очистка latest/ перед каждым запуском
- Логирование копирования

📁 СТРУКТУРА ПАПОК:
   Спикер (ДД.ММ)/
      audio/        ← WAV файлы здесь
      json/         ← JSON сохраняются сюда
      txt/          ← TXT сохраняется сюда
"""

import os
import sys
import whisper
import torch
import shutil
from pathlib import Path
from tqdm import tqdm
import warnings

# Добавляем текущую директорию в путь для импортов
sys.path.insert(0, str(Path(__file__).parent))

# Импорты модулей
from core.config import HF_TOKEN, VERSION, VERSION_NAME
from core.utils import (
    seconds_to_hms, parse_speaker_folder, adaptive_vad_threshold, gap_detector
)
from core.diarization import (
    diarize_audio, compute_speaker_stats, identify_speaker_roles, 
    align_segment_to_diarization
)
from core.alignment import align_whisper_with_diarization
from core.transcription import transcribe_audio, force_transcribe_diar_gaps

from corrections.hallucinations import (
    filter_hallucination_segments, clean_hallucinations_from_text
)
from corrections.speaker_classifier import apply_speaker_classification_v15
from corrections.boundary_fixer import (
    boundary_correction_raw, split_mixed_speaker_segments
)
from corrections.journalist_commands import detect_journalist_commands_cross_segment
from corrections.text_corrections import text_based_correction
from corrections.timestamp_fixer import (  # 🆕 v16.19
    insert_intermediate_timestamps, correct_timestamp_drift
)

from merge.replica_merger import merge_replicas
from merge.deduplicator import (
    remove_cross_speaker_text_duplicates, deduplicate_segments
)
from merge.validator import (
    validate_adjacent_same_speaker, auto_merge_adjacent_same_speaker,
    generate_validation_report
)

from export.json_export import export_to_json
from export.txt_export import export_to_txt, jsons_to_txt

from huggingface_hub import login

warnings.filterwarnings("ignore")

# ═══════════════════════════════════════════════════════════════════════════
# 🆕 v16.8: CONSOLE OUTPUT CAPTURE
# ═══════════════════════════════════════════════════════════════════════════

class TeeOutput:
    """
    Класс для дублирования stdout в файл и консоль одновременно
    (аналог Unix команды 'tee')
    """
    def __init__(self, filename):
        self.terminal = sys.stdout
        self.log = open(filename, 'w', encoding='utf-8')
    
    def write(self, message):
        self.terminal.write(message)
        self.log.write(message)
    
    def flush(self):
        self.terminal.flush()
        self.log.flush()
    
    def close(self):
        if self.log:
            self.log.close()

# ═══════════════════════════════════════════════════════════════════════════
# ВЕРСИЯ
# ═══════════════════════════════════════════════════════════════════════════

VERSION = "16.21"
VERSION_NAME = "Fix continuation phrase position check (90% → in-split check)"

# ═══════════════════════════════════════════════════════════════════════════
# ГЛОБАЛЬНАЯ ПЕРЕМЕННАЯ ДЛЯ PIPELINE
# ═══════════════════════════════════════════════════════════════════════════

_pipeline = None

def get_pipeline():
    """Ленивая инициализация pyannote pipeline"""
    global _pipeline
    if _pipeline is None:
        print("🤖 Загрузка pyannote pipeline...")
        from pyannote.audio import Pipeline
        _pipeline = Pipeline.from_pretrained("pyannote/speaker-diarization-3.1")
        if torch.cuda.is_available():
            _pipeline.to(torch.device("cuda"))
        print("✅ Pyannote готов (3.1)")
    return _pipeline

# ═══════════════════════════════════════════════════════════════════════════
# СОЗДАНИЕ СТРУКТУРЫ ПАПОК
# ═══════════════════════════════════════════════════════════════════════════

def ensure_folder_structure(base_folder):
    """
    Создаёт структуру папок audio/json/txt если их нет

    Args:
        base_folder: Path к папке спикера

    Returns:
        (audio_dir, json_dir, txt_dir)
    """
    audio_dir = base_folder / "audio"
    json_dir = base_folder / "json"
    txt_dir = base_folder / "txt"

    # Создаём папки если их нет
    json_dir.mkdir(exist_ok=True)
    txt_dir.mkdir(exist_ok=True)

    return audio_dir, json_dir, txt_dir

# ═══════════════════════════════════════════════════════════════════════════
# КОПИРОВАНИЕ В TEST-RESULTS
# 🆕 v16.7: Автоматическое копирование результатов для анализа AI
# ═══════════════════════════════════════════════════════════════════════════

def copy_to_test_results(json_files, txt_path, speaker_surname, log_path=None):
    """
    🆕 v16.18.1: Копирует результаты в test-results/latest/ БЕЗ переименования
    
    Сохраняет оригинальные имена файлов для удобства миграции в golden-dataset
    
    Args:
        json_files: Список путей к JSON файлам
        txt_path: Путь к TXT файлу
        speaker_surname: Фамилия спикера (не используется в v16.18.1+)
        log_path: Путь к LOG файлу (опционально)
    """
    # Путь к test-results/latest/ относительно scripts/
    script_dir = Path(__file__).parent
    project_root = script_dir.parent
    test_results_dir = project_root / "test-results" / "latest"
    
    # Проверяем существование папки
    if not test_results_dir.exists():
        print(f"\n⚠️ Папка test-results/latest/ не найдена, пропускаю копирование")
        return
    
    print(f"\n📊 Копирование в test-results/latest/...")
    
    # Очищаем latest/ (удаляем старые результаты)
    for old_file in test_results_dir.glob("*"):
        if old_file.is_file() and old_file.name != ".gitkeep":
            old_file.unlink()
            print(f"   🗑️ Удалён: {old_file.name}")
    
    # 🆕 v16.18.1: Копируем JSON файлы БЕЗ переименования
    copied_json = []
    for json_path in json_files:
        # Сохраняем оригинальное имя (например: NW_Uckpa0001_01.json)
        dest = test_results_dir / json_path.name
        shutil.copy2(json_path, dest)
        copied_json.append(dest.name)
        print(f"   ✅ JSON: {dest.name}")
    
    # 🆕 v16.18.1: Копируем TXT БЕЗ переименования
    if txt_path and txt_path.exists():
        # Сохраняем оригинальное имя (например: Исаев (02.02).txt)
        dest = test_results_dir / txt_path.name
        shutil.copy2(txt_path, dest)
        print(f"   ✅ TXT: {dest.name}")
    
    # Копируем LOG
    if log_path and log_path.exists():
        # LOG можно назвать по базовому имени TXT + "_debug.log"
        if txt_path:
            log_dest_name = txt_path.stem + "_debug.log"
        else:
            log_dest_name = "transcription_debug.log"
        
        dest = test_results_dir / log_dest_name
        shutil.copy2(log_path, dest)
        print(f"   ✅ LOG: {dest.name}")
    
    print(f"\n✅ Скопировано в test-results/latest/:")
    print(f"   - JSON: {len(copied_json)} файлов")
    print(f"   - TXT: 1 файл")
    if log_path and log_path.exists():
        print(f"   - LOG: 1 файл (debug)")
    
    print(f"\n💡 Файлы сохранены с оригинальными именами")
    print(f"   Готовы к копированию в golden-dataset (когда понадобится)")

# ═══════════════════════════════════════════════════════════════════════════
# ОСНОВНАЯ ФУНКЦИЯ ОБРАБОТКИ ОДНОГО ФАЙЛА
# ═══════════════════════════════════════════════════════════════════════════

def process_audio_file(
    wav_path,
    whisper_model,
    speaker_surname,
    json_dir,
    min_speakers=2,
    max_speakers=3,
    debug=False
):
    """
    Обрабатывает один аудио файл

    Args:
        wav_path: Path к WAV файлу
        whisper_model: Загруженная модель Whisper
        speaker_surname: Фамилия основного спикера
        json_dir: Директория для сохранения JSON
        min_speakers: Минимальное количество спикеров
        max_speakers: Максимальное количество спикеров
        debug: Режим отладки

    Returns:
        Path к созданному JSON файлу
    """
    print(f"\n🎤 {wav_path.name}")

    # Получаем pipeline
    pipeline = get_pipeline()

    # ═══════════════════════════════════════════════════════════════════════
    # ЭТАП 1: ДИАРИЗАЦИЯ
    # ═══════════════════════════════════════════════════════════════════════
    diarization = diarize_audio(pipeline, wav_path, min_speakers, max_speakers)

    if not diarization:
        print(f"  ❌ Диаризация не удалась")
        return None

    # Статистика спикеров
    stats = compute_speaker_stats(diarization)

    # ═══════════════════════════════════════════════════════════════════════
    # ЭТАП 2: ТРАНСКРИБАЦИЯ
    # ═══════════════════════════════════════════════════════════════════════
    audio_duration = max(turn.end for turn, _ in diarization.itertracks())
    vad_threshold = adaptive_vad_threshold(audio_duration)
    print(f"📏 Адаптивный VAD: {vad_threshold}")

    result = transcribe_audio(
        whisper_model,
        wav_path,
        language="ru",
        temperature=0.0,
        beam_size=5,
        vad_threshold=vad_threshold
    )

    if not result or not result.get("segments"):
        print("  ❌ Транскрибация не удалась")
        return None

    # ═══════════════════════════════════════════════════════════════════════
    # ЭТАП 3: ВЫРАВНИВАНИЕ С ДИАРИЗАЦИЕЙ
    # ═══════════════════════════════════════════════════════════════════════
    # Определяем роли спикеров
    speaker_roles = identify_speaker_roles(stats, result["segments"])

    # Выравниваем
    segments_raw = align_whisper_with_diarization(
        result["segments"],
        diarization,
        speaker_surname,
        speaker_roles
    )

    # ═══════════════════════════════════════════════════════════════════════
    # ЭТАП 4: КОРРЕКЦИИ
    # ═══════════════════════════════════════════════════════════════════════

    # 4.1 Детекция команд Журналиста
    segments_raw, cmd_corrections = detect_journalist_commands_cross_segment(
        segments_raw, speaker_surname
    )

    # 4.2 Boundary correction
    segments_raw = boundary_correction_raw(
        segments_raw, speaker_surname, speaker_roles
    )

    # 4.3 Cross-speaker deduplication
    print("\n🔄 Cross-speaker deduplication...")
    segments_raw = remove_cross_speaker_text_duplicates(segments_raw)
    print(f"✅ После cross-speaker dedup: {len(segments_raw)} сегментов")

    # 4.4 Дедупликация
    print("\n🔄 Дедупликация сегментов...")
    segments_raw = deduplicate_segments(segments_raw)
    print(f"✅ После дедупликации: {len(segments_raw)} сегментов")

    # ═══════════════════════════════════════════════════════════════════════
    # ЭТАП 5: GAPS (если есть)
    # 🆕 v16.5: Умная атрибуция GAP_FILLED по семантическому сходству
    # ═══════════════════════════════════════════════════════════════════════
    gaps = gap_detector(segments_raw, threshold=3.0)
    gap_segments = []

    if gaps:
        print(f"\n🔍 ГАПЫ WHISPER:")
        for gap in gaps:
            print(f"   🚨 GAP {gap['gap_hms_start']}–{gap['gap_hms_end']} ({gap['duration']}s)")

        # Force transcribe gaps (v16.5: умная атрибуция)
        gap_segments = force_transcribe_diar_gaps(
            whisper_model, wav_path, gaps, segments_raw, speaker_surname
        )

        if gap_segments:
            print(f"  ✅ Добавлено из gaps: {len(gap_segments)} сегментов")
            segments_raw.extend(gap_segments)
            segments_raw.sort(key=lambda x: x["start"])

    # ═══════════════════════════════════════════════════════════════════════
    # 🆕 v16.19: ЭТАП 5.2 - TIMESTAMP CORRECTION после gap filling
    # ═══════════════════════════════════════════════════════════════════════
    segments_raw = correct_timestamp_drift(segments_raw, debug=True)

    # ═══════════════════════════════════════════════════════════════════════
    # ЭТАП 6: MERGE REPLICAS
    # ═══════════════════════════════════════════════════════════════════════
    segments_merged = merge_replicas(segments_raw, debug=True) # 🆕 v16.20: добавлен debug=True

    # ═══════════════════════════════════════════════════════════════════════
    # 🆕 v16.19: ЭТАП 6.1 - TIMESTAMP INJECTION в блоки >30 сек
    # ═══════════════════════════════════════════════════════════════════════
    segments_merged = insert_intermediate_timestamps(segments_merged, interval=30.0, debug=True)

    # ═══════════════════════════════════════════════════════════════════════
    # ЭТАП 7: SPEAKER CLASSIFICATION v15
    # 🆕 v16.13: Передача speaker_roles для синхронизации raw_speaker_id
    # ═══════════════════════════════════════════════════════════════════════
    print("\n" + "="*70)
    print("🎯 v15: Применяем весовую классификацию спикеров (v16.13)...")
    print("="*70)
    segments_merged, classification_stats = apply_speaker_classification_v15(
        segments_merged, speaker_surname, speaker_roles, debug=True  # 🆕 v16.13: передаём speaker_roles
    )
    print("="*70)
    print()

    # ═══════════════════════════════════════════════════════════════════════
    # ЭТАП 8: TEXT-BASED CORRECTIONS
    # 🆕 v16.12: Передача speaker_roles в split для обратной конвертации
    # 🆕 v16.11: Правильная логика continuation phrase fix
    # 🆕 v16.4: Расширенная защита от переатрибуции анонсов вопросов
    # ═══════════════════════════════════════════════════════════════════════
    print("\n✂️ Разделение mixed-speaker сегментов (v16.21)...")
    segments_merged = split_mixed_speaker_segments(
        segments_merged, speaker_surname, speaker_roles  # 🆕 v16.12: передаём speaker_roles
    )
    
    print("\n🔍 Text-based correction (v16.4)...")
    segments_merged = text_based_correction(segments_merged, speaker_surname)

    # ═══════════════════════════════════════════════════════════════════════
    # 🆕 v16.19: ЭТАП 8.1 - HALLUCINATION REMOVAL
    # ═══════════════════════════════════════════════════════════════════════
    segments_merged = filter_hallucination_segments(segments_merged, debug=True)

    # ═══════════════════════════════════════════════════════════════════════
    # ЭТАП 9: ВАЛИДАЦИЯ + AUTO-MERGE
    # 🆕 v16.0: Проверка raw_speaker_id перед слиянием
    # ═══════════════════════════════════════════════════════════════════════
    errors = validate_adjacent_same_speaker(segments_merged)

    if errors:
        segments_merged = auto_merge_adjacent_same_speaker(segments_merged)
        validate_adjacent_same_speaker(segments_merged)

    # ═══════════════════════════════════════════════════════════════════════
    # ЭТАП 10: ЭКСПОРТ
    # ═══════════════════════════════════════════════════════════════════════
    validation_report = generate_validation_report(segments_merged, speaker_surname)

    file_info = {
        "filename": wav_path.name,
        "duration": audio_duration,
        "speaker_surname": speaker_surname,
        "whisper_model": "large-v3-turbo",
        "vad_threshold": vad_threshold,
        "gaps_detected": len(gaps),
        "gaps_final": len(gaps),
        "retry_added": len(gap_segments),
        "speaker_stats": dict(stats),
        "pipeline_version": VERSION,  # 🆕 v16.12: версия в metadata
        "params": {
            "model_name": "large-v3-turbo",
            "language": "ru",
            "min_speakers": min_speakers,
            "max_speakers": max_speakers
        }
    }

    corrections_log = {
        "journalist_commands_detected": len(cmd_corrections),
        "journalist_commands_details": cmd_corrections
    }

    json_path = json_dir / f"{wav_path.stem}.json"
    export_to_json(
        json_path,
        segments_raw,
        segments_merged,
        file_info,
        speaker_roles,
        validation_report,
        corrections_log
    )

    print(f" ✅ {json_path.name} (v{VERSION}, roles={speaker_roles})")
    return json_path

# ═══════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════

def main():
    """
    Главная функция - интерактивный режим
    
    Returns:
        (json_files, txt_path, speaker_surname) для копирования в test-results
    """

    # Инициализация
    login(token=HF_TOKEN)

    print(f"🔥 ПАЙПЛАЙН v{VERSION}: {VERSION_NAME}")
    print(f"GPU: {'✅ CUDA' if torch.cuda.is_available() else '⚠️ CPU'}")
    print("=" * 70)
    print()
    print("💡 v16.21 ИЗМЕНЕНИЯ:")
    print("   ✅ КРИТИЧЕСКИЙ FIX: Проверка позиции continuation phrase")
    print("   ✅ Накопленный текст теперь включает текущее предложение")
    print("   ✅ Threshold: если фраза ближе к началу (≤30%) → считаем \"началом\"")
    print("   ✅ Debug: показ позиции и расстояния до конца текста")
    print()
    print("💡 v16.19 ИЗМЕНЕНИЯ:")
    print("   ✅ ЭТАП 5.2: Исправление сдвига timestamp после gap filling")
    print("   ✅ ЭТАП 6.1: Вставка промежуточных timestamp в блоки >30 сек")
    print("   ✅ ЭТАП 8.1: Удаление дублей + 'Продолжение следует'")
    print("   ✅ Continuation phrase threshold: 80% → 90%")
    print()
    print("💡 v16.12 ИЗМЕНЕНИЯ:")
    print("   ✅ КРИТИЧЕСКИЙ FIX: raw_speaker_id обновляется при split")
    print("   ✅ Создан обратный маппинг speaker_roles (Исаев → SPEAKER_01)")
    print("   ✅ Исправлен баг: TXT выводил старый speaker вместо нового")
    print("   ✅ Добавлено поле pipeline_version в JSON metadata")
    print()
    print("💡 v16.11 ИЗМЕНЕНИЯ:")
    print("   ✅ ПРАВИЛЬНАЯ логика continuation phrase fix")
    print("   ✅ Проверка контекста ВНУТРИ текущего split (не предыдущий сегмент)")
    print()

    # Запрос пути к папке
    folder_path = input("📂 Путь к папке спикера (\\\\  или /): ").strip().replace('"', '')
    folder = Path(folder_path)

    if not folder.exists():
        print("❌ Папка не найдена!")
        return None, None, None

    print(f"✅ Папка: {folder}")

    # Создаём структуру папок
    audio_dir, json_dir, txt_dir = ensure_folder_structure(folder)

    if not audio_dir.exists():
        print(f"❌ Папка audio/ не найдена! Создай: {audio_dir}")
        return None, None, None

    print(f"📁 audio/: {audio_dir}")
    print(f"📁 json/:  {json_dir}")
    print(f"📁 txt/:   {txt_dir}")

    # Выбор режима
    mode = input("\n⚙️ Режим [точный]: ").strip().lower() or "точный"
    print(f"\n🚀 Режим: {mode} (v{VERSION})")

    # Загрузка Whisper
    print("\n🤖 Загрузка Whisper large-v3-turbo...")
    whisper_model = whisper.load_model("large-v3-turbo")
    print("✅ Whisper готов")

    # Парсинг имени спикера
    speaker_surname, date, full_name = parse_speaker_folder(folder.name)
    print(f"\n👤 '{folder.name}' → {full_name}.txt")
    print(f"🤖 large-v3-turbo + pyannote v{VERSION}...")

    # Поиск WAV файлов в audio/
    wav_files = sorted(audio_dir.glob("*.wav"))

    if not wav_files:
        print(f"❌ WAV файлы не найдены в {audio_dir}!")
        return None, None, None

    print(f"\n✅ Найдено WAV: {len(wav_files)}")

    json_files = []

    # Обработка файлов
    for wav_path in tqdm(wav_files, desc="JSON + Диаризация"):
        json_path = process_audio_file(
            wav_path,
            whisper_model,
            speaker_surname,
            json_dir,
            min_speakers=2,
            max_speakers=3,
            debug=True
        )

        if json_path:
            json_files.append(json_path)

    print(f"\n✅ JSON: {len(json_files)}/{len(wav_files)}")

    # Создание TXT
    txt_path = None
    if json_files:
        txt_path = txt_dir / f"{full_name}.txt"
        print(f"\n📄 {len(json_files)} JSON → {txt_path.name}")
        jsons_to_txt(json_files, txt_path, speaker_surname)
        print(f"✅ TXT: {txt_path} (v{VERSION})")

    print(f"\n✅ Готово! 🚀 (v{VERSION})")
    print(f"\n📂 Результаты:")
    print(f"   JSON: {json_dir}")
    print(f"   TXT:  {txt_dir}")
    
    # Возвращаем данные для копирования в test-results
    return json_files, txt_path, speaker_surname

if __name__ == "__main__":
    # 🆕 v16.8: Захват console output в файл
    log_file = Path.cwd() / "transcription_debug.log"
    
    # Создаём tee для stdout
    tee = TeeOutput(log_file)
    original_stdout = sys.stdout
    sys.stdout = tee
    
    json_files = None
    txt_path = None
    speaker_surname = None
    
    try:
        # Запускаем main и получаем результаты
        json_files, txt_path, speaker_surname = main()
    finally:
        # Восстанавливаем stdout и закрываем файл
        sys.stdout = original_stdout
        tee.close()
        
        # ✅ v16.8.1: Копирование ПОСЛЕ закрытия файла
        if json_files and txt_path and log_file.exists():
            print(f"\n💾 DEBUG log сохранён: {log_file}")
            copy_to_test_results(json_files, txt_path, speaker_surname, log_file)
        else:
            print(f"\n💾 DEBUG log сохранён: {log_file}")
            print("   TEST: Копирование в test-results пропущено")
