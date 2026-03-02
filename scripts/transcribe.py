"""
transcribe.py — Главный оркестратор пайплайна транскрибации

Пайплайн:
  1. Диаризация (pyannote 3.1)
  2. Транскрибация (Whisper large-v3-turbo)
  3. Выравнивание Whisper ↔ Pyannote
  4. Коррекции (журналист-команды, boundary, dedup)
  5. GAP filling + timestamp correction
  6. Merge реплик
  7. Классификация спикеров v15
  8. Split смешанных сегментов
  8.1 Timestamp injection (>30s)
  8.2 Text correction
  8.3 Hallucination removal
  9. Валидация + auto-merge
  10. Экспорт (JSON + TXT)

Tech: Whisper large-v3-turbo, Pyannote 3.1, Python 3.10+
История изменений: см. docs/CHANGELOG.md
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

from core.logging_utils import TeeOutput, set_tee, switch_log_phase

from huggingface_hub import login

warnings.filterwarnings("ignore")

# ═══════════════════════════════════════════════════════════════════════════
# DEBUG CHECKPOINT (v17.19: универсальная версия, без привязки к конкретному багу)
# Для активации отладки конкретного бага — задать _DEBUG_SCENARIO в main()
# ═══════════════════════════════════════════════════════════════════════════

# Настраивается из main() или напрямую для отладки конкретного бага.
# Для обычного прогона: пустые значения — только счётчики сегментов.
_DEBUG_TARGET_TIMESTAMPS: list = []   # пример: ["00:02:26", "00:04:29"]
_DEBUG_TARGET_PHRASE: str | None = None  # пример: "прорыв блокады"

def debug_checkpoint(segments, stage_name,
                     target_timestamps=None, target_phrase=None):
    """
    Универсальный checkpoint для всех этапов пайплайна.

    Показывает состояние segments на этапе stage_name.
    Помогает локализовать, где пропал текст/фраза/спикер.

    Если target_timestamps и target_phrase не переданы явно — берёт
    из модульных переменных _DEBUG_TARGET_TIMESTAMPS / _DEBUG_TARGET_PHRASE,
    которые задаются под конкретный баг в main() или в начале файла.

    Args:
        segments: список сегментов
        stage_name: имя этапа ("AFTER MERGE" и т.п.)
        target_timestamps: список строк HH:MM:SS (переопределяет модульный)
        target_phrase: строка для поиска в тексте (переопределяет модульный)
    """
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
            print(f"   ❌ {target_ts}: НЕ НАЙДЕН! "
                  f"(возможно удалён на предыдущих этапах)")

# ═══════════════════════════════════════════════════════════════════════════
# 🆕 v17.10: SPLIT-ЛОГ ПО ФАЗАМ
# ═══════════════════════════════════════════════════════════════════════════

_tee: "TeeOutput | None" = None

def switch_log_phase(phase_path):
    """Переключить фазовый лог-файл. Вызывать перед каждым этапом."""
    if _tee is not None:
        _tee.switch_phase(phase_path)

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

	# 🆕 v17.10: Очищаем log/ от предыдущего прогона  ← СЮДА
	log_subdir = test_results_dir / "log"
	if log_subdir.exists():
	    shutil.rmtree(log_subdir)
	    print(f"   🗑️ Очищена папка log/")

	# 🆕 v17.10: Копируем свежую log/ из рабочей директории
	local_log_dir = Path.cwd() / "log"
	if local_log_dir.exists():
	    shutil.copytree(local_log_dir, log_subdir)
	    count = len(list(log_subdir.glob("*.log")))
	    print(f"   ✅ log/: {count} файлов")

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

		# 🆕 v17.10: Фаза 1 — диаризация
    log_base = Path.cwd() / "log"
    stem = wav_path.stem  # например: NW_Uckpa0001_01
    switch_log_phase(log_base / f"{stem}_01_diarization.log")

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
    speaker_roles = identify_speaker_roles(stats, result["segments"], speaker_surname)

    # Выравниваем
    segments_raw = align_whisper_with_diarization(
        result["segments"],
        diarization,
        speaker_surname,
        speaker_roles
    )
    
    # 🔴 v17.1: CHECKPOINT
    debug_checkpoint(segments_raw, "AFTER ALIGNMENT")

    # 🆕 v17.10: Фаза 2 — коррекции + gaps
    switch_log_phase(log_base / f"{stem}_02_alignment.log")

    # ═══════════════════════════════════════════════════════════════════════
    # ЭТАП 4: КОРРЕКЦИИ
    # ═══════════════════════════════════════════════════════════════════════

    # 4.1 Детекция команд Журналиста
    segments_raw, cmd_corrections = detect_journalist_commands_cross_segment(
        segments_raw, speaker_surname
    )
    
    # 🔴 v17.1: CHECKPOINT
    debug_checkpoint(segments_raw, "AFTER JOURNALIST COMMANDS")

    # 4.2 Boundary correction
    segments_raw = boundary_correction_raw(
        segments_raw, speaker_surname, speaker_roles
    )
    
    # 🔴 v17.1: CHECKPOINT
    debug_checkpoint(segments_raw, "AFTER BOUNDARY CORRECTION")

    # 4.3 Cross-speaker deduplication
    print("\n🔄 Cross-speaker deduplication...")
    segments_raw = remove_cross_speaker_text_duplicates(segments_raw)
    print(f"✅ После cross-speaker dedup: {len(segments_raw)} сегментов")
    
    # 🔴 v17.1: CHECKPOINT
    debug_checkpoint(segments_raw, "AFTER CROSS-SPEAKER DEDUP")

    # 4.4 Дедупликация
    print("\n🔄 Дедупликация сегментов...")
    segments_raw = deduplicate_segments(segments_raw)
    print(f"✅ После дедупликации: {len(segments_raw)} сегментов")
    
    # 🔴 v17.1: CHECKPOINT
    debug_checkpoint(segments_raw, "AFTER DEDUPLICATION")

    # ═══════════════════════════════════════════════════════════════════════
    # ЭТАП 5: GAPS (если есть)
    # 🆕 v17.7: FIX БАГ #25 - передача diarization/speaker_roles в force_transcribe_diar_gaps
    # 🆕 v16.5: Умная атрибуция GAP_FILLED по семантическому сходству
    # ═══════════════════════════════════════════════════════════════════════
    gaps = gap_detector(segments_raw, threshold=3.0)
    gap_segments = []

    if gaps:
        print(f"\n🔍 ГАПЫ WHISPER:")
        for gap in gaps:
            print(f"   🚨 GAP {gap['gap_hms_start']}–{gap['gap_hms_end']} ({gap['duration']}s)")

        # Force transcribe gaps (v17.7: FIX БАГ #25 - pyannote overlap attribution + text override)
        gap_segments = force_transcribe_diar_gaps(
            whisper_model, wav_path, gaps, segments_raw, speaker_surname,
            diarization=diarization,      # 🆕 v17.7: FIX БАГ #25
            speaker_roles=speaker_roles   # 🆕 v17.7: FIX БАГ #25
        )

        if gap_segments:
            print(f"  ✅ Добавлено из gaps: {len(gap_segments)} сегментов")
            segments_raw.extend(gap_segments)
            segments_raw.sort(key=lambda x: x["start"])
            
            # 🔴 v17.1: CHECKPOINT
            debug_checkpoint(segments_raw, "AFTER GAP FILLING")

    # ═══════════════════════════════════════════════════════════════════════
    # 🆕 v16.19: ЭТАП 5.2 - TIMESTAMP CORRECTION после gap filling
    # ═══════════════════════════════════════════════════════════════════════
    segments_raw = correct_timestamp_drift(segments_raw, debug=True)
    
    # 🔴 v17.1: CHECKPOINT
    debug_checkpoint(segments_raw, "AFTER TIMESTAMP CORRECTION")

    # 🆕 v17.10: Фаза 3 — merge replicas
    switch_log_phase(log_base / f"{stem}_03_merges.log")

    # ═══════════════════════════════════════════════════════════════════════
    # ЭТАП 6: MERGE REPLICAS
    # ═══════════════════════════════════════════════════════════════════════
    segments_merged = merge_replicas(segments_raw, debug=True)
    
    # 🔴 v17.1: CHECKPOINT
    debug_checkpoint(segments_merged, "AFTER MERGE")

    # 🆕 v17.10: Фаза 4 — постобработка
    switch_log_phase(log_base / f"{stem}_04_postprocess.log")

    # ═══════════════════════════════════════════════════════════════════════
    # ЭТАП 7: SPEAKER CLASSIFICATION v15
    # 🆕 v16.13: Передача speaker_roles для синхронизации raw_speaker_id
    # ═══════════════════════════════════════════════════════════════════════
    print("\n" + "="*70)
    print("🎯 v15: Применяем весовую классификацию спикеров (v16.13)...")
    print("="*70)
    segments_merged, classification_stats = apply_speaker_classification_v15(
        segments_merged, speaker_surname, speaker_roles, debug=True
    )
    print("="*70)
    print()
    
    # 🔴 v17.1: CHECKPOINT
    debug_checkpoint(segments_merged, "AFTER CLASSIFICATION")

    # ═══════════════════════════════════════════════════════════════════════
    # 🔥 ЭТАП 8: SPLIT (v16.40 - ПЕРЕД timestamp injection)
    # 🆕 v16.12: Передача speaker_roles в split для обратной конвертации
    # 🆕 v16.11: Правильная логика continuation phrase fix
    # 🆕 v16.4: Расширенная защита от переатрибуции анонсов вопросов
    # ═══════════════════════════════════════════════════════════════════════
    print("\n✂️ Разделение mixed-speaker сегментов (v16.21)...")
    segments_merged = split_mixed_speaker_segments(
        segments_merged, speaker_surname, speaker_roles
    )
    
    # 🔴 v17.1: CHECKPOINT
    debug_checkpoint(segments_merged, "AFTER SPLIT")

    # ═══════════════════════════════════════════════════════════════════════
    # 🔥 ЭТАП 8.1: TIMESTAMP INJECTION (v16.40 - ПОСЛЕ split)
    # ═══════════════════════════════════════════════════════════════════════
    segments_merged = insert_intermediate_timestamps(segments_merged, interval=30.0, debug=True)
    
    # 🔴 v17.1: CHECKPOINT
    debug_checkpoint(segments_merged, "AFTER TIMESTAMP INJECTION")
    
    # ═══════════════════════════════════════════════════════════════════════
    # ЭТАП 8.2: TEXT CORRECTION
    # ═══════════════════════════════════════════════════════════════════════
    print("\n🔍 Text-based correction (v16.4)...")
    segments_merged = text_based_correction(segments_merged, speaker_surname)
    
    # 🔴 v17.1: CHECKPOINT
    debug_checkpoint(segments_merged, "AFTER TEXT CORRECTION")

    # ═══════════════════════════════════════════════════════════════════════
    # ЭТАП 8.3: HALLUCINATION REMOVAL
    # ═══════════════════════════════════════════════════════════════════════
    segments_merged = filter_hallucination_segments(segments_merged, debug=True)
    
    # 🔴 v17.1: CHECKPOINT
    debug_checkpoint(segments_merged, "AFTER HALLUCINATION REMOVAL")

    # ═══════════════════════════════════════════════════════════════════════
    # ЭТАП 9: ВАЛИДАЦИЯ + AUTO-MERGE
    # 🆕 v16.0: Проверка raw_speaker_id перед слиянием
    # ═══════════════════════════════════════════════════════════════════════
    errors = validate_adjacent_same_speaker(segments_merged)

    if errors:
        segments_merged = auto_merge_adjacent_same_speaker(segments_merged)
        validate_adjacent_same_speaker(segments_merged)

        # 🆕 v17.18: FIX — очищаем ts из текстов перед повторным inject
        # ROOT CAUSE: после auto_merge SKIP срабатывал из-за хвоста ≤ 45s
        for seg in segments_merged:
            seg['text'] = re.sub(r'\s*\b\d{2}:\d{2}:\d{2}\b\s*', ' ', seg['text']).strip()

        # повторный inject для блоков, выросших после auto-merge
        segments_merged = insert_intermediate_timestamps(segments_merged, interval=30.0, debug=True)

        # 🔴 v17.1: CHECKPOINT
        debug_checkpoint(segments_merged, "AFTER AUTO-MERGE")

    # ═══════════════════════════════════════════════════════════════════════
    # ЭТАП 10: ЭКСПОРТ
    # ═══════════════════════════════════════════════════════════════════════
    
    # 🔴 v17.1: ФИНАЛЬНЫЙ CHECKPOINT перед экспортом
    debug_checkpoint(segments_merged, "BEFORE EXPORT (FINAL)")
    
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
        "pipeline_version": VERSION,
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
	# ── DEBUG SCENARIO ───────────────────────────────────────────────────
	# Задать при отладке конкретного бага. Для обычного прогона — не трогать.
	global _DEBUG_TARGET_TIMESTAMPS, _DEBUG_TARGET_PHRASE
	_DEBUG_TARGET_TIMESTAMPS = []    # пример: ["00:02:26"]
	_DEBUG_TARGET_PHRASE     = None  # пример: "прорыв блокады"
	# ─────────────────────────────────────────────────────────────────────

	# Инициализация
	login(token=HF_TOKEN)

	print(f"🔥 ПАЙПЛАЙН v{VERSION}: {VERSION_NAME}")
	print(f"GPU: {'✅ CUDA' if torch.cuda.is_available() else '⚠️ CPU'}")
	print("=" * 70)
	print()
	print("🔴 v17.1 DEBUG:")
	print("   🐛 БАГ #15: Отслеживание пропуска 'прорыв блокады' на 00:02:26")
	print("   🔍 DEBUG checkpoint на каждом этапе пайплайна")
	print("   📝 Полный вывод текста сегмента для целевого timestamp")
	print()

	# Запрос пути к папке
	folder_path = input("📂 Путь к папке спикера (\\\\ или /): ").strip().replace('"', '')
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
    tee = TeeOutput(log_file)

    # 🆕 v17.10: регистрируем глобально для switch_log_phase()
    set_tee(tee)

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

