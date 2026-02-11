#!/usr/bin/env python3
"""
merge/deduplicator.py - Дедупликация сегментов для v16.0
"""

import re
from core.utils import text_similarity, check_overlap_with_existing

# ═══════════════════════════════════════════════════════════════════════════
# CROSS-SPEAKER DEDUPLICATION
# ═══════════════════════════════════════════════════════════════════════════

def remove_cross_speaker_text_duplicates(segments):
    """
    Удаляет дубликаты между разными спикерами

    Args:
        segments: Список сегментов

    Returns:
        Очищенный список
    """
    if len(segments) < 2:
        return segments

    segments_sorted = sorted(segments, key=lambda x: x["start"])
    to_remove = set()

    for i in range(len(segments_sorted)):
        if i in to_remove:
            continue

        current = segments_sorted[i]

        # Проверяем следующие 10 сегментов
        for j in range(i + 1, min(i + 10, len(segments_sorted))):
            if j in to_remove:
                continue

            next_seg = segments_sorted[j]

            # Только для разных спикеров
            if current["speaker"] == next_seg["speaker"]:
                continue

            # Проверяем сходство текста
            sim = text_similarity(current["text"], next_seg["text"])
            time_diff = abs(current["start"] - next_seg["start"])

            if sim > 0.85 and time_diff < 5.0:
                # Оставляем тот, у которого меньше overlap с другими
                other_segments = [s for k, s in enumerate(segments_sorted) if k != i and k != j]

                current_overlap = check_overlap_with_existing(
                    current["start"], current["end"], other_segments
                )
                next_overlap = check_overlap_with_existing(
                    next_seg["start"], next_seg["end"], other_segments
                )

                # Удаляем тот, у которого больше overlap
                if current_overlap > 50 and next_overlap <= 50:
                    to_remove.add(i)
                    break
                elif next_overlap > 50 and current_overlap <= 50:
                    to_remove.add(j)
                    continue
                else:
                    # Удаляем по времени (оставляем более ранний)
                    if current["start"] > next_seg["start"]:
                        to_remove.add(i)
                        break
                    else:
                        to_remove.add(j)

    cleaned = [seg for i, seg in enumerate(segments_sorted) if i not in to_remove]
    removed_count = len(segments) - len(cleaned)

    if removed_count > 0:
        print(f"✅ Cross-speaker dedup: удалено {removed_count} дублей")

    return cleaned

# ═══════════════════════════════════════════════════════════════════════════
# МНОГОУРОВНЕВАЯ ДЕДУПЛИКАЦИЯ
# ═══════════════════════════════════════════════════════════════════════════

def deduplicate_segments(segments):
    """
    Многоуровневая дедупликация сегментов одного спикера

    Args:
        segments: Список сегментов

    Returns:
        Дедуплицированный список
    """
    if len(segments) < 2:
        return segments

    segments_sorted = sorted(segments, key=lambda x: x["start"])
    deduplicated = []
    skip_indices = set()

    for i in range(len(segments_sorted)):
        if i in skip_indices:
            continue

        current = segments_sorted[i]
        duplicates = [current]

        # Проверяем следующие 11 сегментов
        for j in range(i + 1, min(i + 11, len(segments_sorted))):
            if j in skip_indices:
                continue

            next_seg = segments_sorted[j]

            # Только для одного спикера
            if current["speaker"] != next_seg["speaker"]:
                continue

            # Вычисляем временное перекрытие
            time_overlap = (min(current["end"], next_seg["end"]) - 
                          max(current["start"], next_seg["start"]))
            seg_duration = current["end"] - current["start"]

            if seg_duration > 0:
                time_overlap_pct = (time_overlap / seg_duration) * 100
            else:
                time_overlap_pct = 0

            sim = text_similarity(current["text"], next_seg["text"])

            # Условия для дубликата
            if sim > 0.85:
                duplicates.append(next_seg)
                skip_indices.add(j)
                continue

            if time_overlap_pct > 95 and sim > 0.70:
                duplicates.append(next_seg)
                skip_indices.add(j)
                continue

            if time_overlap_pct > 80:
                # Проверяем различия в числах
                numbers_current = set(re.findall(r'\b\d+\b', current["text"]))
                numbers_next = set(re.findall(r'\b\d+\b', next_seg["text"]))

                if (numbers_current - numbers_next) or (numbers_next - numbers_current):
                    continue

                len_ratio = (min(len(current["text"]), len(next_seg["text"])) / 
                           max(len(current["text"]), len(next_seg["text"])))

                if len_ratio < 0.5 or sim < 0.70:
                    continue

        # Оставляем самый длинный из дубликатов
        best = max(duplicates, key=lambda x: len(x["text"]))
        deduplicated.append(best)

    return deduplicated
