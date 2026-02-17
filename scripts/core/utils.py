#!/usr/bin/env python3
"""
core/utils.py - Утилиты общего назначения для v16.0
"""

import re
from datetime import timedelta
from difflib import SequenceMatcher
from pathlib import Path
from pydub import AudioSegment

# ═══════════════════════════════════════════════════════════════════════════
# ФОРМАТИРОВАНИЕ ВРЕМЕНИ
# ═══════════════════════════════════════════════════════════════════════════

def seconds_to_hms(seconds):
    """Конвертирует секунды в HH:MM:SS формат"""
    td = timedelta(seconds=int(seconds))
    total_seconds = int(td.total_seconds())
    hours = total_seconds // 3600
    minutes = (total_seconds % 3600) // 60
    secs = total_seconds % 60
    return f"{hours:02d}:{minutes:02d}:{secs:02d}"

# ═══════════════════════════════════════════════════════════════════════════
# ТЕКСТОВОЕ СХОДСТВО
# ═══════════════════════════════════════════════════════════════════════════

def text_similarity(text1, text2):
    """Вычисляет similarity ratio между двумя текстами"""
    return SequenceMatcher(None, text1.lower().strip(), text2.lower().strip()).ratio()

# ═══════════════════════════════════════════════════════════════════════════
# ПАРСИНГ ИМЁН ПАПОК
# ═══════════════════════════════════════════════════════════════════════════

def parse_speaker_folder(folder_name):
    """
    Парсит имя папки спикера в формате "Фамилия (ДД.ММ)" или "Фамилия-ДД.ММ"

    Returns:
        (surname, date, full_name)
    """
    # Формат: "Морозов (30.01)"
    match = re.match(r'^(.+?)\s*\((\d{1,2}\.\d{1,2})\)', folder_name)
    if match:
        return match.group(1).strip(), match.group(2), f"{match.group(1).strip()} ({match.group(2)})"

    # Формат: "Морозов-30.01"
    match = re.match(r'^(.+?)(?:-(\d{1,2}\.\d{2}))', folder_name)
    if match:
        return match.group(1).strip(), match.group(2), f"{match.group(1).strip()} ({match.group(2)})"

    # Не распознано - возвращаем как есть
    return folder_name.split('-')[0].strip(), "", folder_name

# ═══════════════════════════════════════════════════════════════════════════
# AUDIO PROCESSING
# ═══════════════════════════════════════════════════════════════════════════

def extract_gap_audio(wav_path, start_sec, end_sec, overlap=3.0):
    """
    Извлекает аудио-слайс с расширением на overlap секунд с каждой стороны

    Args:
        wav_path: Path к WAV файлу
        start_sec: Начало gap в секундах
        end_sec: Конец gap в секундах
        overlap: Сколько секунд добавить с каждой стороны

    Returns:
        Path к временному файлу с извлечённым аудио
    """
    audio = AudioSegment.from_wav(str(wav_path))

    # Расширяем границы с учётом overlap
    start_ms = max(0, (start_sec - overlap) * 1000)
    end_ms = min(len(audio), (end_sec + overlap) * 1000)

    gap_audio = audio[start_ms:end_ms]

    # Сохраняем во временный файл
    temp_path = wav_path.parent / f"temp_gap_{start_sec:.0f}_{end_sec:.0f}.wav"
    gap_audio.export(temp_path, format="wav")

    return temp_path

# ═══════════════════════════════════════════════════════════════════════════
# GAP DETECTION
# ═══════════════════════════════════════════════════════════════════════════

def gap_detector(segments, threshold=3.0):
    """
    Находит gaps (паузы) между сегментами

    Args:
        segments: Список сегментов с полями start/end
        threshold: Минимальная длительность gap в секундах

    Returns:
        Список gaps с информацией о времени и длительности
    """
    gaps = []

    if len(segments) < 2:
        return gaps

    for i in range(1, len(segments)):
        gap_duration = segments[i]["start"] - segments[i-1]["end"]

        if gap_duration > threshold:
            gaps.append({
                "gap_start": segments[i-1]["end"],
                "gap_end": segments[i]["start"],
                "gap_hms_start": seconds_to_hms(segments[i-1]["end"]),
                "gap_hms_end": seconds_to_hms(segments[i]["start"]),
                "duration": round(gap_duration, 1)
            })

    return gaps

# ═══════════════════════════════════════════════════════════════════════════
# ADAPTIVE VAD
# ═══════════════════════════════════════════════════════════════════════════

def adaptive_vad_threshold(audio_duration):
    """
    Вычисляет адаптивный VAD threshold на основе длительности аудио

    Args:
        audio_duration: Длительность аудио в секундах

    Returns:
        VAD threshold (float)
    """
    if audio_duration < 300:  # < 5 минут
        return 0.65
    elif audio_duration < 600:  # < 10 минут
        return 0.70
    elif audio_duration < 900:  # < 15 минут
        return 0.75
    else:
        return 0.80

# ═══════════════════════════════════════════════════════════════════════════
# OVERLAP CHECKING
# ═══════════════════════════════════════════════════════════════════════════

def check_overlap_with_existing(start, end, existing_segments):
    """
    Вычисляет процент перекрытия сегмента с существующими сегментами

    Args:
        start: Начало проверяемого сегмента
        end: Конец проверяемого сегмента
        existing_segments: Список существующих сегментов

    Returns:
        Процент покрытия (0-100)
    """
    seg_len = end - start

    if seg_len <= 0:
        return 100

    covered_len = 0.0

    for eseg in existing_segments:
        overlap_start = max(start, eseg["start"])
        overlap_end = min(end, eseg["end"])

        if overlap_start < overlap_end:
            covered_len += (overlap_end - overlap_start)

    overlap_pct = (covered_len / seg_len) * 100
    return overlap_pct

# ═══════════════════════════════════════════════════════════════════════════
# LONG TURN SPLITTING
# ═══════════════════════════════════════════════════════════════════════════

def split_long_turn(turn_start, turn_end, chunk_size=12, overlap=3):
    """
    Разбивает длинный диаризационный turn на чанки

    Args:
        turn_start: Начало turn в секундах
        turn_end: Конец turn в секундах
        chunk_size: Размер чанка в секундах
        overlap: Overlap между чанками в секундах

    Returns:
        Список кортежей (start, end) для каждого чанка
    """
    duration = turn_end - turn_start

    if duration <= chunk_size:
        return [(turn_start, turn_end)]

    sub_segments = []
    current = turn_start

    while current < turn_end:
        end = min(current + chunk_size, turn_end)
        sub_segments.append((current, end))
        current += (chunk_size - overlap)

    return sub_segments
