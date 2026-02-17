#!/usr/bin/env python3
"""
corrections/timestamp_fixer.py - Исправление timestamp v16.33

🆕 v16.33: FIX БАГ #11 - Timestamp через raw segments (ТОЧНЫЕ timestamps!)
- Находим raw segments внутри merged segment
- Используем raw_segment['start'] напрямую (не пропорциональное распределение!)
- Находим соответствующий текст raw segment в merged text
- Вставляем timestamp перед этим текстом

🆕 v16.32: FIX БАГ #11 - Timestamp drift (УДАЛЕНА логика поиска raw segments)
- current_time УЖЕ правильный (accumulated time)!
- Удалена перезапись timestamp_sec = raw_segment['start']
- ROOT CAUSE: v16.31 заменял правильное время на НАЧАЛО raw segment

🆕 v16.28: FIX БАГ #3 - Потеря последнего предложения
- range(0, len(sentences), 2) вместо range(0, len(sentences)-1, 2)
"""

import re
from core.utils import seconds_to_hms


def insert_intermediate_timestamps(segments, segments_raw, interval=30.0, debug=True):
    """
    🆕 v16.33: FIX БАГ #11 - Используем ТОЧНЫЕ timestamps из raw segments
    
    **ПРОБЛЕМА v16.32:**
    Пропорциональное распределение времени по словам предполагает равномерную скорость,
    но это НЕ так! Накопленная ошибка ±5-10 сек.
    
    **FIX v16.33:**
    1. Находим raw segments внутри merged segment
    2. Фильтруем: raw_seg['start'] - seg['start'] >= interval (30s)
    3. Находим текст raw segment в merged text
    4. Вставляем timestamp raw_seg['start'] перед этим текстом
    
    → ТОЧНЫЕ timestamps напрямую из Whisper!
    
    Args:
        segments: Список merged segments
        segments_raw: Список raw segments с точными timestamps
        interval: Интервал вставки timestamp (30s)
        debug: Показывать debug output
    
    Returns:
        segments с вставленными timestamp
    """
    if debug:
        print(f"\n🕒 Вставка промежуточных timestamp (interval={interval}s) v16.33...")
    
    injection_count = 0
    skipped_too_close = 0
    
    for seg_idx, seg in enumerate(segments):
        start = seg.get('start', 0)
        end = seg.get('end', 0)
        duration = end - start
        
        # Пропускаем короткие блоки
        if duration <= interval:
            continue
        
        text = seg.get('text', '')
        
        # 🆕 v16.33: Находим raw segments внутри этого merged segment
        raw_segs_in_merge = [
            r for r in segments_raw
            if start <= r['start'] < end
        ]
        
        if not raw_segs_in_merge:
            continue
        
        # 🆕 v16.33: Фильтруем кандидатов на inner timestamp
        candidates = []
        last_timestamp = start
        
        for raw_seg in raw_segs_in_merge:
            raw_start = raw_seg.get('start', 0)
            time_since_last = raw_start - last_timestamp
            
            # Условия для вставки:
            # 1. Расстояние >= interval от последнего timestamp
            # 2. Не слишком близко к началу merged segment (>2s)
            # 3. Есть текст для поиска
            if (time_since_last >= interval and 
                raw_start - start > 2.0 and
                raw_seg.get('text', '').strip()):
                
                candidates.append(raw_seg)
                last_timestamp = raw_start
        
        if not candidates:
            continue
        
        # 🆕 v16.33: Вставляем timestamps на основе raw segments
        text_parts = []
        current_pos = 0
        
        for candidate in candidates:
            candidate_text = candidate.get('text', '').strip()
            candidate_start = candidate.get('start', 0)
            
            # Ищем текст raw segment в merged text
            # Используем первые 50 символов для поиска
            search_text = candidate_text[:50].lower()
            
            # Ищем позицию в тексте
            pos = text.lower().find(search_text, current_pos)
            
            if pos == -1:
                # Не нашли точное совпадение - пробуем по словам
                words = search_text.split()[:5]  # Первые 5 слов
                search_pattern = ' '.join(words)
                pos = text.lower().find(search_pattern, current_pos)
            
            if pos != -1:
                # Нашли! Вставляем timestamp перед этим текстом
                timestamp_str = f" {seconds_to_hms(candidate_start)} "
                
                # Добавляем текст до позиции
                text_parts.append(text[current_pos:pos])
                # Добавляем timestamp
                text_parts.append(timestamp_str)
                
                current_pos = pos
                injection_count += 1
                
                if debug:
                    print(f"  📌 {seg.get('time', '???')} ({seg.get('speaker')}) → inject {timestamp_str.strip()} (raw seg)")
            else:
                if debug:
                    print(f"  ⏭️ Пропускаем: не нашли текст '{search_text[:30]}...' в merged segment")
        
        # Добавляем оставшийся текст
        text_parts.append(text[current_pos:])
        
        # Обновляем текст сегмента
        seg['text'] = ''.join(text_parts)
    
    if debug:
        if injection_count > 0:
            print(f"✅ Вставлено промежуточных timestamp: {injection_count}")
        if skipped_too_close > 0:
            print(f"⏭️ Пропущено (слишком близко к началу): {skipped_too_close}")
        if injection_count == 0 and skipped_too_close == 0:
            print(f"✅ Блоков >30s не найдено")
    
    return segments


def correct_timestamp_drift(segments, debug=True):
    """
    🆕 v16.22: FIX БАГ #2 - Timestamp назад
    🆕 v16.19: Исправляет сдвиг timestamp после gap filling
    
    (код без изменений - оставляем как в v16.30)
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
