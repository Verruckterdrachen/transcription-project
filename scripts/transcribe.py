#!/usr/bin/env python3
"""
transcribe_v16.py - Главный файл пайплайна транскрибации v16.5

🔥 v16.5: SMART GAP ATTRIBUTION
- FIX #1: GAP_FILLED умная атрибуция по семантическому сходству
- FIX #2: Защита от атрибуции запинок/переформулировок предыдущему спикеру
- FIX #3: text_similarity() используется из utils.py для анализа GAP

🔥 v16.4: SPEAKER ATTRIBUTION PROTECTION
- FIX #1: split_mixed_speaker_segments — пересчет таймкодов после разделения
- FIX #2: text_based_correction — защита от переатрибуции анонсов вопросов
- FIX #3: Context window protection — не трогать сегменты внутри монологов >60s
- FIX #4: Confirmation pattern detection — детекция подтверждений ("Ну да", "Да-да")
- FIX #5: Announcement vs Question — различение анонса и полного вопроса

v16.0 (базовые исправления):
- FIX #1: text_based_correction — защита от переатрибуции с маркерами Журналиста
- FIX #2: "Давайте снять" НЕ удаляется (убран из patterns)
- FIX #3: force_transcribe — no_speech_threshold 0.3→0.2 (меньше пропусков)
- FIX #4: auto_merge — НЕ склеивает сегменты с разными raw_speaker_id
- DEBUG: Сохранение промежуточных JSON на каждом этапе

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
# ВЕРСИЯ
# ═══════════════════════════════════════════════════════════════════════════

VERSION = "16.5"
VERSION_NAME = "Smart GAP Attribution"

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
    # ЭТАП 6: MERGE REPLICAS
    # ═══════════════════════════════════════════════════════════════════════
    segments_merged = merge_replicas(segments_raw)

    # ═══════════════════════════════════════════════════════════════════════
    # ЭТАП 7: SPEAKER CLASSIFICATION v15
    # ═══════════════════════════════════════════════════════════════════════
    print("\n" + "="*70)
    print("🎯 v15: Применяем весовую классификацию спикеров...")
    print("="*70)
    segments_merged, classification_stats = apply_speaker_classification_v15(
        segments_merged, speaker_surname, debug=True
    )
    print("="*70)
    print()

    # ═══════════════════════════════════════════════════════════════════════
    # ЭТАП 8: TEXT-BASED CORRECTIONS
    # 🆕 v16.4: Расширенная защита от переатрибуции анонсов вопросов
    # ═══════════════════════════════════════════════════════════════════════
    print("\n✂️ Разделение mixed-speaker сегментов (v16.4)...")
    segments_merged = split_mixed_speaker_segments(segments_merged, speaker_surname)
    
    print("\n🔍 Text-based correction (v16.4)...")
    segments_merged = text_based_correction(segments_merged, speaker_surname)

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

    print(f" ✅ {json_path.name} (roles={speaker_roles})")
    return json_path

# ═══════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════

def main():
    """Главная функция - интерактивный режим"""

    # Инициализация
    login(token=HF_TOKEN)

    print(f"🔥 ПАЙПЛАЙН v{VERSION}: {VERSION_NAME}")
    print(f"GPU: {'✅ CUDA' if torch.cuda.is_available() else '⚠️ CPU'}")
    print("=" * 70)
    print()
    print("💡 v16.5 ИЗМЕНЕНИЯ:")
    print("   ✅ FIX: GAP_FILLED — умная атрибуция по семантическому сходству")
    print("   ✅ FIX: Защита от атрибуции запинок предыдущему спикеру")
    print("   ✅ FIX: text_similarity() используется для анализа GAP")
    print()
    print("💡 v16.4 ИЗМЕНЕНИЯ:")
    print("   ✅ FIX: split_mixed_speaker_segments — пересчет таймкодов")
    print("   ✅ FIX: text_based_correction — защита от анонсов вопросов")
    print("   ✅ FIX: Context window protection (монологи >60s)")
    print("   ✅ FIX: Confirmation pattern detection (\"Ну да\", \"Да-да\")")
    print("   ✅ FIX: Announcement vs Question distinction")
    print()
    print("💡 v16.0 БАЗОВЫЕ ИЗМЕНЕНИЯ:")
    print("   ✅ FIX: text_based_correction — защита от неверной атрибуции")
    print("   ✅ FIX: \"Давайте снять\" НЕ удаляется")
    print("   ✅ FIX: force_transcribe — no_speech 0.2 (было 0.3)")
    print("   ✅ FIX: auto_merge — проверка raw_speaker_id")
    print("   ✅ Структура папок: audio/ → json/ + txt/")
    print()

    # Запрос пути к папке
    folder_path = input("📂 Путь к папке спикера (\\\\\\\\  или /): ").strip().replace('"', '')
    folder = Path(folder_path)

    if not folder.exists():
        print("❌ Папка не найдена!")
        return

    print(f"✅ Папка: {folder}")

    # Создаём структуру папок
    audio_dir, json_dir, txt_dir = ensure_folder_structure(folder)

    if not audio_dir.exists():
        print(f"❌ Папка audio/ не найдена! Создай: {audio_dir}")
        return

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
        return

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
    if json_files:
        txt_path = txt_dir / f"{full_name}.txt"
        print(f"\n📄 {len(json_files)} JSON → {txt_path.name}")
        jsons_to_txt(json_files, txt_path, speaker_surname)
        print(f"✅ TXT: {txt_path} (v{VERSION})")

    print(f"\n✅ Готово! 🚀 (v{VERSION})")
    print(f"\n📂 Результаты:")
    print(f"   JSON: {json_dir}")
    print(f"   TXT:  {txt_dir}")

if __name__ == "__main__":
    main()
