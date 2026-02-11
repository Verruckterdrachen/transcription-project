#!/usr/bin/env python3
"""
export/json_export.py - Экспорт результатов в JSON для v16.12

🆕 v16.12: Добавлено поле pipeline_version в JSON metadata
"""

import json
from pathlib import Path

# ═══════════════════════════════════════════════════════════════════════════
# ЭКСПОРТ В JSON
# ═══════════════════════════════════════════════════════════════════════════

def export_to_json(
    output_path,
    segments_raw,
    segments_merged,
    file_info,
    speaker_roles,
    validation_report,
    corrections_log
):
    """
    Экспортирует результаты транскрибации в JSON файл

    Args:
        output_path: Path для сохранения JSON
        segments_raw: Сырые сегменты
        segments_merged: Merged сегменты
        file_info: Информация о файле
        speaker_roles: dict с ролями спикеров
        validation_report: Отчёт валидации
        corrections_log: Лог коррекций

    Returns:
        Path к созданному JSON файлу
    """
    data = {
        "file": file_info.get("filename", ""),
        "duration": file_info.get("duration", 0),
        "speaker": file_info.get("speaker_surname", ""),
        "diarization_model": "pyannote/speaker-diarization-3.1",
        "model": file_info.get("whisper_model", "large-v3-turbo"),
        "vad_threshold_used": file_info.get("vad_threshold", 0.65),
        "gaps_detected": file_info.get("gaps_detected", 0),
        "gaps_final": file_info.get("gaps_final", 0),
        "retry_added": file_info.get("retry_added", 0),
        "speaker_identification": "v16.0-modular",
        "pipeline_version": file_info.get("pipeline_version", "unknown"),  # 🆕 v16.12
        "params": file_info.get("params", {}),
        "segments_count": len(segments_raw),
        "merged_count": len(segments_merged),
        "speaker_stats": file_info.get("speaker_stats", {}),
        "speaker_roles": speaker_roles,
        "corrections_log": corrections_log,
        "validation": validation_report,
        "segments_raw": segments_raw,
        "segments_merged": segments_merged
    }

    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(data, f, ensure_ascii=False, indent=2)

    return output_path
