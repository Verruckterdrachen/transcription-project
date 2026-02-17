#!/usr/bin/env python3
"""
merge/validator.py - Валидация и auto-merge для v16.0
🆕 v16.0: Проверка raw_speaker_id перед слиянием
"""

from core.utils import seconds_to_hms

# ═══════════════════════════════════════════════════════════════════════════
# ВАЛИДАЦИЯ: ADJACENT SAME SPEAKER
# ═══════════════════════════════════════════════════════════════════════════

def validate_adjacent_same_speaker(merged_segments):
    """
    Проверяет наличие соседних реплик одного спикера

    Args:
        merged_segments: Список merged сегментов

    Returns:
        Список ошибок
    """
    print("\n🔍 Validation: Adjacent same speaker...")
    errors = []

    for i in range(len(merged_segments) - 1):
        current = merged_segments[i]
        next_seg = merged_segments[i + 1]

        # Пропускаем Журналиста (у него могут быть подряд вопросы)
        if current['speaker'] == next_seg['speaker'] and current['speaker'] != 'Журналист':
            pause = next_seg['start'] - current['end']

            errors.append({
                'index_current': i,
                'index_next': i + 1,
                'time': current['time'],
                'speaker': current['speaker'],
                'next_time': next_seg['time'],
                'pause': round(pause, 2),
                'text_end': current['text'][-80:],
                'text_start': next_seg['text'][:80]
            })

    if errors:
        print(f"  ⚠️ Найдено {len(errors)} соседних реплик одного спикера!")
        for err in errors[:3]:
            print(f"     🔴 [{err['time']}] {err['speaker']} (пауза {err['pause']}s)")
            print(f"        Конец: '...{err['text_end']}'")
            print(f"        [{err['next_time']}] Начало: '{err['text_start']}...'")
    else:
        print("  ✅ Соседних реплик не найдено")

    return errors

# ═══════════════════════════════════════════════════════════════════════════
# AUTO-MERGE ADJACENT SAME SPEAKER
# 🆕 v16.0: FIX #4 - Проверка raw_speaker_id
# ═══════════════════════════════════════════════════════════════════════════

def auto_merge_adjacent_same_speaker(merged_segments):
    """
    Безопасное автоматическое слияние соседних реплик одного спикера

    🆕 v16.0: НЕ сливает если raw_speaker_id разные (защита от ошибочной атрибуции)

    Args:
        merged_segments: Список merged сегментов

    Returns:
        Список после auto-merge
    """
    print("\n🔧 Auto-merge adjacent same speaker (SAFE)...")
    merged_count = 0
    new_segments = []
    i = 0

    while i < len(merged_segments):
        current = merged_segments[i]
        to_merge = [current]

        j = i + 1
        while j < len(merged_segments):
            next_seg = merged_segments[j]

            if (next_seg['speaker'] == current['speaker'] and 
                next_seg['speaker'] != 'Оператор'):

                pause = next_seg['start'] - to_merge[-1]['end']

                # Проверка: нет другого спикера между
                has_other_speaker_between = False
                if j > i + 1:
                    for k in range(i + 1, j):
                        if merged_segments[k]['speaker'] != current['speaker']:
                            has_other_speaker_between = True
                            break

                if has_other_speaker_between:
                    print(f"  🛑 SKIP MERGE: {current['time']}-{next_seg['time']} (другой спикер между)")
                    break

                # 🆕 v16.0: ЗАЩИТА - Не склеивать если raw_speaker_id разные
                current_raw_id = current.get("raw_speaker_id")
                next_raw_id = next_seg.get("raw_speaker_id")

                if current_raw_id and next_raw_id and current_raw_id != next_raw_id:
                    print(f"  🛡️ SKIP MERGE: {current['time']}-{next_seg['time']} (разные raw_speaker_id)")
                    break

                if pause < 5.0:
                    to_merge.append(next_seg)
                    j += 1
                else:
                    break
            else:
                break

        # Объединяем если > 1 сегмента
        if len(to_merge) > 1:
            merged_text = ' '.join([seg['text'] for seg in to_merge])

            new_segment = {
                'speaker': current['speaker'],
                'time': current['time'],
                'start': current['start'],
                'end': to_merge[-1]['end'],
                'text': merged_text,
                'confidence': current.get('confidence', ''),
                'auto_merged_from': len(to_merge),
                'raw_speaker_id': current.get('raw_speaker_id')
            }

            new_segments.append(new_segment)
            merged_count += len(to_merge) - 1
            print(f"  🔧 [{current['time']}] Слито {len(to_merge)} сегментов {current['speaker']}")
        else:
            new_segments.append(current)

        i = j

    print(f"  ✅ Auto-merge: {merged_count} сегментов объединено")
    return new_segments

# ═══════════════════════════════════════════════════════════════════════════
# ГЕНЕРАЦИЯ ОТЧЁТА ВАЛИДАЦИИ
# ═══════════════════════════════════════════════════════════════════════════

def generate_validation_report(segments_merged, speaker_surname):
    """
    Генерирует детальный отчёт валидации

    Args:
        segments_merged: Список merged сегментов
        speaker_surname: Фамилия основного спикера

    Returns:
        dict с результатами валидации
    """
    report = {
        "adjacent_same_speaker_count": 0,
        "adjacent_same_speaker_list": [],
        "short_segments_under_2s": [],
        "potential_missed_interruptions": [],
        "long_pauses_over_10s": []
    }

    for i in range(len(segments_merged) - 1):
        current = segments_merged[i]
        next_seg = segments_merged[i + 1]

        duration = current['end'] - current['start']
        pause = next_seg['start'] - current['end']

        # Adjacent same speaker
        if current['speaker'] == next_seg['speaker'] and current['speaker'] != 'Журналист':
            report['adjacent_same_speaker_count'] += 1
            report['adjacent_same_speaker_list'].append({
                "time": current['time'],
                "speaker": current['speaker'],
                "next_time": next_seg['time'],
                "pause": round(pause, 2),
                "text_end": current['text'][-50:],
                "text_start": next_seg['text'][:50]
            })

        # Короткие сегменты
        if duration < 2.0 and current['speaker'] != 'Журналист':
            report['short_segments_under_2s'].append({
                "time": current['time'],
                "speaker": current['speaker'],
                "duration": round(duration, 2),
                "text": current['text'][:100]
            })

        # Длинные паузы
        if pause > 10.0:
            report['long_pauses_over_10s'].append({
                "time": current['time'],
                "speaker": current['speaker'],
                "next_time": next_seg['time'],
                "next_speaker": next_seg['speaker'],
                "pause": round(pause, 2)
            })

    return report
