"""
transcribe_de.py — Оркестратор пайплайна транскрибации для немецкого языка (DE)

Отличия от transcribe.py (русский пайплайн):
  - language = "de" для Whisper (основная транскрибация + GAP filling)
  - min_speakers=1, max_speakers=1 — один диктор, без поиска журналиста
  - speaker_surname = "Диктор" (фиксировано, не парсится из имени папки)
  - Все остальные модули (dedup, gaps, timestamps, merge, export) — без изменений

Пайплайн (идентичен transcribe.py по этапам):
  1. Диаризация (pyannote 3.1) — один спикер
  2. Транскрибация (Whisper large-v3-turbo, language=de)
  3. Выравнивание Whisper ↔ Pyannote
  4. Коррекции (dedup — без журналист-логики)
  5. GAP filling (language=de) + timestamp correction
  6. Merge реплик
  7. Split длинных сегментов
  8. Timestamp injection (>30s)
  9. Hallucination removal
  10. Валидация + auto-merge
  11. Экспорт (JSON + TXT)

Tech: Whisper large-v3-turbo, Pyannote 3.1, Python 3.10+
"""

import re
import os
import sys
import whisper
import torch
import shutil
from pathlib import Path
from tqdm import tqdm
import warnings

sys.path.insert(0, str(Path(__file__).parent))

from core.config import HF_TOKEN, VERSION, VERSION_NAME
from core.utils import (
    seconds_to_hms, adaptive_vad_threshold, gap_detector
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
from corrections.boundary_fixer import split_mixed_speaker_segments
from corrections.timestamp_fixer import (
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

from core.logging_utils import TeeOutput, set_tee, switch_log_phase

from huggingface_hub import login

warnings.filterwarnings("ignore")

# ═══════════════════════════════════════════════════════════════════════════
# КОНСТАНТЫ НЕМЕЦКОГО ПРОФИЛЯ
# ═══════════════════════════════════════════════════════════════════════════

LANGUAGE = "de"
SPEAKER_LABEL = "Диктор"   # фиксированная метка для единственного спикера
MIN_SPEAKERS = 1
MAX_SPEAKERS = 1

# ═══════════════════════════════════════════════════════════════════════════
# DEBUG CHECKPOINT (идентичен transcribe.py)
# ═══════════════════════════════════════════════════════════════════════════

_DEBUG_TARGET_TIMESTAMPS: list = []
_DEBUG_TARGET_PHRASE: str | None = None

def debug_checkpoint(segments, stage_name,
                     target_timestamps=None, target_phrase=None):
    if target_timestamps is None:
        target_timestamps = _DEBUG_TARGET_TIMESTAMPS
    if target_phrase is None:
        target_phrase = _DEBUG_TARGET_PHRASE

    print(f"\n🔍 CHECKPOINT [{stage_name}]: {len(segments)} сегментов")

    for target_ts in target_timestamps:
        found = False
        for seg in segments:
            seg_start = seconds_to_hms(seg['start'])
            seg_end   = seconds_to_hms(seg['end'])

            if seg_start <= target_ts <= seg_end or seg_start == target_ts:
                found = True
                text     = seg.get('text', '')
                duration = seg['end'] - seg['start']

                print(f"   ✅ {target_ts}: НАЙДЕН в [{seg_start}-{seg_end}] "
                      f"(длит={duration:.1f}s, слов={len(text.split())})")

                if len(text) > 120:
                    print(f"      📝 Начало: \"{text[:60]}...\"")
                    print(f"      📝 Конец:  \"...{text[-60:]}\"")
                else:
                    print(f"      📝 Текст: \"{text}\"")

                if target_phrase:
                    if target_phrase.lower() in text.lower():
                        print(f"      ✅ Фраза \"{target_phrase}\" — НАЙДЕНА")
                    else:
                        print(f"      ❌ Фраза \"{target_phrase}\" — НЕ НАЙДЕНА")
                break

        if not found:
            print(f"   ❌ {target_ts}: НЕ НАЙДЕН!")

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
# СОЗДАНИЕ СТРУКТУРЫ ПАПОК (идентично transcribe.py)
# ═══════════════════════════════════════════════════════════════════════════

def ensure_folder_structure(base_folder):
    audio_dir = base_folder / "audio"
    json_dir  = base_folder / "json"
    txt_dir   = base_folder / "txt"
    json_dir.mkdir(exist_ok=True)
    txt_dir.mkdir(exist_ok=True)
    return audio_dir, json_dir, txt_dir

# ═══════════════════════════════════════════════════════════════════════════
# КОПИРОВАНИЕ В TEST-RESULTS (идентично transcribe.py)
# ═══════════════════════════════════════════════════════════════════════════

def copy_to_test_results(json_files, txt_path, speaker_label, log_path=None):
    script_dir       = Path(__file__).parent
    project_root     = script_dir.parent
    test_results_dir = project_root / "test-results" / "latest"

    if not test_results_dir.exists():
        print(f"\n⚠️ Папка test-results/latest/ не найдена, пропускаю копирование")
        return

    print(f"\n📊 Копирование в test-results/latest/...")

    for old_file in test_results_dir.glob("*"):
        if old_file.is_file() and old_file.name != ".gitkeep":
            old_file.unlink()
            print(f"   🗑️ Удалён: {old_file.name}")

    log_subdir = test_results_dir / "log"
    if log_subdir.exists():
        shutil.rmtree(log_subdir)
        print(f"   🗑️ Очищена папка log/")

    local_log_dir = Path.cwd() / "log"
    if local_log_dir.exists():
        shutil.copytree(local_log_dir, log_subdir)
        count = len(list(log_subdir.glob("*.log")))
        print(f"   ✅ log/: {count} файлов")

    copied_json = []
    for json_path in json_files:
        dest = test_results_dir / json_path.name
        shutil.copy2(json_path, dest)
        copied_json.append(dest.name)
        print(f"   ✅ JSON: {dest.name}")

    if txt_path and txt_path.exists():
        dest = test_results_dir / txt_path.name
        shutil.copy2(txt_path, dest)
        print(f"   ✅ TXT: {dest.name}")

    if log_path and log_path.exists():
        log_dest_name = (txt_path.stem + "_debug.log") if txt_path else "transcription_debug.log"
        dest = test_results_dir / log_dest_name
        shutil.copy2(log_path, dest)
        print(f"   ✅ LOG: {dest.name}")

    print(f"\n✅ Скопировано в test-results/latest/: JSON={len(copied_json)}, TXT=1")

# ═══════════════════════════════════════════════════════════════════════════
# ОСНОВНАЯ ФУНКЦИЯ ОБРАБОТКИ ОДНОГО ФАЙЛА
# ═══════════════════════════════════════════════════════════════════════════

def process_audio_file_de(
    wav_path,
    whisper_model,
    json_dir,
    debug=False
):
    """
    Обрабатывает один аудио файл немецкого диктора.

    Отличия от process_audio_file() в transcribe.py:
    - language="de" передаётся в transcribe_audio() и force_transcribe_diar_gaps()
    - min_speakers=1, max_speakers=1 (один диктор)
    - speaker_surname=SPEAKER_LABEL ("Диктор") — фиксированная метка
    - НЕ вызываются: apply_speaker_classification_v15, boundary_correction_raw,
      detect_journalist_commands_cross_segment, text_based_correction
      (все они заточены под русский диалог журналист/эксперт)

    Args:
        wav_path:      Path к WAV файлу
        whisper_model: Загруженная модель Whisper
        json_dir:      Директория для сохранения JSON
        debug:         Режим отладки

    Returns:
        Path к созданному JSON файлу или None при ошибке
    """
    print(f"\n🎤 {wav_path.name}")

    pipeline = get_pipeline()

    log_base = Path.cwd() / "log"
    stem = wav_path.stem
    switch_log_phase(log_base / f"{stem}_01_diarization.log")

    # ═══════════════════════════════════════════════════════════════════════
    # ЭТАП 1: ДИАРИЗАЦИЯ (один спикер)
    # ═══════════════════════════════════════════════════════════════════════
    diarization = diarize_audio(pipeline, wav_path, MIN_SPEAKERS, MAX_SPEAKERS)

    if not diarization:
        print(f"  ❌ Диаризация не удалась")
        return None

    stats = compute_speaker_stats(diarization)

    # speaker_roles: все метки pyannote → SPEAKER_LABEL
    speaker_roles = {label: SPEAKER_LABEL for label in stats.keys()}
    print(f"  ℹ️ Роли спикеров (DE): {speaker_roles}")

    # ═══════════════════════════════════════════════════════════════════════
    # ЭТАП 2: ТРАНСКРИБАЦИЯ (language=de)
    # ═══════════════════════════════════════════════════════════════════════
    audio_duration = max(turn.end for turn, _ in diarization.itertracks())
    vad_threshold  = adaptive_vad_threshold(audio_duration)
    print(f"📏 Адаптивный VAD: {vad_threshold}")

    result = transcribe_audio(
        whisper_model,
        wav_path,
        language=LANGUAGE,
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
    segments_raw = align_whisper_with_diarization(
        result["segments"],
        diarization,
        SPEAKER_LABEL,
        speaker_roles
    )

    debug_checkpoint(segments_raw, "AFTER ALIGNMENT")

    switch_log_phase(log_base / f"{stem}_02_alignment.log")

    # ═══════════════════════════════════════════════════════════════════════
    # ЭТАП 4: КОРРЕКЦИИ (только dedup — без журналист-логики)
    # ═══════════════════════════════════════════════════════════════════════
    print("\n🔄 Cross-speaker deduplication...")
    segments_raw = remove_cross_speaker_text_duplicates(segments_raw)
    print(f"✅ После cross-speaker dedup: {len(segments_raw)} сегментов")

    debug_checkpoint(segments_raw, "AFTER CROSS-SPEAKER DEDUP")

    print("\n🔄 Дедупликация сегментов...")
    segments_raw = deduplicate_segments(segments_raw)
    print(f"✅ После дедупликации: {len(segments_raw)} сегментов")

    debug_checkpoint(segments_raw, "AFTER DEDUPLICATION")

    # ═══════════════════════════════════════════════════════════════════════
    # ЭТАП 5: GAP FILLING (language=de)
    # ═══════════════════════════════════════════════════════════════════════
    gaps         = gap_detector(segments_raw, threshold=3.0)
    gap_segments = []

    if gaps:
        print(f"\n🔍 ГАПЫ WHISPER:")
        for gap in gaps:
            print(f"   🚨 GAP {gap['gap_hms_start']}–{gap['gap_hms_end']} ({gap['duration']}s)")

        gap_segments = force_transcribe_diar_gaps(
            whisper_model, wav_path, gaps, segments_raw, SPEAKER_LABEL,
            diarization=diarization,
            speaker_roles=speaker_roles,
            language=LANGUAGE   # 🆕 v17.25: передаём DE
        )

        if gap_segments:
            print(f"  ✅ Добавлено из gaps: {len(gap_segments)} сегментов")
            segments_raw.extend(gap_segments)
            segments_raw.sort(key=lambda x: x["start"])
            debug_checkpoint(segments_raw, "AFTER GAP FILLING")

    # ═══════════════════════════════════════════════════════════════════════
    # ЭТАП 5.2: TIMESTAMP CORRECTION
    # ═══════════════════════════════════════════════════════════════════════
    segments_raw = correct_timestamp_drift(segments_raw, debug=True)
    debug_checkpoint(segments_raw, "AFTER TIMESTAMP CORRECTION")

    switch_log_phase(log_base / f"{stem}_03_merges.log")

    # ═══════════════════════════════════════════════════════════════════════
    # ЭТАП 6: MERGE REPLICAS
    # ═══════════════════════════════════════════════════════════════════════
    segments_merged = merge_replicas(segments_raw, debug=True)
    debug_checkpoint(segments_merged, "AFTER MERGE")

    switch_log_phase(log_base / f"{stem}_04_postprocess.log")

    # ═══════════════════════════════════════════════════════════════════════
    # ЭТАП 7: SPLIT длинных сегментов
    # (speaker_classifier и text_based_correction пропущены — DE не нужны)
    # ═══════════════════════════════════════════════════════════════════════
    print("\n✂️ Разделение mixed-speaker сегментов...")
    segments_merged = split_mixed_speaker_segments(
        segments_merged, SPEAKER_LABEL, speaker_roles
    )
    debug_checkpoint(segments_merged, "AFTER SPLIT")

    # ═══════════════════════════════════════════════════════════════════════
    # ЭТАП 8: TIMESTAMP INJECTION (>30s)
    # ═══════════════════════════════════════════════════════════════════════
    segments_merged = insert_intermediate_timestamps(
        segments_merged, interval=30.0, debug=True
    )
    debug_checkpoint(segments_merged, "AFTER TIMESTAMP INJECTION")

    # ═══════════════════════════════════════════════════════════════════════
    # ЭТАП 9: HALLUCINATION REMOVAL
    # ═══════════════════════════════════════════════════════════════════════
    segments_merged = filter_hallucination_segments(segments_merged, debug=True)
    debug_checkpoint(segments_merged, "AFTER HALLUCINATION REMOVAL")

    # ═══════════════════════════════════════════════════════════════════════
    # ЭТАП 10: ВАЛИДАЦИЯ + AUTO-MERGE
    # ═══════════════════════════════════════════════════════════════════════
    errors = validate_adjacent_same_speaker(segments_merged)

    if errors:
        segments_merged = auto_merge_adjacent_same_speaker(segments_merged)
        validate_adjacent_same_speaker(segments_merged)

        for seg in segments_merged:
            seg['text'] = re.sub(r'\s*\b\d{2}:\d{2}:\d{2}\b\s*', ' ', seg['text']).strip()

        segments_merged = insert_intermediate_timestamps(
            segments_merged, interval=30.0, debug=True
        )
        debug_checkpoint(segments_merged, "AFTER AUTO-MERGE")

    # ═══════════════════════════════════════════════════════════════════════
    # ЭТАП 11: ЭКСПОРТ
    # ═══════════════════════════════════════════════════════════════════════
    debug_checkpoint(segments_merged, "BEFORE EXPORT (FINAL)")

    validation_report = generate_validation_report(segments_merged, SPEAKER_LABEL)

    file_info = {
        "filename":       wav_path.name,
        "duration":       audio_duration,
        "speaker_surname": SPEAKER_LABEL,
        "whisper_model":  "large-v3-turbo",
        "vad_threshold":  vad_threshold,
        "gaps_detected":  len(gaps),
        "gaps_final":     len(gaps),
        "retry_added":    len(gap_segments),
        "speaker_stats":  dict(stats),
        "pipeline_version": VERSION,
        "params": {
            "model_name":   "large-v3-turbo",
            "language":     LANGUAGE,
            "min_speakers": MIN_SPEAKERS,
            "max_speakers": MAX_SPEAKERS,
        }
    }

    corrections_log = {
        "journalist_commands_detected": 0,
        "journalist_commands_details":  []
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

    print(f" ✅ {json_path.name} (v{VERSION}, lang={LANGUAGE})")
    return json_path

# ═══════════════════════════════════════════════════════════════════════════
# MAIN
# ═══════════════════════════════════════════════════════════════════════════

def main():
    global _DEBUG_TARGET_TIMESTAMPS, _DEBUG_TARGET_PHRASE
    _DEBUG_TARGET_TIMESTAMPS = []
    _DEBUG_TARGET_PHRASE     = None

    login(token=HF_TOKEN)

    folder_path = input("📂 Путь к папке с немецким аудио (\\\\ или /): ").strip().replace('"', '')
    folder = Path(folder_path)

    if not folder.exists():
        print("❌ Папка не найдена!")
        return None, None, None

    print(f"✅ Папка: {folder}")
    print(f"🇩🇪 Язык: {LANGUAGE} | Спикер: {SPEAKER_LABEL}")

    audio_dir, json_dir, txt_dir = ensure_folder_structure(folder)

    if not audio_dir.exists():
        print(f"❌ Папка audio/ не найдена! Создай: {audio_dir}")
        return None, None, None

    print(f"📁 audio/: {audio_dir}")
    print(f"📁 json/:  {json_dir}")
    print(f"📁 txt/:   {txt_dir}")
    print(f"\n🚀 Режим: DE одиночный диктор (v{VERSION})")

    print("\n🤖 Загрузка Whisper large-v3-turbo...")
    whisper_model = whisper.load_model("large-v3-turbo")
    print("✅ Whisper готов")

    # Имя TXT файла берём из имени папки (без парсинга даты)
    folder_clean = folder.name
    txt_filename = f"{folder_clean}.txt"

    print(f"\n👤 Папка: '{folder_clean}' → {txt_filename}")
    print(f"🤖 large-v3-turbo + pyannote v{VERSION} [DE]...")

    wav_files = sorted(audio_dir.glob("*.wav"))

    if not wav_files:
        print(f"❌ WAV файлы не найдены в {audio_dir}!")
        return None, None, None

    print(f"\n✅ Найдено WAV: {len(wav_files)}")

    json_files = []

    for wav_path in tqdm(wav_files, desc="JSON + Диаризация [DE]"):
        json_path = process_audio_file_de(
            wav_path,
            whisper_model,
            json_dir,
            debug=True
        )
        if json_path:
            json_files.append(json_path)

    print(f"\n✅ JSON: {len(json_files)}/{len(wav_files)}")

    txt_path = None
    if json_files:
        txt_path = txt_dir / txt_filename
        print(f"\n📄 {len(json_files)} JSON → {txt_path.name}")
        jsons_to_txt(json_files, txt_path, SPEAKER_LABEL)
				raw = txt_path.read_text(encoding="utf-8")
				cleaned = re.sub(r'^(\d{2}:\d{2}:\d{2}) Диктор: ', r'\1 ', raw, flags=re.MULTILINE)
				txt_path.write_text(cleaned, encoding="utf-8")
        print(f"✅ TXT: {txt_path} (v{VERSION})")

    print(f"\n✅ Готово! 🚀 (v{VERSION}, lang={LANGUAGE})")
    print(f"\n📂 Результаты:")
    print(f"   JSON: {json_dir}")
    print(f"   TXT:  {txt_dir}")

    return json_files, txt_path, SPEAKER_LABEL


if __name__ == "__main__":
    log_file = Path.cwd() / "transcription_de_debug.log"
    tee = TeeOutput(log_file)

    set_tee(tee)

    original_stdout = sys.stdout
    sys.stdout = tee

    json_files    = None
    txt_path      = None
    speaker_label = None

    try:
        json_files, txt_path, speaker_label = main()
    finally:
        sys.stdout = original_stdout
        tee.close()

        if json_files and txt_path and log_file.exists():
            print(f"\n💾 DEBUG log сохранён: {log_file}")
            copy_to_test_results(json_files, txt_path, speaker_label, log_file)
        else:
            print(f"\n💾 DEBUG log сохранён: {log_file}")
            print("   TEST: Копирование в test-results пропущено")
