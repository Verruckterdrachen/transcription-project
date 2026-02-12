#!/usr/bin/env python3
"""
corrections/timestamp_fixer.py - Исправление timestamp v16.19

🆕 v16.19: КРИТИЧЕСКИЙ FIX - Timestamp injection в блоки >30 сек
- Детекция блоков без промежуточных timestamp (длительность >30s)
- Вставка промежуточных меток каждые ~30 сек
- Исправление сдвигов timestamp после gap filling
"""

import re
from core.utils import seconds_to_hms


def insert_intermediate_timestamps(segments, interval=30.0, debug=True):
    """
    🆕 v16.19: Вставляет промежуточные timestamp в блоки >30 сек
    
    **ПРОБЛЕМА:**
    После merge_replicas() блоки могут быть >60 сек без меток.
    Пример: 00:06:12 → 00:10:03 (~231 сек, 500 слов) — нет промежуточных меток!
    
    **РЕШЕНИЕ:**
    1. Определяем блоки длительностью > interval (30s)
    2. Разбиваем текст на предложения
    3. Вставляем timestamp каждые ~30 сек перед новым предложением
    
    Args:
        segments: Список сегментов после merge_replicas
        interval: Интервал вставки timestamp (по умолчанию 30s)
        debug: Показывать debug output
    
    Returns:
        segments с вставленными timestamp в тексте
    
    Example:
        БЫЛО:
        00:06:12 Текст 231 сек без меток...
        
        СТАЛО:
        00:06:12 Текст начало... 00:06:42 Текст продолжение... 00:07:12 ...
    """
    if debug:
        print(f"\n🕒 Вставка промежуточных timestamp (interval={interval}s)...")
    
    injection_count = 0
    
    for seg_idx, seg in enumerate(segments):
        start = seg.get('start', 0)
        end = seg.get('end', 0)
        duration = end - start
        
        # Пропускаем короткие блоки
        if duration <= interval:
            continue
        
        text = seg.get('text', '')
        
        # Разбиваем на предложения
        sentences = re.split(r'([.!?]+)\s+', text)
        # Объединяем предложения с пунктуацией: ['Текст', '.', ' '] → ['Текст.']
        sentences = [''.join(sentences[i:i+2]).strip() for i in range(0, len(sentences)-1, 2)]
        sentences = [s for s in sentences if s]
        
        if len(sentences) < 2:
            continue
        
        # Вычисляем примерную длительность одного предложения
        words_total = len(text.split())
        sentence_durations = []
        
        for sent in sentences:
            sent_words = len(sent.split())
            sent_duration = (sent_words / words_total) * duration if words_total > 0 else 0
            sentence_durations.append(sent_duration)
        
        # Вставляем timestamp
        new_text_parts = []
        current_time = start
        elapsed = 0.0
        
        for sent_idx, (sent, sent_dur) in enumerate(zip(sentences, sentence_durations)):
            # Проверяем, нужна ли вставка timestamp
            if elapsed >= interval and sent_idx < len(sentences) - 1:  # НЕ перед последним
                timestamp_str = f" {seconds_to_hms(current_time)} "
                new_text_parts.append(timestamp_str)
                
                if debug:
                    print(f"  📌 {seg.get('time', '???')} ({seg.get('speaker')}) → inject {timestamp_str.strip()} после {elapsed:.1f}s")
                
                injection_count += 1
                elapsed = 0.0  # Сбрасываем счётчик
            
            new_text_parts.append(sent)
            current_time += sent_dur
            elapsed += sent_dur
        
        # Обновляем текст сегмента
        seg['text'] = ' '.join(new_text_parts)
    
    if debug:
        if injection_count > 0:
            print(f"✅ Вставлено промежуточных timestamp: {injection_count}")
        else:
            print(f"✅ Блоков >30s не найдено")
    
    return segments


def correct_timestamp_drift(segments, debug=True):
    """
    🆕 v16.19: Исправляет сдвиг timestamp после gap filling
    
    **ПРОБЛЕМА:**
    После gap filling + overlap adjustment меняется segment.end,
    но segment.start остаётся старым → timestamp в TXT не совпадает с аудио.
    
    Пример:
    - segment.start = 551.2 (00:09:11)
    - реальное начало речи (после adjustment) = 559.5 (00:09:19)
    - Сдвиг: +8 сек!
    
    **РЕШЕНИЕ:**
    После gap filling пересчитываем start по реальным границам:
    - Для первого сегмента после gap: start = конец предыдущего
    - Обновляем segment['time'] по новому start
    
    Args:
        segments: Список сегментов после gap filling
        debug: Показывать debug output
    
    Returns:
        segments с исправленными timestamp
    """
    if debug:
        print(f"\n🔧 Исправление сдвига timestamp после gap filling...")
    
    corrections = 0
    
    for i in range(1, len(segments)):
        prev_seg = segments[i - 1]
        current_seg = segments[i]
        
        prev_end = prev_seg.get('end', 0)
        current_start = current_seg.get('start', 0)
        
        # Если есть overlap (отрицательная пауза) или маленькая пауза
        gap = current_start - prev_end
        
        if -10.0 <= gap <= 0.5:  # Overlap до 10s или микропауза
            # Корректируем start
            old_start = current_start
            new_start = prev_end
            
            current_seg['start'] = new_start
            current_seg['time'] = seconds_to_hms(new_start)
            
            if debug and abs(old_start - new_start) > 1.0:
                print(f"  ⏱️ {seconds_to_hms(old_start)} → {seconds_to_hms(new_start)} (сдвиг {new_start - old_start:+.1f}s)")
            
            corrections += 1
    
    if debug:
        if corrections > 0:
            print(f"✅ Исправлено timestamp: {corrections}")
        else:
            print(f"✅ Сдвигов timestamp не найдено")
    
    return segments
