#!/usr/bin/env python3
"""
corrections/timestamp_fixer.py - Исправление timestamp v16.42

🔥 v16.42: FIX БАГ #14 - Timestamp injection: tracking last_timestamp_time
- БАГ: time_since_start считался от начала сегмента → timestamp каждые 4-15s
- FIX: last_timestamp_time tracking → правильный интервал ≥30s

🔥 v16.40: УПРОЩЕНИЕ - Timestamp injection ПОСЛЕ split
- Split уже разбил текст на предложения с точками
- Просто вставляем timestamp МЕЖДУ предложениями
- НЕ НУЖНО искать точку в радиусе 100 символов!
- Timestamp ВСЕГДА на границе предложений

🆕 v16.39: FIX БАГ #10 - Text-based gap detection
...
"""

import re
from core.utils import seconds_to_hms, hms_to_seconds

def insert_intermediate_timestamps(segments, segments_raw, interval=30.0, debug=True):
    """
    🔥 v16.42: FIX БАГ #14 - Tracking last_timestamp_time для правильного интервала
    🔥 v16.40: УПРОЩЁННАЯ ВЕРСИЯ - вставка ПОСЛЕ split
    
    **ПРОБЛЕМА v16.40:**
    ```python
    time_since_start = cumulative_time - start  # ← От НАЧАЛА сегмента!
    if time_since_start >= interval:
        # Вставляем timestamp
    ```
    
    Результат: timestamp вставлялся КАЖДЫЙ РАЗ когда cumulative_time > start+30,
    игнорируя расстояние между timestamp! Получалось 4-15s вместо ≥30s.
    
    **FIX v16.42:**
    Добавлена переменная `last_timestamp_time` для tracking последнего timestamp.
    Проверяем `cumulative_time - last_timestamp_time >= interval`.
    
    ИЗМЕНЕНИЯ v16.40:
    - Split УЖЕ разбил на предложения → точки известны
    - Просто разбиваем text на предложения и вставляем timestamp
    - НЕ НУЖЕН поиск точки в радиусе 100 символов!
    - Timestamp ВСЕГДА после точки
    
    Args:
        segments: Список merged segments (ПОСЛЕ split!)
        segments_raw: Raw segments (для поиска реальных timestamps)
        interval: Интервал между timestamps (секунды)
        debug: Debug output
    
    Returns:
        segments с вставленными timestamps
    """
    if debug:
        print(f"\n🕒 Вставка промежуточных timestamp (interval={interval}s) v16.42...")
    
    injection_count = 0
    
    for seg_idx, seg in enumerate(segments):
        start = seg.get('start', 0)
        end = seg.get('end', 0)
        duration = end - start
        
        # Пропускаем короткие блоки
        if duration <= interval:
            continue
        
        text = seg.get('text', '')
        
        # 🔥 v16.40: УПРОЩЁННОЕ РАЗБИЕНИЕ на предложения
        # Split УЖЕ сделал это, поэтому у нас короткие сегменты
        # Но если всё же есть длинные (>30s) - разбиваем здесь
        sentences = re.split(r'([.!?]+)\s+', text)
        sentences = [''.join(sentences[i:i+2]).strip() for i in range(0, len(sentences), 2)]
        sentences = [s for s in sentences if s]
        
        if len(sentences) < 2:
            # Нечего делить - только одно предложение
            continue
        
        # Находим raw segments внутри этого merged segment
        raw_segs_in_merge = [
            r for r in segments_raw
            if start <= r['start'] < end
        ]
        
        if not raw_segs_in_merge:
            continue
        
        # Вычисляем пропорциональное время для каждого предложения
        total_chars = sum(len(s) for s in sentences)
        
        if total_chars == 0:
            continue
        
        # 🆕 v16.42: Tracking последнего вставленного timestamp
        last_timestamp_time = start
        
        # Строим карту: позиция конца предложения → timestamp
        sentence_timestamps = []
        cumulative_time = start
        
        for sent in sentences[:-1]:  # Последнее предложение не трогаем
            sent_duration = (len(sent) / total_chars) * duration
            cumulative_time += sent_duration
            
            # 🆕 v16.42: Проверяем время от ПОСЛЕДНЕГО timestamp, не от начала!
            time_since_last_ts = cumulative_time - last_timestamp_time
            time_to_end = end - cumulative_time
            
            if time_since_last_ts >= interval and time_to_end >= 15:
                # ✅ Нужен timestamp!
                # Ищем ближайший raw segment к этому времени
                closest_raw = min(
                    raw_segs_in_merge,
                    key=lambda r: abs(r['start'] - cumulative_time)
                )
                
                sentence_timestamps.append((sent, seconds_to_hms(closest_raw['start'])))
                
                # 🆕 v16.42: ОБНОВЛЯЕМ last_timestamp_time!
                last_timestamp_time = cumulative_time
        
        if not sentence_timestamps:
            continue
        
        # Собираем текст с timestamps
        text_parts = []
        sentence_idx = 0
        
        for sent in sentences:
            text_parts.append(sent)
            
            # Проверяем, нужен ли timestamp после этого предложения
            if sentence_idx < len(sentence_timestamps):
                target_sent, timestamp = sentence_timestamps[sentence_idx]
                
                if sent == target_sent:
                    text_parts.append(f" {timestamp} ")
                    injection_count += 1
                    sentence_idx += 1
                    
                    if debug:
                        print(f"  📌 {seg.get('time', '???')} ({seg.get('speaker')}) → inject {timestamp}")
        
        # Обновляем текст сегмента
        seg['text'] = ''.join(text_parts)
    
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
