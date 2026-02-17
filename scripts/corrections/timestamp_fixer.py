#!/usr/bin/env python3
"""
corrections/timestamp_fixer.py - Исправление timestamp v16.43

🔥 v16.43: FIX БАГ #12 + БАГ #14
- БАГ #12: Точки без пробелов → ''.join(text_parts) → text_parts.append(' ')
- БАГ #14: Timestamp >30s → last_timestamp_time глобальный (между сегментами!)

🔥 v16.42: FIX БАГ #14 - Timestamp injection: tracking last_timestamp_time
🔥 v16.40: УПРОЩЕНИЕ - Timestamp injection ПОСЛЕ split
"""

import re
from core.utils import seconds_to_hms, hms_to_seconds

def insert_intermediate_timestamps(segments, segments_raw, interval=30.0, debug=True):
    """
    🔥 v16.43: FIX БАГ #12 + БАГ #14
    
    **БАГ #12: Точки без пробелов**
    ПРОБЛЕМА v16.42:
    ```python
    text_parts.append(sent)  # "предложение1."
    text_parts.append(f" {timestamp} ")  # " 00:01:30 "
    text_parts.append(sent)  # "предложение2."
    ''.join(text_parts)  # "предложение1. 00:01:30 предложение2."
    #                                      ^^^ НЕТ пробела!
    ```
    
    FIX v16.43:
    Добавляем пробел ПОСЛЕ каждого предложения:
    text_parts.append(sent + ' ')  # "предложение1. "
    
    **БАГ #14: Timestamp интервал > 30s**
    ПРОБЛЕМА v16.42:
    ```python
    for seg in segments:
        last_timestamp_time = start  # ← Сбрасывается каждый сегмент!
    ```
    
    Если есть несколько коротких сегментов (<30s) подряд:
    - Seg1 (20s): last_timestamp_time сброшен → НЕТ timestamp
    - Seg2 (25s): last_timestamp_time сброшен → НЕТ timestamp
    - Seg3 (30s): last_timestamp_time сброшен → НЕТ timestamp
    → Накапливается 75s БЕЗ timestamp!
    
    FIX v16.43:
    last_timestamp_time ГЛОБАЛЬНЫЙ (отслеживается между сегментами):
    - Seg1 (20s): 0s < 30s → НЕТ timestamp, last=20s
    - Seg2 (25s): 20s < 30s → НЕТ timestamp, last=45s
    - Seg3 (30s): 45s >= 30s → ЕСТЬ timestamp! ✅
    
    Args:
        segments: Список merged segments (ПОСЛЕ split!)
        segments_raw: Raw segments (для поиска реальных timestamps)
        interval: Интервал между timestamps (секунды)
        debug: Debug output
    
    Returns:
        segments с вставленными timestamps
    """
    if debug:
        print(f"\n🕒 Вставка промежуточных timestamp (interval={interval}s) v16.43...")
    
    injection_count = 0
    
    # 🆕 v16.43: ГЛОБАЛЬНЫЙ tracking последнего timestamp (между сегментами!)
    global_last_timestamp_time = 0
    
    for seg_idx, seg in enumerate(segments):
        start = seg.get('start', 0)
        end = seg.get('end', 0)
        duration = end - start
        
        # 🆕 v16.43: Обновляем global tracking (если сегмент идёт после предыдущего)
        if seg_idx == 0:
            global_last_timestamp_time = start
        
        text = seg.get('text', '')
        
        # 🔥 v16.40: УПРОЩЁННОЕ РАЗБИЕНИЕ на предложения
        sentences = re.split(r'([.!?]+)\s+', text)
        sentences = [''.join(sentences[i:i+2]).strip() for i in range(0, len(sentences), 2)]
        sentences = [s for s in sentences if s]
        
        if len(sentences) < 2:
            # Нечего делить - только одно предложение
            # 🆕 v16.43: Обновляем global tracking для следующего сегмента
            global_last_timestamp_time = end
            continue
        
        # Короткие сегменты пропускаем (но tracking продолжаем!)
        if duration <= interval:
            global_last_timestamp_time = end
            continue
        
        # Находим raw segments внутри этого merged segment
        raw_segs_in_merge = [
            r for r in segments_raw
            if start <= r['start'] < end
        ]
        
        if not raw_segs_in_merge:
            global_last_timestamp_time = end
            continue
        
        # Вычисляем пропорциональное время для каждого предложения
        total_chars = sum(len(s) for s in sentences)
        
        if total_chars == 0:
            global_last_timestamp_time = end
            continue
        
        # Строим карту: позиция конца предложения → timestamp
        sentence_timestamps = []
        cumulative_time = start
        
        for sent in sentences[:-1]:  # Последнее предложение не трогаем
            sent_duration = (len(sent) / total_chars) * duration
            cumulative_time += sent_duration
            
            # 🆕 v16.43: Проверяем время от ГЛОБАЛЬНОГО последнего timestamp!
            time_since_last_ts = cumulative_time - global_last_timestamp_time
            time_to_end = end - cumulative_time
            
            if time_since_last_ts >= interval and time_to_end >= 15:
                # ✅ Нужен timestamp!
                # Ищем ближайший raw segment к этому времени
                closest_raw = min(
                    raw_segs_in_merge,
                    key=lambda r: abs(r['start'] - cumulative_time)
                )
                
                sentence_timestamps.append((sent, seconds_to_hms(closest_raw['start'])))
                
                # 🆕 v16.43: ОБНОВЛЯЕМ ГЛОБАЛЬНЫЙ last_timestamp_time!
                global_last_timestamp_time = cumulative_time
        
        if not sentence_timestamps:
            # Timestamp не вставлен, но обновляем tracking
            global_last_timestamp_time = end
            continue
        
        # Собираем текст с timestamps
        text_parts = []
        sentence_idx = 0
        
        for sent in sentences:
            # 🆕 v16.43: FIX БАГ #12 - Добавляем пробел ПОСЛЕ предложения!
            text_parts.append(sent + ' ')  # "предложение. "
            
            # Проверяем, нужен ли timestamp после этого предложения
            if sentence_idx < len(sentence_timestamps):
                target_sent, timestamp = sentence_timestamps[sentence_idx]
                
                if sent == target_sent:
                    text_parts.append(f"{timestamp} ")  # "00:01:30 "
                    injection_count += 1
                    sentence_idx += 1
                    
                    if debug:
                        print(f"  📌 {seg.get('time', '???')} ({seg.get('speaker')}) → inject {timestamp}")
        
        # Обновляем текст сегмента
        seg['text'] = ''.join(text_parts).strip()  # trim trailing space
        
        # 🆕 v16.43: Обновляем global tracking для следующего сегмента
        global_last_timestamp_time = end
    
    if debug:
        if injection_count > 0:
            print(f"\n✅ Вставлено inner timestamps: {injection_count}")
        else:
            print(f"\n✅ Timestamp injection не требуется")
    
    return segments


def correct_timestamp_drift(segments, debug=True):
    """
    🆕 v16.22: FIX БАГ #2 - Timestamp назад
    🆕 v16.19: Исправляет сдвиг timestamp после gap filling
    """
    if debug:
        print(f"\n🔧 Исправление сдвига timestamp после gap filling...")
    
    corrections = 0
    skipped_backward = 0
    
    for i in range(1, len(segments)):
        prev_seg = segments[i - 1]
        current_seg = segments[i]
        
        prev_end = prev_seg.get('end', 0)
        current_start = current_seg.get('start', 0)
        
        gap = current_start - prev_end
        
        if -10.0 <= gap <= 0.5:
            old_start = current_start
            new_start = prev_end
            
            if new_start >= old_start:
                current_seg['start'] = new_start
                current_seg['time'] = seconds_to_hms(new_start)
                
                if debug and abs(old_start - new_start) > 1.0:
                    print(f"  ⏱️ {seconds_to_hms(old_start)} → {seconds_to_hms(new_start)} (сдвиг {new_start - old_start:+.1f}s)")
                
                corrections += 1
            else:
                if debug:
                    print(f"  ⏭️ ПРОПУСКАЕМ: {seconds_to_hms(old_start)} → {seconds_to_hms(new_start)} (сдвиг назад {new_start - old_start:.1f}s)")
                skipped_backward += 1
    
    if debug:
        if corrections > 0:
            print(f"✅ Исправлено timestamp: {corrections}")
        if skipped_backward > 0:
            print(f"⏭️ Пропущено (сдвиг назад): {skipped_backward}")
        if corrections == 0 and skipped_backward == 0:
            print(f"✅ Сдвигов timestamp не найдено")
    
    return segments
