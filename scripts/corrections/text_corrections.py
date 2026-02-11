#!/usr/bin/env python3
"""
corrections/text_corrections.py - Text-based speaker correction v16.4

🆕 v16.4: КРИТИЧЕСКИЕ ИСПРАВЛЕНИЯ
- Защита от переатрибуции анонсов вопросов ("Следующий вопрос про...")
- Context window protection (не трогать сегменты внутри монологов >60s)
- Confirmation pattern detection ("Ну да", "Да-да" как подтверждение)
- Announcement vs Question distinction (анонс ≠ полный вопрос)
- Short segment protection внутри монологов
"""

import re


def is_journalist_command(text):
    """
    v16.3.2: Проверяет, является ли текст командой журналиста
    
    Команды журналиста НЕ должны переатрибутироваться спикеру,
    даже если в них есть маркеры эксперта
    """
    text_lower = text.lower()
    
    commands = [
        r'давайте',
        r'смотрим',
        r'представьтесь',
        r'расскажите',
        r'объясните',
        r'покажите',
        r'повторите',
    ]
    
    for cmd in commands:
        if re.search(cmd, text_lower):
            return True
    return False


def is_question_segment(text):
    """
    v16.3.2: Проверяет, является ли сегмент вопросом
    
    Вопросы задает журналист, не переатрибутировать
    """
    text_lower = text.lower()
    
    question_markers = [
        r'\?$',  # Заканчивается на ?
        r'^первый вопрос',  # "Первый вопрос", "11-й вопрос"
        r'^второй вопрос',
        r'^третий вопрос',
        r'^\d+[-й\s]+вопрос',
        r'^расскажите',
        r'^объясните',
        r'^как\s+',
        r'^почему\s+',
        r'^что\s+',
        r'^каков',
        r'^в\s+чем',
    ]
    
    for marker in question_markers:
        if re.search(marker, text_lower):
            return True
    return False


def is_question_announcement(text):
    """
    🆕 v16.4: Определяет, является ли текст анонсом вопроса (не сам вопрос)
    
    Анонс: "Следующий вопрос про наступление"
    Вопрос: "С какой целью был занят плацдарм..."
    
    Args:
        text: Текст сегмента
    
    Returns:
        True если это анонс вопроса
    """
    text_lower = text.lower()
    
    announcement_patterns = [
        r'следующий вопрос\s+(про|о|об)',  # "Следующий вопрос про..."
        r'еще вопрос\s+(про|о|об)',
        r'другой вопрос\s+(про|о|об)',
        r'дальше вопрос\s+(про|о|об)',
    ]
    
    for pattern in announcement_patterns:
        if re.search(pattern, text_lower):
            # Проверяем, что это короткая фраза (не развернутый вопрос)
            word_count = len(text.split())
            if word_count < 20:  # Анонсы обычно короткие
                return True
    
    return False


def is_confirmation(text):
    """
    🆕 v16.4: Проверяет, является ли текст подтверждением
    
    Подтверждения: "Ну да", "Да-да", "Угу", "Верно"
    
    Args:
        text: Текст сегмента
    
    Returns:
        True если это подтверждение
    """
    text_lower = text.lower().strip()
    
    confirmation_patterns = [
        r'^ну\s+да',
        r'^да[-,\s]',
        r'^да\.',
        r'^угу',
        r'^ага',
        r'^мм[-\s]?хм',
        r'^верно',
        r'^правильно',
        r'^точно',
        r'^именно',
        r'^конечно',
        r'^хорошо$',
        r'^ладно$',
    ]
    
    for pattern in confirmation_patterns:
        if re.match(pattern, text_lower):
            return True
    return False


def is_inside_long_monologue(segment, all_segments, index, threshold=60):
    """
    🆕 v16.4: Проверяет, находится ли сегмент внутри длинного монолога (>60s)
    одного спикера БЕЗ прерываний другим спикером
    
    Args:
        segment: Текущий сегмент
        all_segments: Все сегменты
        index: Индекс текущего сегмента
        threshold: Минимальная длительность монолога (секунды)
    
    Returns:
        True если сегмент внутри длинного монолога
    """
    speaker = segment.get('speaker')
    
    # Ищем начало монолога (последний переход спикера)
    monologue_start_idx = 0
    for i in range(index - 1, -1, -1):
        if all_segments[i].get('speaker') != speaker:
            monologue_start_idx = i + 1
            break
    
    # Ищем конец монолога (следующий переход спикера)
    monologue_end_idx = len(all_segments) - 1
    for i in range(index + 1, len(all_segments)):
        if all_segments[i].get('speaker') != speaker:
            monologue_end_idx = i - 1
            break
    
    # Вычисляем длительность монолога
    monologue_duration = (
        all_segments[monologue_end_idx].get('end', 0) - 
        all_segments[monologue_start_idx].get('start', 0)
    )
    
    return monologue_duration > threshold


def text_based_correction(segments_merged, speaker_surname):
    """
    v16.4: Text-based speaker correction с расширенной защитой
    
    Применяет коррекцию спикеров на основе текстовых маркеров:
    1. Детекция представления эксперта ("Меня зовут...", "Фамилия Имя...")
    2. Переатрибуция Журналист → Эксперт если есть маркеры
    
    🆕 v16.4 ЗАЩИТЫ:
    1. Пропускает первые 2 сегмента (представление)
    2. Защита от команд журналиста
    3. Защита от вопросов
    4. 🆕 Защита от сегментов внутри длинных монологов (>60s)
    5. 🆕 Защита от анонсов вопросов с подтверждением
    
    Args:
        segments_merged: Список merged сегментов
        speaker_surname: Фамилия спикера
    
    Returns:
        segments_merged с исправленными атрибуциями
    """
    if not speaker_surname or not segments_merged:
        return segments_merged
    
    corrections = 0
    surname_lower = speaker_surname.lower()
    
    # Маркеры представления эксперта
    introduction_markers = [
        surname_lower,  # Фамилия
        r'меня\s+зовут',
        r'я\s+' + surname_lower,
        r'это\s+' + surname_lower,
        r'профессор',
        r'доктор\s+(наук|исторических)',
        r'кандидат\s+(наук|исторических)',
    ]
    
    for i, seg in enumerate(segments_merged):
        speaker = seg.get('speaker')
        text = seg.get('text', '')
        text_lower = text.lower()
        
        # ЗАЩИТА 1: Пропускаем первые 2 сегмента
        if i < 2:
            continue
        
        # ЗАЩИТА 2: Пропускаем команды журналиста
        if is_journalist_command(text):
            continue
        
        # ЗАЩИТА 3: Пропускаем вопросы
        if is_question_segment(text):
            continue
        
        # 🆕 ЗАЩИТА 4: Пропускаем сегменты внутри длинных монологов (>60s)
        if is_inside_long_monologue(seg, segments_merged, i, threshold=60):
            monologue_duration = 0
            # Вычисляем для debug
            speaker_current = seg.get('speaker')
            start_idx = i
            for j in range(i - 1, -1, -1):
                if segments_merged[j].get('speaker') != speaker_current:
                    start_idx = j + 1
                    break
            end_idx = i
            for j in range(i + 1, len(segments_merged)):
                if segments_merged[j].get('speaker') != speaker_current:
                    end_idx = j - 1
                    break
            monologue_duration = (
                segments_merged[end_idx].get('end', 0) - 
                segments_merged[start_idx].get('start', 0)
            )
            print(f"  🛡️ ЗАЩИТА: {seg.get('time')} внутри монолога {monologue_duration:.1f}s")
            continue
        
        # 🆕 ЗАЩИТА 5: Пропускаем анонсы вопросов с подтверждением
        if (is_question_announcement(text) and 
            i < len(segments_merged) - 1):
            next_seg = segments_merged[i + 1]
            next_text = next_seg.get('text', '')
            if is_confirmation(next_text):
                print(f"  🛡️ ЗАЩИТА: {seg.get('time')} анонс вопроса + подтверждение")
                continue
        
        # Проверяем маркеры представления эксперта
        if speaker != speaker_surname:
            has_marker = False
            for marker in introduction_markers:
                if re.search(marker, text_lower):
                    has_marker = True
                    break
            
            if has_marker:
                print(f"  ✏️ TEXT-FIX: {seg.get('time', '???')} Журналист → {speaker_surname}")
                seg['speaker'] = speaker_surname
                corrections += 1
    
    if corrections > 0:
        print(f"✅ Text-based corrections: {corrections}")
    else:
        print(f"✅ Text-based corrections: 0 (все верно)")
    
    return segments_merged
