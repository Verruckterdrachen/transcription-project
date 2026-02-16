#!/usr/bin/env python3
"""
corrections/timestamp_fixer.py - Исправление timestamp v16.31

🆕 v16.31: FIX БАГ #5 + БАГ #7
- Использование реальных timestamps из segments_raw
- Защита от timestamp дублей (проверка близости к seg['start'])

🆕 v16.28: FIX БАГ #3 - Потеря последнего предложения
- range(0, len(sentences), 2) вместо range(0, len(sentences)-1, 2)

🆕 v16.22: FIX БАГ #1 - Дублирующиеся timestamp
- Проверка: timestamp НЕ вставляется, если предложение уже начинается с HH:MM:SS

🆕 v16.22: FIX БАГ #2 - Timestamp назад
- Проверка монотонности: new_start >= old_start
"""

import re
from core.utils import seconds_to_hms


def insert_intermediate_timestamps(segments, segments_raw, interval=30.0, debug=True):
    """
    🆕 v16.31: FIX БАГ #5 - Использование реальных timestamps из segments_raw
    🆕 v16.31: FIX БАГ #7 - Защита от timestamp дублей
    
    **ПРОБЛЕМА (БАГ #5):**
    Inner timestamps вычислялись пропорционально от начала merged блока
    → Сдвиг на 4-5 сек назад от реальных timestamps!
    
    Пример:
    Merged segment: start=9.06 (00:00:09), end=220.5 (00:03:40), текст ~500 слов
    Raw segment 3: start=46.22 (00:00:46), text="Соответственно отзывом..."
    
    СТАРАЯ ЛОГИКА (пропорционально):
    - Текст до предложения: 200 символов
    - Пропорциональное время: 9.06 + (200/2000) * (220.5 - 9.06) = 30.2 сек (00:00:30)
    - Ошибка: -16 сек от реального времени 46.22!
    
    НОВАЯ ЛОГИКА (реальные timestamps):
    - Находим raw segment по пропорциональному времени
    - Используем raw_segment['start'] = 46.22 (00:00:46) ✅
    
    **ПРОБЛЕМА (БАГ #7):**
    Timestamp вставлялся, даже если он слишком близко к seg['time']
    → Дубль: "00:16:25 Исаев: 00:16:25 Кроме того..."
    
    **FIX v16.31:**
    Проверяем abs(timestamp_sec - seg['start']) < 2.0 → пропускаем!
    
    Args:
        segments: Список merged segments
        segments_raw: Список raw segments с реальными timestamps ← 🆕 v16.31
        interval: Интервал вставки timestamp (30s)
        debug: Показывать debug output
    
    Returns:
        segments с вставленными timestamp
    """
    if debug:
        print(f"\n🕒 Вставка промежуточных timestamp (interval={interval}s) v16.31...")
    
    injection_count = 0
    skipped_duplicates = 0
    skipped_too_close = 0  # 🆕 v16.31
    
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
        sentences = [''.join(sentences[i:i+2]).strip() for i in range(0, len(sentences), 2)]
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
            if elapsed >= interval and sent_idx < len(sentences) - 1:
                
                # v16.22: Проверяем, что предложение НЕ начинается с timestamp
                if not re.match(r'^\d{2}:\d{2}:\d{2}', sent.strip()):
                    
                    # 🆕 v16.31: Ищем реальный raw segment
                    timestamp_sec = current_time
                    
                    # Находим raw segment, который ближайший к current_time
                    closest_raw_seg = None
                    min_diff = float('inf')
                    
                    for raw_seg in segments_raw:
                        raw_start = raw_seg.get('start', 0)
                        raw_end = raw_seg.get('end', 0)
                        
                        # Проверяем, попадает ли current_time в этот raw segment
                        if raw_start <= current_time <= raw_end:
                            closest_raw_seg = raw_seg
                            break
                        
                        # Или ближайший по времени
                        diff = abs(raw_start - current_time)
                        if diff < min_diff:
                            min_diff = diff
                            closest_raw_seg = raw_seg
                    
                    if closest_raw_seg:
                        timestamp_sec = closest_raw_seg.get('start', current_time)
                        
                        if debug and abs(timestamp_sec - current_time) > 2.0:
                            print(f"  🔧 Корректировка timestamp: {seconds_to_hms(current_time)} → {seconds_to_hms(timestamp_sec)} (raw segment)")
                    
                    # 🆕 v16.31: FIX БАГ #7 - Проверяем близость к seg['start']
                    if abs(timestamp_sec - seg['start']) < 2.0:
                        # Слишком близко к началу сегмента → пропускаем!
                        if debug:
                            print(f"  ⏭️ Пропускаем: {seconds_to_hms(timestamp_sec)} слишком близко к началу {seg.get('time')}")
                        skipped_too_close += 1
                    else:
                        timestamp_str = f" {seconds_to_hms(timestamp_sec)} "
                        new_text_parts.append(timestamp_str)
                        
                        if debug:
                            print(f"  📌 {seg.get('time', '???')} ({seg.get('speaker')}) → inject {timestamp_str.strip()} после {elapsed:.1f}s")
                        
                        injection_count += 1
                    
                    elapsed = 0.0
                else:
                    # Предложение УЖЕ начинается с timestamp → пропускаем
                    if debug:
                        print(f"  ⏭️ Пропускаем дубль: предложение начинается с {sent[:10]}...")
                    skipped_duplicates += 1
                
                elapsed = 0.0  # Сбрасываем счётчик
            
            new_text_parts.append(sent)
            current_time += sent_dur
            elapsed += sent_dur
        
        # Обновляем текст сегмента
        seg['text'] = ' '.join(new_text_parts)
    
    if debug:
        if injection_count > 0:
            print(f"✅ Вставлено промежуточных timestamp: {injection_count}")
        if skipped_duplicates > 0:
            print(f"⏭️ Пропущено дублей: {skipped_duplicates}")
        if skipped_too_close > 0:
            print(f"⏭️ Пропущено (слишком близко к началу): {skipped_too_close}")
        if injection_count == 0 and skipped_duplicates == 0 and skipped_too_close == 0:
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
