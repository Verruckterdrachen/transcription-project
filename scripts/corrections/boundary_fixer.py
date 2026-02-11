#!/usr/bin/env python3
"""
corrections/boundary_fixer.py - Boundary correction v16.16

🔥 v16.16: КРИТИЧЕСКИЙ FIX - Word Boundary в regex паттернах!
- Добавлен \\b (word boundary) в начале всех regex паттернов
- Исправлен баг: 'вы\\s+' ловил "вы " внутри слов (Невы, совы, кровы)
- Теперь поиск только целых слов: '\\bвы\\s+', '\\bрасскажите\\b' и т.д.
- Предотвращение FALSE POSITIVE в is_journalist_phrase() и is_expert_phrase()

🆕 v16.15: DEBUG OUTPUT ДЛЯ SPLIT - находим виновника!
- Детальный debug output для каждого предложения
- Показ результатов проверок (is_journalist/expert/continuation)
- Логирование смены current_speaker с причиной
- Поможет найти КАКОЕ предложение ошибочно определяется

🆕 v16.12: КРИТИЧЕСКИЙ FIX RAW_SPEAKER_ID В SPLIT
- При split обновляется не только speaker, но и raw_speaker_id
- Создан обратный маппинг speaker_roles для конвертации
- Исправлен баг: TXT выводил старый speaker вместо нового
"""

import re
from core.utils import seconds_to_hms


def is_journalist_phrase(text):
    """
    v16.16: Проверяет, является ли фраза журналистской
    
    🔥 v16.16: Добавлен \\b (word boundary) для точного поиска целых слов
    """
    text_lower = text.lower()
    
    journalist_markers = [
        r'\bвы\s+(можете|могли|должны)?',  # 🔥 v16.16: добавлен \b
        r'\bрасскажите\b',                  # 🔥 v16.16: добавлен \b
        r'\bобъясните\b',                   # 🔥 v16.16: добавлен \b
        r'\bкак\s+вы\b',                    # 🔥 v16.16: добавлен \b
        r'\bпочему\s+вы\b',                 # 🔥 v16.16: добавлен \b
        r'\bчто\s+вы\b',                    # 🔥 v16.16: добавлен \b
        r'\bдавайте\b',                     # 🔥 v16.16: добавлен \b
        r'\bсмотрим\b',                     # 🔥 v16.16: добавлен \b
    ]
    
    for marker in journalist_markers:
        if re.search(marker, text_lower):
            return True
    return False


def is_expert_phrase(text, speaker_surname):
    """
    v16.16: Проверяет, является ли фраза экспертной
    
    🔥 v16.16: Добавлен \\b (word boundary) для точного поиска целых слов
    """
    if not speaker_surname:
        return False
    
    text_lower = text.lower()
    surname_lower = speaker_surname.lower()
    
    expert_markers = [
        surname_lower,
        r'\bя\s+(считаю|думаю|полагаю)\b',  # 🔥 v16.16: добавлен \b
        r'\bна\s+мой\s+взгляд\b',            # 🔥 v16.16: добавлен \b
        r'\bпо\s+моему\s+мнению\b',          # 🔥 v16.16: добавлен \b
    ]
    
    for marker in expert_markers:
        if re.search(marker, text_lower):
            return True
    return False


def is_continuation_phrase(text):
    """
    🆕 v16.10: Определяет continuation phrases (продолжение мысли)
    
    Эти фразы обычно продолжают предыдущую мысль того же спикера:
    - "То есть..."
    - "В частности..."
    - "Кроме того..."
    - "Также..."
    - "Иными словами..."
    
    Args:
        text: Текст предложения
    
    Returns:
        True если это continuation phrase
    """
    text_lower = text.lower().strip()
    
    continuation_patterns = [
        r'^то\s+есть\b',
        r'^в\s+частности\b',
        r'^кроме\s+того\b',
        r'^также\b',
        r'^иными\s+словами\b',
        r'^другими\s+словами\b',
        r'^более\s+того\b',
        r'^помимо\s+этого\b',
        r'^при\s+этом\b',
        r'^однако\b',
        r'^тем\s+не\s+менее\b',
        r'^впрочем\b',
    ]
    
    for pattern in continuation_patterns:
        if re.search(pattern, text_lower):
            return True
    
    return False


def is_question_announcement(text):
    """
    🆕 v16.4: Определяет, является ли текст анонсом вопроса
    
    Защита: НЕ split анонсы вопросов
    """
    text_lower = text.lower()
    
    announcement_patterns = [
        r'следующий вопрос\s+(про|о|об)',
        r'еще вопрос\s+(про|о|об)',
        r'другой вопрос\s+(про|о|об)',
    ]
    
    for pattern in announcement_patterns:
        if re.search(pattern, text_lower):
            word_count = len(text.split())
            if word_count < 20:
                return True
    return False


def boundary_correction_raw(segments_raw, speaker_surname, speaker_roles):
    """
    v16.3.2: Boundary correction между спикерами
    
    Корректирует границы между сегментами разных спикеров:
    1. Находит короткие последние предложения (≤10 слов)
    2. Проверяет паузу < 0.5s до следующего спикера
    3. Анализирует семантику (журналистская/экспертная фраза)
    4. Переносит последнее предложение к следующему спикеру
    
    Args:
        segments_raw: raw segments после alignment
        speaker_surname: Фамилия спикера
        speaker_roles: Dict SPEAKER_XX → роль
    
    Returns:
        segments_raw с исправленными границами
    """
    if len(segments_raw) < 2:
        return segments_raw
    
    corrections = 0
    i = 0
    
    while i < len(segments_raw) - 1:
        current = segments_raw[i]
        next_seg = segments_raw[i + 1]
        
        current_speaker = current.get('speaker')
        next_speaker = next_seg.get('speaker')
        
        # Пропускаем если тот же спикер
        if current_speaker == next_speaker:
            i += 1
            continue
        
        # Разбиваем текст на предложения
        current_text = current.get('text', '')
        sentences = re.split(r'[.!?]+\s+', current_text)
        
        if len(sentences) < 2:
            i += 1
            continue
        
        # Берем последнее предложение
        last_sentence = sentences[-1].strip()
        word_count = len(last_sentence.split())
        
        # Пропускаем если последнее предложение длинное
        if word_count > 10:
            i += 1
            continue
        
        # Проверяем паузу между сегментами
        current_end = current.get('end', 0)
        next_start = next_seg.get('start', 0)
        pause = next_start - current_end
        
        if pause > 0.5:
            i += 1
            continue
        
        # Анализируем семантику
        is_journalist_text = is_journalist_phrase(last_sentence)
        is_expert_text = is_expert_phrase(last_sentence, speaker_surname)
        
        # Если журналистская фраза, а следующий спикер НЕ журналист
        if is_journalist_text and next_speaker != "Журналист":
            # Переносим фразу к следующему сегменту (исправление)
            next_speaker = "Журналист"
            i += 1
            continue  # НЕ переносим, ошибка атрибуции
        
        # Если экспертная фраза, а следующий спикер журналист
        if is_expert_text and next_speaker == "Журналист":
            # Переносим фразу к следующему сегменту (исправление)
            next_speaker = speaker_surname
            i += 1
            continue  # НЕ переносим, ошибка атрибуции
        
        # Переносим последнее предложение
        remaining_text = '. '.join(sentences[:-1])
        if remaining_text:
            remaining_text = remaining_text.strip() + '.'
            current['text'] = remaining_text
        
        # Добавляем к следующему сегменту
        next_seg_text = f"{last_sentence} {next_seg.get('text', '')}"
        next_seg['text'] = next_seg_text.strip()
        
        print(f"  ✂️ BOUNDARY FIX: {next_seg.get('start_hms', '???')} перенос → {next_speaker}")
        print(f"     \"{last_sentence}\"")
        
        corrections += 1
        i += 1
    
    if corrections > 0:
        print(f"✅ Boundary correction: {corrections}")
    
    return segments_raw


def split_mixed_speaker_segments(segments_merged, speaker_surname, speaker_roles, debug=True):
    """
    v16.16: КРИТИЧЕСКИЙ FIX - Word Boundary в regex паттернах!
    
    🔥 v16.16 ИЗМЕНЕНИЯ:
    - Использует обновлённые is_journalist_phrase() и is_expert_phrase()
    - Исправлен баг FALSE POSITIVE: "Невы" больше не считается "вы"
    - Точное определение журналистских/экспертных фраз
    
    🆕 v16.15 ИЗМЕНЕНИЯ:
    - Детальный debug output для каждого предложения в split
    - Показ результатов is_journalist_phrase, is_expert_phrase, is_continuation
    - Логирование смены current_speaker с указанием причины
    - Параметр debug=True для включения детального вывода
    
    🆕 v16.12 ИЗМЕНЕНИЯ:
    - При split обновляется НЕ ТОЛЬКО speaker, но и raw_speaker_id
    - Создан обратный маппинг speaker_roles для конвертации (Исаев → SPEAKER_01)
    - Исправлен баг: TXT выводил старый speaker из-за несинхронизации полей
    
    Args:
        segments_merged: Список merged сегментов
        speaker_surname: Фамилия спикера
        speaker_roles: Dict SPEAKER_XX → роль (для обратной конвертации)
        debug: Включить детальный debug output
    
    Returns:
        Список сегментов с разделенными mixed-speaker блоками
    """
    print("\n✂️ Разделение mixed-speaker сегментов...")
    
    # 🆕 v16.12: Создаём обратный маппинг speaker → raw_speaker_id
    reverse_roles = {}
    for raw_id, role in speaker_roles.items():
        reverse_roles[role] = raw_id
    
    result = []
    splitcount = 0
    continuation_fixed = 0
    
    for seg_idx, seg in enumerate(segments_merged):
        speaker = seg.get('speaker')
        text = seg.get('text', '')
        start = seg.get('start', 0)
        end = seg.get('end', 0)
        duration = end - start
        
        # 🆕 ЗАЩИТА: НЕ разделять анонсы вопросов
        if is_question_announcement(text):
            result.append(seg)
            continue
        
        # Разбиваем на предложения
        sentences = re.split(r'[.!?]+\s+', text)
        sentences = [s.strip() for s in sentences if s.strip()]
        
        if len(sentences) < 2:
            result.append(seg)
            continue
        
        # 🆕 v16.15: DEBUG HEADER
        if debug and len(sentences) >= 2:
            print(f"\n  🔍 АНАЛИЗ СЕГМЕНТА: {seconds_to_hms(start)} ({speaker}) — {len(sentences)} предложений")
        
        # Анализируем каждое предложение на принадлежность спикеру
        current_group = []
        current_speaker = speaker
        
        total_words = sum(len(s.split()) for s in sentences)
        current_time = start
        
        for sent_idx, sentence in enumerate(sentences):
            sentence = sentence.strip()
            if not sentence:
                continue
            
            is_journalist_sent = is_journalist_phrase(sentence)
            is_expert_sent = is_expert_phrase(sentence, speaker_surname)
            is_continuation = is_continuation_phrase(sentence)
            
            # 🆕 v16.15: DEBUG OUTPUT для каждого предложения
            if debug:
                print(f"    [{sent_idx+1}] \"{sentence[:60]}...\"")
                print(f"        Journalist={is_journalist_sent} | Expert={is_expert_sent} | Continuation={is_continuation}")
            
            # 🆕 v16.11: ПРАВИЛЬНАЯ ЛОГИКА ОПРЕДЕЛЕНИЯ СПИКЕРА
            sentence_speaker = None
            reason = ""
            
            if is_journalist_sent:
                sentence_speaker = "Журналист"
                reason = "is_journalist_phrase=True"
            elif is_expert_sent:
                sentence_speaker = speaker_surname
                reason = "is_expert_phrase=True"
            elif is_continuation:
                # 🔧 v16.11: CONTINUATION PHRASE LOGIC
                # Проверяем контекст ВНУТРИ текущего split
                current_group_words = sum(len(s.split()) for s in current_group)
                
                # Если УЖЕ накоплено много слов (>80) → продолжение текущего монолога
                if current_group_words > 80:
                    sentence_speaker = current_speaker
                    reason = f"continuation + context (>{current_group_words} слов)"
                    if debug:
                        print(f"        → {sentence_speaker} ({reason})")
                    continuation_fixed += 1
                else:
                    # Если мало накоплено, используем контекст сегмента
                    sentence_speaker = current_speaker
                    reason = f"continuation + inherit ({current_group_words} слов)"
            else:
                # Нейтральная фраза - используем контекст
                sentence_speaker = current_speaker
                reason = "neutral (inherit)"
            
            # 🆕 v16.15: DEBUG - показываем определённого спикера
            if debug:
                print(f"        → SPEAKER: {sentence_speaker} ({reason})")
            
            # Если спикер изменился - создаем новый сегмент
            if sentence_speaker != current_speaker and current_group:
                # 🆕 v16.15: DEBUG - логируем смену спикера
                if debug:
                    print(f"        ⚠️ СМЕНА СПИКЕРА: {current_speaker} → {sentence_speaker}")
                
                # 🆕 Вычисляем пропорциональное время
                group_text = '. '.join(current_group) + '.'
                group_words = len(group_text.split())
                group_duration = (group_words / total_words) * duration if total_words > 0 else 0
                group_end = current_time + group_duration
                
                newseg = seg.copy()
                newseg['text'] = group_text
                newseg['speaker'] = current_speaker
                newseg['start'] = current_time
                newseg['end'] = group_end
                newseg['time'] = seconds_to_hms(current_time)
                
                # 🆕 v16.12: ОБНОВЛЯЕМ raw_speaker_id через обратный маппинг
                newseg['raw_speaker_id'] = reverse_roles.get(current_speaker, seg.get('raw_speaker_id'))
                
                result.append(newseg)
                splitcount += 1
                
                print(f"  ✂️ SPLIT: {newseg['time']} ({current_speaker}) \"{group_text[:50]}...\"")
                
                # Сбрасываем группу
                current_group = []
                current_time = group_end
                current_speaker = sentence_speaker
            
            current_group.append(sentence)
        
        # Добавляем последнюю группу
        if current_group:
            group_text = '. '.join(current_group) + '.'
            
            newseg = seg.copy()
            newseg['text'] = group_text
            newseg['speaker'] = current_speaker
            newseg['start'] = current_time
            newseg['end'] = end  # До конца оригинального сегмента
            newseg['time'] = seconds_to_hms(current_time)
            
            # 🆕 v16.12: ОБНОВЛЯЕМ raw_speaker_id через обратный маппинг
            newseg['raw_speaker_id'] = reverse_roles.get(current_speaker, seg.get('raw_speaker_id'))
            
            result.append(newseg)
    
    if splitcount > 0:
        print(f"✅ Разделено: {splitcount} mixed сегментов")
    else:
        print(f"✅ Mixed сегментов не найдено")
    
    if continuation_fixed > 0:
        print(f"✅ Continuation phrases исправлено: {continuation_fixed}")
    
    return result
