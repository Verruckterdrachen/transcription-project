#!/usr/bin/env python3
"""
corrections/timestamp_fixer.py - Исправление timestamp v16.38

🆕 v16.38: FIX БАГ #9 - Sentence-aware timestamps + gap check
- Timestamps ВСЕГДА на границах предложений
- Optimal candidate selection (ближайший к 30s)
- Gap check между блоками (>45s)

ROOT CAUSE (3 проблемы):
1. Timestamps посередине предложений (6%)
2. Пропущенные блоки >45s (5 gaps)
3. Неравномерные интервалы (37-45s вместо ~30s)

РЕШЕНИЕ:
- find_sentence_boundary_before() из utils.py
- Выбор ближайшего кандидата к target_time
- Дополнительная проверка gaps между блоками
"""

import re
from core.utils import seconds_to_hms, find_sentence_boundary_before, find_sentence_boundary_after


def insert_intermediate_timestamps(segments, segments_raw, interval=30.0, debug=True):
    """
    🆕 v16.38: SENTENCE-AWARE timestamp injection + gap check
    
    PASS 1: Вставка timestamp ВНУТРИ длинных блоков (>30s)
    - Находим оптимальные raw segments (ближайшие к 30s)
    - Вставляем timestamp на границы предложений
    
    PASS 2: Gap check МЕЖДУ блоками
    - Проверяем расстояния между соседними блоками
    - Если >45s → вставляем дополнительный timestamp
    
    Args:
        segments: Список merged segments
        segments_raw: Список raw segments с точными timestamps
        interval: Интервал вставки timestamp (30s)
        debug: Показывать debug output
    
    Returns:
        segments с вставленными timestamp
    """
    if debug:
        print(f"\n🕒 Вставка промежуточных timestamp (interval={interval}s) v16.38...")
    
    injection_count = 0
    skipped_no_boundary = 0
    skipped_too_close_end = 0
    
    # ═══════════════════════════════════════════════════════════════════════
    # PASS 1: ВНУТРИ БЛОКОВ (блоки >30s)
    # ═══════════════════════════════════════════════════════════════════════
    
    for seg_idx, seg in enumerate(segments):
        start = seg.get('start', 0)
        end = seg.get('end', 0)
        duration = end - start
        
        # Пропускаем короткие блоки
        if duration <= interval:
            continue
        
        text = seg.get('text', '')
        
        # Находим raw segments внутри этого merged segment
        raw_segs_in_merge = [
            r for r in segments_raw
            if start <= r['start'] < end
        ]
        
        if not raw_segs_in_merge:
            continue
        
        # 🆕 v16.38: OPTIMAL CANDIDATE SELECTION
        # Вместо "первого подходящего" → "ближайшего к target_time"
        candidates = []
        last_timestamp = start
        
        while True:
            target_time = last_timestamp + interval  # Целевое время (30s от последнего)
            
            if target_time >= end - 15:  # Не ставим timestamp в конце (<15s до end)
                break
            
            # Ищем кандидатов в окне [target-5s, target+10s]
            window_candidates = []
            
            for raw_seg in raw_segs_in_merge:
                raw_start = raw_seg.get('start', 0)
                
                # Кандидат должен быть:
                # 1. >= interval от последнего timestamp
                # 2. В окне допуска [target-5, target+10]
                # 3. >= 15s до конца блока
                time_since_last = raw_start - last_timestamp
                time_to_end = end - raw_start
                delta_from_target = abs(raw_start - target_time)
                
                if (time_since_last >= interval - 5 and 
                    delta_from_target <= 10 and
                    time_to_end >= 15.0 and
                    raw_seg.get('text', '').strip()):
                    
                    window_candidates.append((raw_seg, delta_from_target))
            
            if not window_candidates:
                # Нет кандидатов в окне → сдвигаем target дальше
                last_timestamp = target_time
                continue
            
            # Сортируем по близости к target_time
            window_candidates.sort(key=lambda x: x[1])
            best_candidate = window_candidates[0][0]
            
            candidates.append(best_candidate)
            last_timestamp = best_candidate.get('start', 0)
        
        if not candidates:
            continue
        
        # 🆕 v16.38: SENTENCE-AWARE INJECTION
        text_parts = []
        current_pos = 0
        
        for candidate in candidates:
            candidate_text = candidate.get('text', '').strip()
            candidate_start = candidate.get('start', 0)
            
            # Ищем текст raw segment в merged text
            search_text = candidate_text[:50].lower()
            
            # Ищем позицию в тексте
            pos = text.lower().find(search_text, current_pos)
            
            if pos == -1:
                # Не нашли точное совпадение - пробуем по словам
                words = search_text.split()[:5]
                search_pattern = ' '.join(words)
                pos = text.lower().find(search_pattern, current_pos)
            
            if pos != -1:
                # ✅ ПРОВЕРЯЕМ ГРАНИЦУ ПРЕДЛОЖЕНИЯ
                # Ищем ближайшую точку ПЕРЕД pos
                sentence_boundary = find_sentence_boundary_before(text, pos, max_distance=100)
                
                if sentence_boundary != -1 and sentence_boundary > current_pos:
                    # Нашли границу - вставляем ПОСЛЕ точки
                    inject_pos = sentence_boundary
                    inject_type = "after ."
                else:
                    # Граница далеко/не найдена - ищем границу ПОСЛЕ pos
                    sentence_boundary_after = find_sentence_boundary_after(text, pos, max_distance=100)
                    
                    if sentence_boundary_after != -1 and sentence_boundary_after < len(text):
                        inject_pos = sentence_boundary_after
                        inject_type = "after . (next)"
                    else:
                        # Нет границ - вставляем перед найденным текстом
                        inject_pos = pos
                        inject_type = "before text"
                        skipped_no_boundary += 1
                
                # Создаём timestamp
                timestamp_str = f" {seconds_to_hms(candidate_start)} "
                
                # Добавляем текст до inject_pos
                text_parts.append(text[current_pos:inject_pos])
                # Добавляем timestamp
                text_parts.append(timestamp_str)
                
                current_pos = inject_pos
                injection_count += 1
                
                if debug:
                    print(f"  📌 {seg.get('time', '???')} ({seg.get('speaker')}) → inject {timestamp_str.strip()} [{inject_type}] (от начала: {candidate_start - start:.1f}s)")
            else:
                if debug:
                    print(f"  ⏭️ Пропускаем: не нашли текст '{search_text[:30]}...' в merged segment")
        
        # Добавляем оставшийся текст
        text_parts.append(text[current_pos:])
        
        # Обновляем текст сегмента
        seg['text'] = ''.join(text_parts)
    
    # ═══════════════════════════════════════════════════════════════════════
    # PASS 2: МЕЖДУ БЛОКАМИ (gaps >45s)
    # ═══════════════════════════════════════════════════════════════════════
    
    if debug:
        print(f"\n🔍 Gap check между блоками (threshold=45s)...")
    
    gap_injections = 0
    
    for i in range(len(segments) - 1):
        current_seg = segments[i]
        next_seg = segments[i + 1]
        
        current_end = current_seg.get('end', 0)
        next_start = next_seg.get('start', 0)
        gap = next_start - current_end
        
        if gap > 45:
            # ✅ Большой gap! Вставляем timestamp в начало next_segment
            # Ищем первое предложение в next_segment
            next_text = next_seg.get('text', '')
            
            # Ищем первую точку
            first_boundary = find_sentence_boundary_after(next_text, 0, max_distance=200)
            
            if first_boundary != -1 and first_boundary < len(next_text):
                # Вставляем timestamp ПОСЛЕ первой точки
                timestamp_str = f" {next_seg.get('time', '00:00:00')} "
                
                # Проверяем, нет ли уже timestamp в начале
                if not re.match(r'\s*\d{2}:\d{2}:\d{2}\s', next_text[:20]):
                    next_seg['text'] = next_text[:first_boundary] + timestamp_str + next_text[first_boundary:]
                    gap_injections += 1
                    
                    if debug:
                        print(f"  📌 GAP {seconds_to_hms(current_end)} → {seconds_to_hms(next_start)} ({gap:.1f}s) → inject {timestamp_str.strip()} в начало next")
    
    # ═══════════════════════════════════════════════════════════════════════
    # ИТОГИ
    # ═══════════════════════════════════════════════════════════════════════
    
    if debug:
        if injection_count > 0:
            print(f"\n✅ PASS 1: Вставлено inner timestamps: {injection_count}")
        if gap_injections > 0:
            print(f"✅ PASS 2: Вставлено gap timestamps: {gap_injections}")
        if skipped_no_boundary > 0:
            print(f"⚠️ Вставлено БЕЗ sentence boundary: {skipped_no_boundary} (не нашли точку)")
        if skipped_too_close_end > 0:
            print(f"⏭️ Пропущено (< 15s до конца): {skipped_too_close_end}")
        if injection_count == 0 and gap_injections == 0:
            print(f"✅ Timestamp injection не требуется")
    
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
