#!/usr/bin/env python3
"""
corrections/timestamp_fixer.py - Исправление timestamp v16.39

🆕 v16.39: FIX БАГ #10 - Text-based gap detection
- PASS 1.5: Проверка gaps МЕЖДУ timestamp В ТЕКСТЕ
- Находим gaps >45s между timestamp
- Вставляем промежуточные timestamp из raw segments

ROOT CAUSE:
PASS 1 вставляет timestamp на основе raw segments, но если
Whisper пропустил участок (gap), то PASS 1 его НЕ видит.
PASS 2 проверяет gaps между merged segments, а не внутри текста.

РЕШЕНИЕ:
PASS 1.5 извлекает timestamp ИЗ ТЕКСТА и находит gaps >45s.
"""

import re
from core.utils import seconds_to_hms, hms_to_seconds, find_sentence_boundary_before, find_sentence_boundary_after


def extract_timestamps_from_text(text):
    """
    Извлекает все timestamp из текста
    
    Returns:
        List[(time_seconds, pos_in_text)]
    """
    pattern = r'\b(\d{2}):(\d{2}):(\d{2})\b'
    timestamps = []
    
    for match in re.finditer(pattern, text):
        hms = match.group(0)
        seconds = hms_to_seconds(hms)
        pos = match.start()
        timestamps.append((seconds, pos, hms))
    
    return timestamps


def insert_intermediate_timestamps(segments, segments_raw, interval=30.0, debug=True):
    """
    🆕 v16.39: SENTENCE-AWARE timestamp injection + text-based gap check
    
    PASS 1: Вставка timestamp ВНУТРИ длинных блоков (>30s)
    PASS 1.5: 🆕 Text-based gap detection (gaps >45s между timestamp в тексте)
    PASS 2: Gap check МЕЖДУ блоками
    """
    if debug:
        print(f"\n🕒 Вставка промежуточных timestamp (interval={interval}s) v16.39...")
    
    injection_count = 0
    skipped_no_boundary = 0
    
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
        candidates = []
        last_timestamp = start
        
        while True:
            target_time = last_timestamp + interval
            
            if target_time >= end - 15:
                break
            
            # Ищем кандидатов в окне [target-5s, target+10s]
            window_candidates = []
            
            for raw_seg in raw_segs_in_merge:
                raw_start = raw_seg.get('start', 0)
                
                time_since_last = raw_start - last_timestamp
                time_to_end = end - raw_start
                delta_from_target = abs(raw_start - target_time)
                
                if (time_since_last >= interval - 5 and 
                    delta_from_target <= 10 and
                    time_to_end >= 15.0 and
                    raw_seg.get('text', '').strip()):
                    
                    window_candidates.append((raw_seg, delta_from_target))
            
            if not window_candidates:
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
                sentence_boundary = find_sentence_boundary_before(text, pos, max_distance=100)
                
                if sentence_boundary != -1 and sentence_boundary > current_pos:
                    inject_pos = sentence_boundary
                    inject_type = "after ."
                else:
                    sentence_boundary_after = find_sentence_boundary_after(text, pos, max_distance=100)
                    
                    if sentence_boundary_after != -1 and sentence_boundary_after < len(text):
                        inject_pos = sentence_boundary_after
                        inject_type = "after . (next)"
                    else:
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
    # 🆕 PASS 1.5: TEXT-BASED GAP DETECTION
    # ═══════════════════════════════════════════════════════════════════════
    
    if debug:
        print(f"\n🔍 Text-based gap check (threshold=45s)...")
    
    text_gap_injections = 0
    
    for seg_idx, seg in enumerate(segments):
        start = seg.get('start', 0)
        end = seg.get('end', 0)
        text = seg.get('text', '')
        
        # Извлекаем все timestamp из текста
        timestamps_in_text = extract_timestamps_from_text(text)
        
        if len(timestamps_in_text) == 0:
            continue
        
        # Добавляем начальный timestamp блока
        all_times = [(start, 0, seconds_to_hms(start))] + timestamps_in_text + [(end, len(text), seconds_to_hms(end))]
        
        # Ищем gaps >45s
        text_parts = []
        last_pos = 0
        
        for i in range(len(all_times) - 1):
            current_time, current_pos, current_hms = all_times[i]
            next_time, next_pos, next_hms = all_times[i + 1]
            
            gap = next_time - current_time
            
            if gap > 45:
                # ✅ Нашли gap! Ищем промежуточный raw segment
                # Ищем raw segment ближайший к середине gap
                gap_middle = current_time + gap / 2
                
                # Находим raw segments в диапазоне gap
                gap_raw_segs = [
                    r for r in segments_raw
                    if current_time < r['start'] < next_time and
                    r.get('text', '').strip()
                ]
                
                if gap_raw_segs:
                    # Выбираем ближайший к середине gap
                    gap_raw_segs.sort(key=lambda r: abs(r['start'] - gap_middle))
                    bridge_seg = gap_raw_segs[0]
                    bridge_time = bridge_seg['start']
                    bridge_text = bridge_seg.get('text', '').strip()[:50]
                    
                    # Ищем текст bridge_seg в merged text
                    search_start = current_pos
                    search_end = next_pos if next_pos < len(text) else len(text)
                    search_area = text[search_start:search_end]
                    
                    search_pattern = bridge_text.lower()[:30]
                    bridge_pos_rel = search_area.lower().find(search_pattern)
                    
                    if bridge_pos_rel != -1:
                        bridge_pos_abs = search_start + bridge_pos_rel
                        
                        # Ищем границу предложения
                        sentence_boundary = find_sentence_boundary_before(text, bridge_pos_abs, max_distance=100)
                        
                        if sentence_boundary != -1 and sentence_boundary > last_pos:
                            inject_pos = sentence_boundary
                        else:
                            sentence_boundary_after = find_sentence_boundary_after(text, bridge_pos_abs, max_distance=100)
                            if sentence_boundary_after != -1:
                                inject_pos = sentence_boundary_after
                            else:
                                inject_pos = bridge_pos_abs
                        
                        # Вставляем timestamp
                        timestamp_str = f" {seconds_to_hms(bridge_time)} "
                        text_parts.append(text[last_pos:inject_pos])
                        text_parts.append(timestamp_str)
                        last_pos = inject_pos
                        text_gap_injections += 1
                        
                        if debug:
                            print(f"  ✅ GAP {current_hms} ... {next_hms} ({gap:.0f}s) → inject {timestamp_str.strip()}")
                    else:
                        if debug:
                            print(f"  ⚠️ GAP {current_hms} ... {next_hms} ({gap:.0f}s) → не нашли bridge text")
                else:
                    if debug:
                        print(f"  ⚠️ GAP {current_hms} ... {next_hms} ({gap:.0f}s) → нет raw segments")
        
        if last_pos > 0:
            # Были вставки - обновляем текст
            text_parts.append(text[last_pos:])
            seg['text'] = ''.join(text_parts)
    
    # ═══════════════════════════════════════════════════════════════════════
    # PASS 2: МЕЖДУ БЛОКАМИ (gaps >45s)
    # ═══════════════════════════════════════════════════════════════════════
    
    if debug:
        print(f"\n🔍 Block gap check (threshold=45s)...")
    
    gap_injections = 0
    
    for i in range(len(segments) - 1):
        current_seg = segments[i]
        next_seg = segments[i + 1]
        
        current_end = current_seg.get('end', 0)
        next_start = next_seg.get('start', 0)
        gap = next_start - current_end
        
        if gap > 45:
            next_text = next_seg.get('text', '')
            
            # Ищем первую точку
            first_boundary = find_sentence_boundary_after(next_text, 0, max_distance=200)
            
            if first_boundary != -1 and first_boundary < len(next_text):
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
        if text_gap_injections > 0:
            print(f"✅ PASS 1.5: Вставлено text gap timestamps: {text_gap_injections}")
        if gap_injections > 0:
            print(f"✅ PASS 2: Вставлено block gap timestamps: {gap_injections}")
        if skipped_no_boundary > 0:
            print(f"⚠️ Вставлено БЕЗ sentence boundary: {skipped_no_boundary} (не нашли точку)")
        if injection_count == 0 and gap_injections == 0 and text_gap_injections == 0:
            print(f"✅ Timestamp injection не требуется")
    
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
