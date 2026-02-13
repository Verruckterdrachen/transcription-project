"""
export/txt_export.py - Экспорт в TXT формат

🔧 v16.26: FIX дублей timestamp - проверка наличия inner timestamps
"""

import json
import re
from pathlib import Path
from core.utils import seconds_to_hms

def insert_inner_timestamps(text, start_sec, end_sec, next_segment_exists):
    """
    🔧 v16.26: FIX дублей timestamp - проверка наличия inner timestamps
    
    ПРОБЛЕМА v16.25:
    - replica_merger (v16.19 ЭТАП 6.1) добавляет inner timestamps в merged segments
    - txt_export ТОЖЕ добавляет inner timestamps при экспорте
    - РЕЗУЛЬТАТ: ДУБЛИ! "00:00:56 00:00:56 Текст..."
    
    РЕШЕНИЕ v16.26:
    - Проверяем наличие timestamp (\d{2}:\d{2}:\d{2}) внутри текста
    - Если УЖЕ есть → НЕ добавляем (они от replica_merger!)
    - Если НЕТ → добавляем (короткий merged segment без inner timestamps)
    
    Для реплик длительностью > 30 секунд добавляет timestamp каждые ~25 секунд.
    
    Args:
        text: Текст реплики
        start_sec: Начало реплики (секунды)
        end_sec: Конец реплики (секунды)
        next_segment_exists: Есть ли следующий сегмент
    
    Returns:
        Текст с добавленными timestamps (если нужно)
    """
    # ✅ v16.26: Проверяем наличие inner timestamps от replica_merger
    has_inner_timestamps = bool(re.search(r'\d{2}:\d{2}:\d{2}', text))
    
    if has_inner_timestamps:
        return text  # УЖЕ есть timestamps от replica_merger (ЭТАП 6.1)!
    
    # ═════════════════════════════════════════════════════════════════════
    # ДАЛЕЕ: ЛОГИКА v16.25 (без изменений)
    # ═════════════════════════════════════════════════════════════════════
    
    duration = end_sec - start_sec
    
    # Короткие реплики не трогаем
    if duration <= 30:
        return text
    
    # Разбиваем на предложения (сохраняем знаки препинания)
    sentences = re.split(r'([.!?])\s*', text)
    
    if len(sentences) <= 2:
        return text
    
    # Склеиваем предложения с их знаками препинания
    sentence_list = []
    for i in range(0, len(sentences)-1, 2):
        if i+1 < len(sentences):
            sentence_list.append(sentences[i] + sentences[i+1])
        else:
            sentence_list.append(sentences[i])
    
    # Добавляем последний элемент если он остался
    if len(sentences) % 2 != 0:
        sentence_list.append(sentences[-1])
    
    # Вычисляем долю каждого предложения
    total_chars = sum(len(s) for s in sentence_list)
    
    if total_chars == 0:
        return text
    
    # Распределяем время по предложениям
    sentence_times = []
    current_time = start_sec
    
    for sentence in sentence_list:
        char_ratio = len(sentence) / total_chars
        sentence_duration = duration * char_ratio
        sentence_times.append({
            "text": sentence,
            "start": current_time,
            "end": current_time + sentence_duration
        })
        current_time += sentence_duration
    
    # Вставляем timestamps
    result = []
    last_timestamp_at = start_sec
    
    for i, sent_info in enumerate(sentence_times):
        sent_start = sent_info["start"]
        sent_text = sent_info["text"]
        
        time_since_last = sent_start - last_timestamp_at
        time_to_end = end_sec - sent_start
        
        # Вставляем timestamp если:
        # 1. НЕ первое предложение (i > 0) - v16.25!
        # 2. Прошло >= 25 секунд с последнего timestamp
        # 3. И до конца реплики >= 30 секунд (или это последняя реплика файла)
        should_insert = (
            i > 0 and  # v16.25: КРИТИЧЕСКОЕ! Первое предложение БЕЗ inner timestamp!
            time_since_last >= 25 and 
            (time_to_end >= 30 or not next_segment_exists)
        )
        
        if should_insert:
            timestamp_str = seconds_to_hms(sent_start)
            # Timestamp ПЕРЕД текстом (без \n!)
            result.append(f" {timestamp_str} {sent_text}")
            last_timestamp_at = sent_start
        else:
            # Обычное добавление (с пробелом если не первое предложение)
            if i > 0:
                result.append(f" {sent_text}")
            else:
                result.append(sent_text)
    
    return ''.join(result)

def export_to_txt(txt_path, segments, speaker_surname):
    """
    Экспорт одного JSON в TXT
    
    Args:
        txt_path: Path к TXT файлу
        segments: Список merged сегментов
        speaker_surname: Фамилия спикера
    """
    with open(txt_path, 'w', encoding='utf-8') as f:
        for i, seg in enumerate(segments):
            time = seg.get('time', '00:00:00')
            speaker = seg.get('speaker', 'Неизвестно')
            text = seg.get('text', '')
            start = seg.get('start', 0)
            end = seg.get('end', 0)
            
            # Проверяем, есть ли следующий сегмент
            next_segment_exists = (i + 1) < len(segments)
            
            # Добавляем inner timestamps для длинных реплик
            text_with_timestamps = insert_inner_timestamps(
                text, start, end, next_segment_exists
            )
            
            # Форматируем
            f.write(f"{time} {speaker}: {text_with_timestamps}\n")
    
    return txt_path

def jsons_to_txt(json_files, txt_path, speaker_surname):
    """
    🔧 v16.26: FIX дублей timestamp - проверка наличия inner timestamps
    
    Объединяет все JSON файлы интервью в единый TXT с правильной нумерацией
    и временными метками внутри длинных реплик.
    
    Args:
        json_files: Список Path к JSON файлам
        txt_path: Path к итоговому TXT файлу
        speaker_surname: Фамилия спикера
    
    Returns:
        Path к созданному TXT файлу
    """
    print(f"\n📄 {len(json_files)} JSON → {txt_path.name}")
    
    all_segments = []
    
    # Собираем все сегменты из всех JSON
    for json_file in json_files:
        try:
            with open(json_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            merged_segs = data.get('segments_merged', [])
            filename_original = data.get('file', json_file.stem)
            
            # Добавляем маркер файла
            all_segments.append({
                "type": "file",
                "filename": filename_original
            })
            
            # Добавляем сегменты
            for seg in merged_segs:
                all_segments.append({
                    "type": "speaker",
                    "time": seg.get('time', '00:00:00'),
                    "speaker": seg.get('speaker', ''),
                    "text": seg.get('text', ''),
                    "start": seg.get('start', 0),
                    "end": seg.get('end', 0)
                })
        
        except Exception as e:
            print(f"  ⚠️ {json_file.name}: {e}")
            continue
    
    # Записываем TXT
    with open(txt_path, 'w', encoding='utf-8') as f:
        first_file = True
        
        for idx, seg in enumerate(all_segments):
            if seg["type"] == "file":
                # Разделитель между файлами
                if not first_file:
                    f.write("\n" + "=" * 70 + "\n\n")
                
                # Убран # из названия файла
                filename_clean = Path(seg["filename"]).stem
                f.write(f"{filename_clean}\n\n")
                first_file = False
            
            else:
                # Проверяем, есть ли следующий сегмент
                next_segment_exists = False
                if idx + 1 < len(all_segments):
                    next_seg = all_segments[idx + 1]
                    if next_seg["type"] in ("speaker", "file"):
                        next_segment_exists = True
                
                # Добавляем inner timestamps
                text_with_timestamps = insert_inner_timestamps(
                    seg["text"],
                    seg["start"],
                    seg["end"],
                    next_segment_exists
                )
                
                f.write(f"{seg['time']} {seg['speaker']}: {text_with_timestamps}\n")
    
    print(f" ✅ TXT: {txt_path.name} (v16.26 - no duplicate timestamps)")
    return txt_path
