#!/usr/bin/env python3
"""
corrections/journalist_commands.py - Детекция команд Журналиста для v16.0
"""

import re
from core.config import JOURNALIST_COMMAND_PATTERNS
from core.utils import seconds_to_hms

def detect_journalist_commands_cross_segment(segments_raw, speaker_surname):
    """
    Детектирует команды Журналиста в сегментах Спикера
    Упрощённая версия для v16.0

    Args:
        segments_raw: Список сырых сегментов
        speaker_surname: Фамилия основного спикера

    Returns:
        (new_segments, corrections)
    """
    print("\n🎤 Детекция команд Журналиста (cross-segment)...")

    corrections = []
    new_segments = []

    for i, seg in enumerate(segments_raw):
        # Пропускаем не-Спикера
        if seg['speaker'] != speaker_surname:
            new_segments.append(seg)
            continue

        text = seg['text']
        found_command = False

        # Проверяем каждый паттерн команды
        for pattern in JOURNALIST_COMMAND_PATTERNS:
            match = re.search(pattern, text, re.I)

            if match:
                # Простое разделение: до команды и после
                match_pos = match.start()

                before = text[:match_pos].strip()
                after = text[match_pos:].strip()

                # Если есть текст до и после
                if len(before.split()) > 3 and len(after.split()) > 3:
                    print(f"  🔧 COMMAND [{seg['start_hms']}]: '{match.group()}'")

                    # Разделяем сегмент
                    mid_time = seg['start'] + (seg['end'] - seg['start']) * 0.5

                    new_segments.append({
                        **seg,
                        'end': mid_time,
                        'end_hms': seconds_to_hms(mid_time),
                        'text': before
                    })

                    new_segments.append({
                        **seg,
                        'start': mid_time,
                        'start_hms': seconds_to_hms(mid_time),
                        'text': after,
                        'speaker': 'Журналист',
                        'raw_speaker_id': 'JOURNALIST_COMMAND'
                    })

                    corrections.append({
                        'time': seg['start_hms'],
                        'pattern': match.group()
                    })

                    found_command = True
                    break

        if not found_command:
            new_segments.append(seg)

    print(f"  ✅ Команд Журналиста обнаружено: {len(corrections)}")
    return new_segments, corrections
