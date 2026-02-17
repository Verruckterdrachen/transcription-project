#!/usr/bin/env python3
"""
corrections/timestamp_fixer.py - Исправление timestamp v16.34

🆕 v16.34: FIX БАГ #9 + улучшение логики interval checking
- Inner timestamp НЕ РАНЬШЕ чем start + interval (30s)
- Не ставить inner timestamp если до конца < 15s
- Удаление inner timestamps в TXT export (они не должны быть видны)

🆕 v16.33: FIX БАГ #11 - Timestamp через raw segments (ТОЧНЫЕ timestamps!)
- Находим raw segments внутри merged segment
- Используем raw_segment['start'] напрямую
"""

import re
from core.utils import seconds_to_hms


def insert_intermediate_timestamps(segments, segments_raw, interval=30.0, debug=True):
    """
    🆕 v16.34: ПРАВИЛЬНАЯ логика interval checking
    
    1. Первый inner timestamp: НЕ РАНЬШЕ чем start + interval (30s)
    2. Между собой: ~interval (30s) от предыдущего
    3. От конца: НЕ ставить если до конца < 15s
    
    Args:
        segments: Список merged segments
        segments_raw: Список raw segments с точными timestamps
        interval: Интервал вставки timestamp (30s)
        debug: Показывать debug output
    
    Returns:
        segments с вставленными timestamp
    """
    if debug:
        print(f"\n🕒 Вставка промежуточных timestamp (interval={interval}s) v16.34...")
    
    injection_count = 0
    skipped_too_close_start = 0
    skipped_too_close_end = 0
    
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
        
        # 🆕 v16.34: ПРАВИЛЬНАЯ логика фильтрации кандидатов
        candidates = []
        last_timestamp = start
        
        for raw_seg in raw_segs_in_merge:
            raw_start = raw_seg.get('start', 0)
            time_since_last = raw_start - last_timestamp
            time_to_end = end - raw_start
            
            # 🆕 v16.34: Условия для вставки:
            # 1. Расстояние >= interval от последнего timestamp (включая start)
            # 2. До конца >= 15s (не ставим inner timestamp в самом конце)
            # 3. Есть текст для поиска
            if (time_since_last >= interval and 
                time_to_end >= 15.0 and
                raw_seg.get('text', '').strip()):
                
                candidates.append(raw_seg)
                last_timestamp = raw_start
            else:
                # Debug почему пропустили
                if debug and time_since_last >= interval and time_to_end < 15.0:
                    skipped_too_close_end += 1
                elif debug and time_since_last < interval:
                    skipped_too_close_start += 1
        
        if not candidates:
            continue
        
        # v16.33: Вставляем timestamps на основе raw segments
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
                    print(f"  📌 {seg.get('time', '???')} ({seg.get('speaker')}) → inject {timestamp_str.strip()} (от начала: {candidate_start - start:.1f}s)")
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
        if skipped_too_close_start > 0:
            print(f"⏭️ Пропущено (< {interval}s от предыдущего): {skipped_too_close_start}")
        if skipped_too_close_end > 0:
            print(f"⏭️ Пропущено (< 15s до конца): {skipped_too_close_end}")
        if injection_count == 0:
            print(f"✅ Блоков >30s не найдено")
    
    return segments


def correct_timestamp_drift(segments, debug=True):
    """
    🆕 v16.22: FIX БАГ #2 - Timestamp назад
    🆕 v16.19: Исправляет сдвиг timestamp после gap filling
    
    (код без изменений)
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
