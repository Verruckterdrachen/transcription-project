#!/usr/bin/env python3
"""
corrections/diarization_correction.py - Context-aware коррекция diarization v16.31

🆕 v16.31: FIX БАГ #6 - Исправление ошибок Pyannote diarization
"""

def correct_diarization_errors(segments, debug=True):
    """
    🆕 v16.31: FIX БАГ #6 - Context-aware speaker correction
    
    **ПРОБЛЕМА:**
    Pyannote diarization может ошибочно присвоить короткий сегмент (<3 сек)
    неправильному спикеру, если он находится между длинными репликами другого спикера.
    
    Пример:
    Segment 174: [886.02-886.48] 0.46s, "Большой Ладоги она, по-моему, дошла", Журналист
    Segment 175: [886.48-887.74] 1.26s, "До Шлиссельбурга", Журналист ❌ (должен быть Исаев!)
    Segment 176: [888.88-890.9] 2.02s, "Да, железная дорога прошла", Исаев
    
    **ЛОГИКА:**
    1. Находим короткие сегменты (<3 сек)
    2. Проверяем соседей (prev/next)
    3. Если prev_speaker == next_speaker AND current_duration < 3.0:
       → Переопределяем current_speaker = prev_speaker
    
    Args:
        segments: Список сегментов после alignment
        debug: Показывать debug output
    
    Returns:
        segments с исправленными speaker
    """
    if debug:
        print(f"\n🔧 Context-aware diarization correction v16.31...")
    
    corrections = 0
    
    for i in range(1, len(segments) - 1):
        prev_seg = segments[i - 1]
        current_seg = segments[i]
        next_seg = segments[i + 1]
        
        current_duration = current_seg['end'] - current_seg['start']
        current_speaker = current_seg.get('speaker')
        prev_speaker = prev_seg.get('speaker')
        next_speaker = next_seg.get('speaker')
        
        # Проверяем условия для correction
        if (current_duration < 3.0 and 
            prev_speaker and next_speaker and 
            prev_speaker == next_speaker and 
            current_speaker != prev_speaker):
            
            old_speaker = current_speaker
            current_seg['speaker'] = prev_speaker
            
            # 🆕 v16.31: Синхронизируем raw_speaker_id
            # Нужно найти соответствие speaker → raw_speaker_id
            # Берём из prev_seg, т.к. он уже имеет правильный маппинг
            if 'raw_speaker_id' in prev_seg:
                current_seg['raw_speaker_id'] = prev_seg['raw_speaker_id']
            
            if debug:
                from core.utils import seconds_to_hms
                current_time = seconds_to_hms(current_seg.get('start', 0))
                text_preview = current_seg.get('text', '')[:40]
                print(f"  🔄 {current_time} ({current_duration:.2f}s): {old_speaker} → {prev_speaker}")
                print(f"     Текст: \"{text_preview}...\"")
            
            corrections += 1
    
    if debug:
        if corrections > 0:
            print(f"✅ Исправлено speaker: {corrections}")
        else:
            print(f"✅ Context-aware correction: ошибок не найдено")
    
    return segments
