#!/usr/bin/env python3
"""
corrections/hallucinations.py - Удаление галлюцинаций Whisper

🔧 v16.28: clean_loops() НЕ удаляет - заменяет на "..."
- Вместо удаления repeating n-grams → замена на "..."
- Threshold: 95% (очень строго!)
- Min n-gram size: 4 слова (не 2!)
- Сохраняем контекст, НЕ теряем смысл

🆕 v16.19: КРИТИЧЕСКИЙ FIX - Удаление дублей + "Продолжение следует"
- Детекция дублированных фраз (similarity >95%)
- Удаление Whisper hallucination в конце файла ("Продолжение следует", "Спасибо за внимание")
- Удаление дублей с разным регистром ("логичным Логичным")
"""

import re
from difflib import SequenceMatcher


def is_hallucination(text):
    """
    ✅ LEGACY FUNCTION (для обратной совместимости с transcription.py)
    
    Простая проверка, является ли текст галлюцинацией Whisper.
    
    Типичные галлюцинации:
    - Пустой текст
    - Только пробелы/пунктуация
    - Короткие бессмысленные фразы
    - Повторяющиеся символы
    
    Args:
        text: Текст для проверки
    
    Returns:
        bool: True если это галлюцинация
    """
    if not text or not text.strip():
        return True
    
    # Убираем пунктуацию
    clean = re.sub(r'[^\w\s]', '', text)
    
    # Только пробелы
    if not clean.strip():
        return True
    
    # Слишком короткий (меньше 3 символов)
    if len(clean.strip()) < 3:
        return True
    
    # Повторяющиеся символы (например "ааааа")
    if len(set(clean.lower())) < 3:
        return True
    
    return False


def clean_loops(text, is_gap_filled=False, debug=False):
    """
    🔧 v16.28: ЗАМЕНЯЕТ hallucination loops на "..." (НЕ удаляет!)
    
    v16.27 проблема: удаление текста → потеря смысла
    v16.28 решение: замена на "..." → сохранение контекста
    
    Whisper иногда создаёт петли при force-transcribe gaps:
    "учитывать была немецкая артиллерия вправь до еще фактором
     которые надо учитывать это было немецкая вплоть до"
    
    БЫЛО (v16.27): "учитывать была немецкая артиллерия"  ❌ потеря текста!
    СТАЛО (v16.28): "учитывать ... немецкая артиллерия" ✅ контекст сохранён!
    
    Алгоритм:
    1. Разбивает текст на слова
    2. Создаёт n-граммы (4-8 слов, не 2!)
    3. Ищет ОЧЕНЬ похожие n-граммы (similarity >= 95%)
    4. Заменяет повторы на "..." (НЕ удаляет!)
    
    Args:
        text: Текст для очистки
        is_gap_filled: Это gap-filled сегмент (строже)
        debug: Показывать debug output
    
    Returns:
        Текст с "..." вместо loops
    """
    if not text or len(text) < 30:
        return text
    
    # Нормализуем: пунктуация → пробелы
    normalized = re.sub(r'[^\w\s]', ' ', text.lower())
    words = [w for w in normalized.split() if w]
    
    if len(words) < 8:
        return text  # Слишком короткий
    
    # Ищем repeating n-grams
    loop_positions = []  # [(start_word_idx, end_word_idx, ngram_text), ...]
    
    # 🆕 v16.28: min_size=4 (не 2!), max_size=8
    for ngram_size in range(8, 3, -1):  # 8→4 (не 8→2!)
        if ngram_size > len(words) // 3:  # Не больше 1/3 текста
            continue
        
        # 🆕 v16.28: СТРОГИЙ threshold 95% (не 75-85%!)
        threshold = 0.95
        
        # Gap-filled: threshold 97% (ещё строже!)
        if is_gap_filled:
            threshold = 0.97
        
        # Минимальное расстояние между n-граммами
        min_distance = max(ngram_size, 4)
        
        # Создаём n-граммы
        ngrams = []
        for i in range(len(words) - ngram_size + 1):
            # Пропускаем уже найденные loops
            if any(start <= i < end for start, end, _ in loop_positions):
                continue
            
            ngram = ' '.join(words[i:i+ngram_size])
            ngrams.append((i, ngram))
        
        # Ищем повторы
        for idx1, (pos1, ngram1) in enumerate(ngrams):
            if any(start <= pos1 < end for start, end, _ in loop_positions):
                continue
            
            for pos2, ngram2 in ngrams[idx1+1:]:
                # Проверяем расстояние
                if pos2 - pos1 < min_distance:
                    continue
                
                # Уже найдено?
                if any(start <= pos2 < end for start, end, _ in loop_positions):
                    continue
                
                # Similarity
                similarity = SequenceMatcher(None, ngram1, ngram2).ratio()
                
                if similarity >= threshold:
                    if debug:
                        print(f"  🔍 LOOP (n={ngram_size}, sim={similarity:.0%}): \"{ngram1}\" ≈ \"{ngram2}\"")
                    
                    # 🆕 v16.28: Помечаем для замены на "..."
                    loop_positions.append((pos1, pos1 + ngram_size, ngram1))
                    loop_positions.append((pos2, pos2 + ngram_size, ngram2))
                    break  # Нашли loop для этой n-граммы
    
    # Если нашли loops → заменяем на "..."
    if loop_positions:
        # Сортируем по start position
        loop_positions.sort()
        
        # Объединяем пересекающиеся диапазоны
        merged_loops = []
        for start, end, ngram_text in loop_positions:
            if merged_loops and start < merged_loops[-1][1]:
                # Пересечение → расширяем последний
                merged_loops[-1] = (merged_loops[-1][0], max(merged_loops[-1][1], end))
            else:
                merged_loops.append((start, end))
        
        # 🆕 v16.28: Заменяем loops на "..."
        original_words = text.split()
        result_words = []
        norm_idx = 0
        last_was_ellipsis = False
        
        for orig_word in original_words:
            # Убираем пунктуацию для сопоставления
            word_clean = re.sub(r'[^\w]', '', orig_word.lower())
            
            if word_clean:  # Не пустое слово
                # Проверяем: это loop?
                is_in_loop = any(start <= norm_idx < end for start, end in merged_loops)
                
                if is_in_loop:
                    # Вставляем "..." только ОДИН раз на loop
                    if not last_was_ellipsis:
                        result_words.append("...")
                        last_was_ellipsis = True
                else:
                    result_words.append(orig_word)
                    last_was_ellipsis = False
                
                norm_idx += 1
            else:
                # Пунктуация между словами
                if result_words and not last_was_ellipsis:
                    result_words.append(orig_word)
        
        cleaned_text = ' '.join(result_words)
        
        # Очистка двойных пробелов
        cleaned_text = re.sub(r'\s+', ' ', cleaned_text).strip()
        
        if debug:
            print(f"  ✅ Loops replaced with '...': {len(original_words)} → {len(result_words)} слов")
        
        return cleaned_text
    
    return text


def is_duplicate_phrase(text, debug=False):
    """
    🆕 v16.19: Определяет дублированные фразы
    
    Примеры дублей:
    - "ничего не знали. ничего не знали."
    - "логичным Логичным решением"
    - "начинает наступать начинает наступать"
    
    Args:
        text: Текст для проверки
        debug: Показывать debug output
    
    Returns:
        (has_duplicate, cleaned_text)
    """
    # Разбиваем на предложения
    sentences = re.split(r'([.!?]+)\s*', text)
    sentences = [s.strip() for s in sentences if s.strip() and s not in '.!?']
    
    if len(sentences) < 2:
        return False, text
    
    # Ищем смежные дубли
    cleaned_sentences = []
    skip_next = False
    duplicates_found = 0
    
    for i in range(len(sentences)):
        if skip_next:
            skip_next = False
            continue
        
        current = sentences[i]
        
        # Проверяем следующее предложение
        if i < len(sentences) - 1:
            next_sent = sentences[i + 1]
            
            # Similarity (игнорируя регистр)
            similarity = SequenceMatcher(
                None, 
                current.lower().strip(), 
                next_sent.lower().strip()
            ).ratio()
            
            if similarity > 0.95:  # 95% similarity = дубль!
                if debug:
                    print(f"  🔍 ДУБЛЬ (similarity={similarity:.2%}): \"{current}\" ≈ \"{next_sent}\"")
                
                # Берём более длинный вариант
                if len(next_sent) > len(current):
                    cleaned_sentences.append(next_sent)
                else:
                    cleaned_sentences.append(current)
                
                skip_next = True
                duplicates_found += 1
                continue
        
        cleaned_sentences.append(current)
    
    if duplicates_found > 0:
        cleaned_text = '. '.join(cleaned_sentences) + '.'
        return True, cleaned_text
    
    return False, text


def remove_ending_hallucinations(text, debug=False):
    """
    🆕 v16.19: Удаляет типичные Whisper hallucination в конце текста
    
    Whisper часто добавляет в конце файла:
    - "Продолжение следует"
    - "Спасибо за внимание"
    - "До новых встреч"
    - "Подписывайтесь на наш канал"
    
    Args:
        text: Текст сегмента
        debug: Показывать debug output
    
    Returns:
        Очищенный текст
    """
    hallucination_patterns = [
        r'продолжение\s+следует[.!?]*\s*$',
        r'спасибо\s+за\s+внимание[.!?]*\s*$',
        r'до\s+новых\s+встреч[.!?]*\s*$',
        r'подписывайтесь\s+на\s+наш\s+канал[.!?]*\s*$',
        r'ставьте\s+лайки[.!?]*\s*$',
    ]
    
    text_lower = text.lower()
    
    for pattern in hallucination_patterns:
        if re.search(pattern, text_lower):
            cleaned = re.sub(pattern, '', text, flags=re.IGNORECASE).strip()
            
            if debug:
                removed = text[len(cleaned):].strip()
                print(f"  🗑️ HALLUCINATION: удалена фраза \"{removed}\"")
            
            return cleaned
    
    return text


def clean_hallucinations_from_text(text, speaker=None, is_gap_filled=False, debug=False):
    """
    🔧 v16.28: Комплексная очистка текста от галлюцинаций
    
    Выполняет:
    1. 🔧 Замена hallucination loops на "..." (НЕ удаление!)
    2. Удаление дублированных фраз
    3. Удаление ending hallucinations
    4. Очистка multiple пробелов и пунктуации
    
    Args:
        text: Текст для очистки
        speaker: Спикер (для контекста)
        is_gap_filled: Это gap-filled сегмент (строже)
        debug: Показывать debug output
    
    Returns:
        Очищенный текст
    """
    if not text or not text.strip():
        return text
    
    original_text = text
    
    # 1. 🔧 v16.28: Замена hallucination loops на "..."
    text = clean_loops(text, is_gap_filled=is_gap_filled, debug=debug)
    
    # 2. Удаление дублей
    has_dupl, text = is_duplicate_phrase(text, debug=debug)
    
    # 3. Удаление ending hallucinations
    text = remove_ending_hallucinations(text, debug=debug)
    
    # 4. Очистка пробелов и пунктуации
    text = re.sub(r'\s+', ' ', text)  # Multiple spaces → one
    text = re.sub(r'([.!?]){2,}', r'\1', text)  # Multiple punctuation → one
    text = text.strip()
    
    if debug and text != original_text:
        print(f"  ✅ Очищено: {len(original_text)} → {len(text)} символов")
    
    return text


def filter_hallucination_segments(segments, debug=True):
    """
    🔧 v16.28: Фильтрует сегменты от галлюцинаций
    
    Применяет clean_hallucinations_from_text() к каждому сегменту.
    Удаляет сегменты, ставшие пустыми после очистки.
    Передаёт is_gap_filled флаг для gap-filled сегментов.
    
    Args:
        segments: Список сегментов
        debug: Показывать debug output
    
    Returns:
        Отфильтрованный список сегментов
    """
    if debug:
        print(f"\n🧹 Очистка hallucinations из {len(segments)} сегментов...")
    
    cleaned_segments = []
    removed_count = 0
    
    for seg in segments:
        text = seg.get('text', '')
        speaker = seg.get('speaker', '')
        is_gap_filled = seg.get('source') == 'GAP_FILLED'
        
        cleaned_text = clean_hallucinations_from_text(
            text, speaker, is_gap_filled=is_gap_filled, debug=debug
        )
        
        if cleaned_text:
            seg['text'] = cleaned_text
            cleaned_segments.append(seg)
        else:
            removed_count += 1
            if debug:
                print(f"  🗑️ Удалён пустой сегмент: {seg.get('time', '???')} ({speaker})")
    
    if debug:
        print(f"✅ Очистка завершена: {len(cleaned_segments)} сегментов (удалено {removed_count})")
    
    return cleaned_segments
