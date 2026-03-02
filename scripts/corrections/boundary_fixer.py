#!/usr/bin/env python3
"""
corrections/boundary_fixer.py - Boundary correction v17.6

🔥 v17.6: КРИТИЧЕСКИЙ FIX БАГ #25 - Цитационные обороты (антипаттерн)
- Добавлена защита от цитируемой речи: "так и сказал", "товарищ сказал", "ответил, что"
- Расширены антипаттерны для косвенной речи: "говорил", "твердил", "утверждал"
- Исправлен баг: "Товарищ так и сказал, нет, вы без этих высот..." → Журналист (False positive)

🔥 v17.4: КРИТИЧЕСКИЙ FIX БАГ #21, #24 - False positive is_journalist_phrase
- Добавлена защита от ложных срабатываний в цитируемой/косвенной речи
- Контекстная проверка: если накоплено >100 слов в монологе → игнорируем «вы»/«давайте»
- Исправлены случаи: "Вы наваливаетесь..." (слова немцев), "давайте мы так больше..." (пересказ штаба)

🆕 v16.23: КРИТИЧЕСКИЙ FIX БАГ #4 - Raw speaker ID маппинг в split
🆕 v16.19: КРИТИЧЕСКИЙ FIX БАГ #3 - Повышен порог similarity с 80% до 90%
🔥 v16.16: КРИТИЧЕСКИЙ FIX - Word Boundary в regex паттернах!
"""

import re
from difflib import SequenceMatcher
from core.utils import seconds_to_hms

def is_journalist_phrase(text, context_words=0):
    """
    🔧 v17.19: BAG_E FIX — добавлен антипаттерн 'давайте я/мы/еще/ещё'
    🔥 v17.6: Защита от цитационных оборотов
    🔥 v17.4: Защита от false positive в длинных монологах
    """
    text_lower = text.lower()

    quotation_antipatterns = [
        r'\bтак и сказал\b',
        r'\bвот и сказал\b',
        r'\b(сказал|ответил|заявил|отметил|приказал|распорядился)\b.*\b(что|чтобы|нет|да)\b',
        r'\b(товарищ|командир|генерал|маршал|капитан|полковник)\s+\w+\s+(сказал|ответил|приказал|заявил)\b',
        r'\bкак\s+(он|они|мне|нам|ему|им)\s+(сказал|ответил|говорил)\b',
        r'\b(говорил|говорили|твердил|утверждал|утверждали|заявлял)\b',
        r'\bцитирую\b',
        r'\bпо\s+его\s+словам\b',
        r'\bпо\s+их\s+словам\b',
        # 🔧 v17.19: BAG_E — эксперт предлагает действие от себя/от нас
        r'\bдавайте\s+(я|мы|еще|ещё)\b',
    ]

    for pattern in quotation_antipatterns:
        if re.search(pattern, text_lower):
            return False

    strong_journalist_markers = [
        r'\bрасскажите\b',
        r'\bобъясните\b',
        r'\bкак\s+вы\b',
        r'\bпочему\s+вы\b',
        r'\bчто\s+вы\b',
        r'\bсмотрим\b',
    ]
    for marker in strong_journalist_markers:
        if re.search(marker, text_lower):
            return True

    weak_journalist_markers = [
        r'\bвы\s+(можете|могли|должны)?',
        r'\bдавайте\b',
    ]
    if context_words > 100:
        return False
    for marker in weak_journalist_markers:
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
        r'\bя\s+(считаю|думаю|полагаю)\b',
        r'\bна\s+мой\s+взгляд\b',
        r'\bпо\s+моему\s+мнению\b',
    ]
    
    for marker in expert_markers:
        if re.search(marker, text_lower):
            return True
    return False


def detect_continuation_phrase(current_text, previous_texts, threshold=0.90):
    """
    🔧 v16.19: КРИТИЧЕСКИЙ FIX БАГ #3 - Повышен порог similarity с 80% до 90%
    
    **ПРОБЛЕМА v16.16:**
    Порог 80% слишком низкий для детекции заикания.
    Заикание обычно имеет similarity 85-95% (почти идентичный текст).
    
    Примеры НЕ детектировались:
    - "...точки зрения коммуникации, «Невский пятачок», несмотря..." (similarity ~92%)
    - "...был прежде всего Леонид Говоров, была основа плана..." (similarity ~88%)
    
    **РЕШЕНИЕ v16.19:**
    Повысить порог до 90% для точной детекции заикания.
    
    Args:
        current_text: Текущий текст для проверки
        previous_texts: Список предыдущих текстов (для контекста)
        threshold: Порог similarity (теперь 0.90)
    
    Returns:
        (is_repetition, similarity, matched_text)
    """
    if not previous_texts:
        return False, 0.0, None
    
    current_lower = current_text.lower().strip()
    
    # Проверяем последние 2-3 предложения
    for prev_text in previous_texts[-3:]:
        prev_lower = prev_text.lower().strip()
        
        similarity = SequenceMatcher(None, current_lower, prev_lower).ratio()
        
        if similarity >= threshold:  # 🆕 v16.19: теперь 0.90
            return True, similarity, prev_text
    
    return False, 0.0, None


def is_continuation_phrase(text):
    """
    🆕 v16.10: Определяет continuation phrases (продолжение мысли)
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
            i += 1
            continue
        
        # Если экспертная фраза, а следующий спикер журналист
        if is_expert_text and next_speaker == "Журналист":
            i += 1
            continue
        
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
    🔥 v17.6: КРИТИЧЕСКИЙ FIX БАГ #25 - Цитационные обороты (антипаттерн)
    
    **ПРОБЛЕМА v17.4:**
    is_journalist_phrase не проверял цитационные обороты типа "так и сказал",
    "товарищ сказал", "ответил, что" — фразы с косвенной речью ошибочно детектировались
    как журналистские.
    
    Пример false positive:
    - БАГ #25: "Товарищ так и сказал, нет, вы без этих высот..." 
      → "вы" триггерил is_journalist_phrase, хотя это цитата Сталина/Жукова
    
    **РЕШЕНИЕ v17.6:**
    Добавлены антипаттерны цитирования в is_journalist_phrase().
    Если фраза содержит маркеры цитирования → автоматически НЕ журналист.
    
    🔥 v17.4: КРИТИЧЕСКИЙ FIX БАГ #21, #24 - False positive is_journalist_phrase
    🆕 v16.24.1: FIX #2 - Neutral фразы возвращаются к original speaker
    🆕 v16.23: КРИТИЧЕСКИЙ FIX БАГ #4 - Правильный raw_speaker_id маппинг!
    
    Args:
        segments_merged: Список merged сегментов
        speaker_surname: Фамилия спикера
        speaker_roles: Dict SPEAKER_XX → роль (для обратной конвертации)
        debug: Включить детальный debug output
    
    Returns:
        Список сегментов с разделенными mixed-speaker блоками
    """
    print("\n✂️ Разделение mixed-speaker сегментов (v17.6)...")
    
    # v16.23: УЛУЧШЕННЫЙ МАППИНГ - имена + роли → raw_speaker_id
    reverse_roles = {}
    
    # Сначала добавляем роли из speaker_roles
    for raw_id, role in speaker_roles.items():
        reverse_roles[role] = raw_id
    
    # v16.23: Добавляем speaker_surname → raw_speaker_id основного спикера
    if speaker_surname:
        main_speaker_id = None
        for raw_id, role in speaker_roles.items():
            if role not in ("Журналист", "Оператор"):
                main_speaker_id = raw_id
                break
        
        if main_speaker_id:
            reverse_roles[speaker_surname] = main_speaker_id
            print(f"  🔗 Маппинг: \"{speaker_surname}\" → {main_speaker_id}")
    
    print(f"  📋 Reverse roles: {reverse_roles}")
    
    result = []
    splitcount = 0
    continuation_fixed = 0
    protected_from_false_positive = 0  # v17.4: счётчик защиты контекста
    quotation_protected = 0  # 🆕 v17.6: счётчик защиты цитирования
    
    for seg_idx, seg in enumerate(segments_merged):
        speaker = seg.get('speaker')
        text = seg.get('text', '')
        start = seg.get('start', 0)
        end = seg.get('end', 0)
        duration = end - start
        
        # ЗАЩИТА: НЕ разделять анонсы вопросов
        if is_question_announcement(text):
            result.append(seg)
            continue
        
        # Разбиваем на предложения
        sentences = re.split(r'[.!?]+\s+', text)
        sentences = [s.strip() for s in sentences if s.strip()]
        
        if len(sentences) < 2:
            result.append(seg)
            continue
        
        # DEBUG HEADER
        if debug and len(sentences) >= 2:
            print(f"\n  🔍 АНАЛИЗ СЕГМЕНТА {seg.get('time', '???')} ({speaker}) — {len(sentences)} предложений")
        
        # 🆕 v16.24.1: Запоминаем ИСХОДНОГО спикера сегмента
        original_speaker = speaker
        
        # Анализируем каждое предложение на принадлежность спикеру
        current_group = []
        current_speaker = speaker
        
        total_words = sum(len(s.split()) for s in sentences)
        current_time = start
        
        for sent_idx, sentence in enumerate(sentences):
            sentence = sentence.strip()
            if not sentence:
                continue
            
            # v17.4: Вычисляем контекст (количество слов накопленных в current_group)
            context_words = sum(len(s.split()) for s in current_group)
            
            # 🆕 v17.6: Проверяем антипаттерн цитирования ДО вызова is_journalist_phrase
            has_quotation = False
            quotation_antipatterns = [
                r'\bтак и сказал\b',
                r'\bвот и сказал\b',
                r'\b(сказал|ответил|заявил|отметил|приказал)\b',
                r'\b(товарищ|командир|генерал)\s+\w+\s+(сказал|ответил)\b',
            ]
            for pattern in quotation_antipatterns:
                if re.search(pattern, sentence.lower()):
                    has_quotation = True
                    quotation_protected += 1
                    break
            
            # v17.6: Передаём context_words в is_journalist_phrase
            is_journalist_sent = is_journalist_phrase(sentence, context_words)
            is_expert_sent = is_expert_phrase(sentence, speaker_surname)
            is_continuation = is_continuation_phrase(sentence)
            
            # DEBUG OUTPUT для каждого предложения
            if debug:
                print(f"    [{sent_idx+1}] \"{sentence[:60]}...\"")
                print(f"        Journalist={is_journalist_sent} | Expert={is_expert_sent} | Continuation={is_continuation}")
                if context_words > 0:
                    print(f"        Context: {context_words} слов накоплено")
                if has_quotation:
                    print(f"        🛡️ АНТИПАТТЕРН: цитационный оборот обнаружен")
            
            # ПРАВИЛЬНАЯ ЛОГИКА ОПРЕДЕЛЕНИЯ СПИКЕРА
            sentence_speaker = None
            reason = ""
            
            if is_journalist_sent:
                sentence_speaker = "Журналист"
                reason = "is_journalist_phrase=True"
            elif is_expert_sent:
                sentence_speaker = speaker_surname
                reason = "is_expert_phrase=True"
            elif is_continuation:
                # CONTINUATION PHRASE LOGIC
                current_group_words = sum(len(s.split()) for s in current_group)
                
                if current_group_words > 80:
                    sentence_speaker = current_speaker
                    reason = f"continuation + context (>{current_group_words} слов)"
                    if debug:
                        print(f"        → {sentence_speaker} ({reason})")
                    continuation_fixed += 1
                else:
                    sentence_speaker = current_speaker
                    reason = f"continuation + inherit ({current_group_words} слов)"
            else:
                # v16.24.1: Нейтральная фраза - возвращаемся к ИСХОДНОМУ спикеру
                sentence_speaker = original_speaker
                reason = "neutral (return to original)"
            
            # v17.4: Если был применён контекст >100 слов, логируем
            if context_words > 100 and not is_journalist_sent:
                if re.search(r'\b(вы\s+|давайте\b)', sentence.lower()):
                    protected_from_false_positive += 1
                    if debug:
                        print(f"        🛡️ ЗАЩИТА: контекст {context_words} слов → игнорируем слабые паттерны")
            
            # DEBUG - показываем определённого спикера
            if debug:
                print(f"        → SPEAKER: {sentence_speaker} ({reason})")
            
            # Если спикер изменился - создаем новый сегмент
            if sentence_speaker != current_speaker and current_group:
                # DEBUG - логируем смену спикера
                if debug:
                    print(f"        ⚠️ СМЕНА СПИКЕРА: {current_speaker} → {sentence_speaker}")
                
                # Вычисляем пропорциональное время
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
                
                # v16.23: ПРАВИЛЬНЫЙ МАППИНГ через улучшенный reverse_roles
                newseg['raw_speaker_id'] = reverse_roles.get(
                    current_speaker, 
                    seg.get('raw_speaker_id')
                )
                
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
            newseg['end'] = end
            newseg['time'] = seconds_to_hms(current_time)
            
            # v16.23: ПРАВИЛЬНЫЙ МАППИНГ через улучшенный reverse_roles
            newseg['raw_speaker_id'] = reverse_roles.get(
                current_speaker,
                seg.get('raw_speaker_id')
            )
            
            result.append(newseg)
    
    if splitcount > 0:
        print(f"✅ Разделено: {splitcount} mixed сегментов")
    else:
        print(f"✅ Mixed сегментов не найдено")
    
    if continuation_fixed > 0:
        print(f"✅ Continuation phrases исправлено: {continuation_fixed}")
    
    # v17.4: Статистика защиты от false positive
    if protected_from_false_positive > 0:
        print(f"🛡️ Защита от false positive (контекст >100): {protected_from_false_positive} фраз")
    
    # 🆕 v17.6: Статистика защиты от цитирования
    if quotation_protected > 0:
        print(f"🛡️ Защита от цитирования: {quotation_protected} фраз")
    
    return result
