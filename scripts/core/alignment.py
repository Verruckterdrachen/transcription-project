#!/usr/bin/env python3
"""
core/alignment.py - Выравнивание Whisper сегментов с диаризацией для v16.0
"""

from .diarization import align_segment_to_diarization
from .utils import seconds_to_hms
from .config import JOURNALIST_PATTERNS
import re

# ═══════════════════════════════════════════════════════════════════════════
# МАППИНГ СПИКЕРОВ
# ═══════════════════════════════════════════════════════════════════════════

def map_speaker(speaker_id, coverage_pct, seg_len, seg_text, speaker_surname,
                speaker_roles, seg_start=0, previous_segment=None):
    """
    Определяет финальное имя спикера на основе:
    - ID спикера из диаризации
    - Ролей спикеров
    - Текстовых паттернов
    - Контекста предыдущего сегмента

    Args:
        speaker_id: ID спикера из pyannote
        coverage_pct: Процент покрытия сегмента этим спикером
        seg_len: Длительность сегмента в секундах
        seg_text: Текст сегмента
        speaker_surname: Фамилия основного спикера
        speaker_roles: dict с ролями спикеров
        seg_start: Время начала сегмента
        previous_segment: Предыдущий сегмент для проверки continuity

    Returns:
        str: Имя спикера ("Журналист", "Оператор" или speaker_surname)
    """
    seg_len_s = seg_len
    role = speaker_roles.get(speaker_id, "Неизвестно")

    # Оператор всегда остаётся оператором
    if role == "Оператор":
        return "Оператор"

    # Проверка на продолжение реплики того же спикера
    is_continuation = False
    if previous_segment:
        prev_speaker_id = previous_segment.get("raw_speaker_id")
        prev_end = previous_segment.get("end", 0)
        pause = seg_start - prev_end

        if prev_speaker_id == speaker_id and pause < 2.0:
            is_continuation = True

    if is_continuation and previous_segment:
        return previous_segment.get("speaker")

    # Паттерны для определения Журналиста
    journalist_patterns = JOURNALIST_PATTERNS
    question_start_patterns = r'^(?:где|когда|кто|что|как|почему|зачем|какой|какая|какое)\s'

    is_journalist_phrase = re.search(journalist_patterns, seg_text, re.I)
    is_question_start = re.search(question_start_patterns, seg_text.strip(), re.I)

    # Короткая фраза с паттернами журналиста = Журналист
    if (is_journalist_phrase or is_question_start) and seg_len_s < 20:
        if role != "Спикер":
            return "Журналист"

    # Маппинг по роли
    if role == "Спикер":
        return speaker_surname

    if role == "Журналист":
        return "Журналист"

    return speaker_surname

# ═══════════════════════════════════════════════════════════════════════════
# ВЫРАВНИВАНИЕ WHISPER СЕГМЕНТОВ С ДИАРИЗАЦИЕЙ
# ═══════════════════════════════════════════════════════════════════════════

def align_whisper_with_diarization(whisper_segments, diarization, speaker_surname, speaker_roles):
    """
    Выравнивает сегменты Whisper со спикерами из диаризации

    Args:
        whisper_segments: Список сегментов от Whisper
        diarization: Pyannote diarization object
        speaker_surname: Фамилия основного спикера
        speaker_roles: dict с ролями спикеров

    Returns:
        Список сегментов с добавленной информацией о спикере
    """
    aligned_segments = []
    previous_segment = None

    for seg in whisper_segments:
        start = seg["start"]
        end = seg["end"]
        text = seg["text"].strip()

        if not text:
            continue

        # Определяем спикера через диаризацию
        speaker_id, coverage = align_segment_to_diarization(start, end, diarization)

        if speaker_id is None:
            # Нет перекрытия с диаризацией - используем предыдущий спикер или дефолт
            if previous_segment:
                speaker = previous_segment["speaker"]
                speaker_id = previous_segment.get("raw_speaker_id", "UNKNOWN")
            else:
                speaker = speaker_surname
                speaker_id = "UNKNOWN"
        else:
            # Маппим спикера
            seg_len = end - start
            speaker = map_speaker(
                speaker_id, coverage, seg_len, text, speaker_surname,
                speaker_roles, start, previous_segment
            )

        aligned_seg = {
            "start": start,
            "end": end,
            "start_hms": seconds_to_hms(start),
            "end_hms": seconds_to_hms(end),
            "text": text,
            "raw_speaker_id": speaker_id,
            "speaker": speaker,
            "confidence": seg.get("avg_logprob", 0)
        }

        aligned_segments.append(aligned_seg)
        previous_segment = aligned_seg

        # Вывод для debug
        print(f"  📍 [{aligned_seg['start_hms']}-{aligned_seg['end_hms']}] {speaker}")

    return aligned_segments
