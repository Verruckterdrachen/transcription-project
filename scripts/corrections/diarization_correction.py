#!/usr/bin/env python3
"""
corrections/diarization_correction.py - Context-aware коррекция diarization v16.32

🆕 v16.32: FIX БАГ #6 - Два сценария исправления ошибок Pyannote
"""

def correct_diarization_errors(segments, debug=True):
    """
    🆕 v16.32: FIX БАГ #6 - Context-aware speaker correction (2 сценария)
    
    **ПРОБЛЕМА v16.31:**
    Исправлял только "зажатый между одинаковыми", но НЕ "начало next реплики"
    
    Пример БАГ #6:
    Segment 174: [886.02-886.48] 0.46s, "Большой Ладоги...", Журналист
    Segment 175: [886.48-887.74] 1.26s, "До Шлиссельбурга", Журналист ❌ (должен быть Исаев!)
    Segment 176: [888.88-890.9] 2.02s, "Да, железная дорога...", Исаев
    
    **ЛОГИКА v16.32 (2 сценария):**
    
    **Сценарий 1: Короткий зажат между одинаковыми (v16.31)**
    - Условия:
      1. current_duration < 3.0
      2. prev_speaker == next_speaker
      3. current_speaker != prev_speaker
    - Действие: current_speaker = prev_speaker
    
    **Сценарий 2: Очень короткий перед длинным (v16.32 NEW)**
    - Условия:
      1. current_duration < 1.0 (очень короткий!)
      2. len(current_text.split()) < 5 (мало слов!)
      3. next_duration > 5.0 (next длинный!)
      4. current_speaker != next_speaker
    - Действие: current_speaker = next_speaker (начало next реплики!)
    
    Args:
        segments: Список сегментов после alignment
        debug: Показывать debug output
    
    Returns:
        segments с исправленными speaker
    """
    if debug:
        print(f"\n🔧 Context-aware diarization correction v16.32...")
    
    corrections = 0
    
    for i in range(1, len(segments) - 1):
        prev_seg = segments[i - 1]
        current_seg = segments[i]
        next_seg = segments[i + 1]
        
        current_duration = current_seg['end'] - current_seg['start']
        current_speaker = current_seg.get('speaker')
        prev_speaker = prev_seg.get('speaker')
        next_speaker = next_seg.get('speaker')
        current_text = current_seg.get('text', '')
        next_duration = next_seg['end'] - next_seg['start']
        
        # 🆕 v16.32: Сценарий 2 - Очень короткий перед длинным (начало next реплики)
        if (current_duration < 1.0 and
            len(current_text.split()) < 5 and
            next_duration > 5.0 and
            next_speaker and
            current_speaker != next_speaker):
            
            old_speaker = current_speaker
            current_seg['speaker'] = next_speaker
            
            # Синхронизируем raw_speaker_id
            if 'raw_speaker_id' in next_seg:
                current_seg['raw_speaker_id'] = next_seg['raw_speaker_id']
            
            if debug:
                from core.utils import seconds_to_hms
                current_time = seconds_to_hms(current_seg.get('start', 0))
                text_preview = current_text[:40]
                word_count = len(current_text.split())
                print(f"  🔄 {current_time} ({current_duration:.2f}s, {word_count} слов): {old_speaker} → {next_speaker}")
                print(f"     Текст: \"{text_preview}...\"")
                print(f"     Причина: Очень короткий перед длинным next ({next_duration:.1f}s) → начало next реплики")
            
            corrections += 1
            continue  # Переходим к следующему сегменту
        
        # Сценарий 1 (v16.31): Короткий зажат между одинаковыми
        if (current_duration < 3.0 and 
            prev_speaker and next_speaker and 
            prev_speaker == next_speaker and 
            current_speaker != prev_speaker):
            
            old_speaker = current_speaker
            current_seg['speaker'] = prev_speaker
            
            # Синхронизируем raw_speaker_id
            if 'raw_speaker_id' in prev_seg:
                current_seg['raw_speaker_id'] = prev_seg['raw_speaker_id']
            
            if debug:
                from core.utils import seconds_to_hms
                current_time = seconds_to_hms(current_seg.get('start', 0))
                text_preview = current_text[:40]
                print(f"  🔄 {current_time} ({current_duration:.2f}s): {old_speaker} → {prev_speaker}")
                print(f"     Текст: \"{text_preview}...\"")
                print(f"     Причина: Зажат между одинаковыми prev={prev_speaker}")
            
            corrections += 1
    
    if debug:
        if corrections > 0:
            print(f"✅ Исправлено speaker: {corrections}")
        else:
            print(f"✅ Context-aware correction: ошибок не найдено")
    
    return segments
