#!/usr/bin/env python3
"""
corrections/hallucinations.py - Удаление галлюцинаций Whisper v16.23

🆕 v16.23: FIX БАГ #3 - Hallucination loops в gap-filled сегментах
- Новая функция clean_loops() для детекции repeating patterns
- Adaptive threshold: короткие фразы (<5 слов) → 85%, длинные → 75%
- Особая обработка gap-filled сегментов (threshold +10%)

🆕 v16.19: КРИТИЧЕСКИЙ FIX - Удаление дублей + "Продолжение следует"
- Детекция дублированных фраз (similarity >95%)
- Удаление Whisper hallucination в конце файла ("Продолжение следует", "Спасибо за внимание")
- Удаление дублей с разным регистром ("логичным Логичным")
- Сохранена старая функция is_hallucination() для обратной совместимости
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

def clean_loops(text, is_gap_filled=False, debug=False):
    """
    🆕 v16.23: Удаляет repeating loop patterns внутри текста
    
    Детектит и удаляет повторяющиеся фразы с вариациями:
    - "учитывать была немецкая... который надо учитывать... это была немецкая"
    - "вплоть до... вправь до... вплоть до"
    
    Использует n-gram анализ для поиска похожих фраз.
    
    Adaptive threshold:
    - Короткие фразы (<5 слов): similarity ≥85%
    - Длинные фразы (≥5 слов): similarity ≥75%
    - Gap-filled сегменты: +10% к threshold
    
    ВАЖНО: n-граммы должны быть разделены минимальным расстоянием,
    чтобы избежать false positives от overlapping windows.
    
    Args:
        text: Текст для очистки
        is_gap_filled: True если сегмент был добавлен через gap filling
        debug: Показывать debug output
    
    Returns:
        Очищенный текст
    """
    if not text or len(text.strip()) < 20:
        return text
    
    # Разбиваем текст на слова (игнорируем пунктуацию для анализа)
    words = re.findall(r'\b\w+\b', text.lower())
    
    if len(words) < 4:  # ← ИЗМЕНЕНО: было 6, стало 4 (минимум 2+2 для детекции)
        return text  # Слишком короткий
    
    # Параметры
    min_ngram_size = 2  # ← ИЗМЕНЕНО: было 3, стало 2 (детектим фразы из 2 слов!)
    max_ngram_size = 8  # Максимум 8 слов
    
    removed_positions = set()  # Позиции слов для удаления
    loop_found = False
    
    # Пробуем разные размеры n-gram (от большего к меньшему)
    for ngram_size in range(max_ngram_size, min_ngram_size - 1, -1):
        
        # Adaptive threshold
        if ngram_size < 5:
            base_threshold = 0.85  # Короткие фразы — строже!
        else:
            base_threshold = 0.75
        
        # Gap-filled сегменты требуют ещё больше внимания
        threshold = base_threshold + (0.10 if is_gap_filled else 0.0)
        
        # Минимальное расстояние между n-граммами (чтобы избежать overlapping)
        min_distance = max(ngram_size // 2, 2)  # Минимум половина размера n-граммы или 2 слова
        
        # Создаём все n-граммы заданного размера
        ngrams = []
        for i in range(len(words) - ngram_size + 1):
            # Пропускаем n-граммы с удалёнными словами
            if any(idx in removed_positions for idx in range(i, i + ngram_size)):
                continue
            
            ngram = ' '.join(words[i:i + ngram_size])
            ngrams.append((i, ngram))
        
        # Ищем похожие n-граммы
        matched_pairs = []
        
        for i, (pos1, ngram1) in enumerate(ngrams):
            for pos2, ngram2 in ngrams[i + 1:]:
                
                # КРИТИЧЕСКАЯ ПРОВЕРКА: n-граммы должны быть достаточно далеко друг от друга!
                distance = pos2 - pos1
                if distance < min_distance:
                    continue  # Слишком близко — это overlapping, не loop!
                
                # Проверяем similarity
                similarity = SequenceMatcher(None, ngram1, ngram2).ratio()
                
                if similarity >= threshold:
                    matched_pairs.append((pos1, pos2, ngram1, ngram2, similarity))
        
        # Обрабатываем найденные пары
        for pos1, pos2, ngram1, ngram2, similarity in matched_pairs:
            # LOOP DETECTED!
            if debug:
                print(f"  🔄 LOOP (len={ngram_size}, sim={similarity:.0%}, distance={pos2-pos1}):")
                print(f"     [{pos1}] \"{ngram1}\"")
                print(f"     [{pos2}] \"{ngram2}\"")
            
            # Удаляем вторую копию (сохраняем первую)
            for idx in range(pos2, pos2 + ngram_size):
                removed_positions.add(idx)
            
            loop_found = True
    
    if not loop_found:
        return text
    
    # Восстанавливаем текст без удалённых слов
    words_original = re.findall(r'\b\w+\b', text)
    
    # Создаём маппинг: позиция слова → оригинальное слово
    kept_words = [words_original[i] for i in range(len(words_original)) if i not in removed_positions]
    
    if not kept_words:
        return text  # Если всё удалено — возвращаем оригинал
    
    # Собираем текст из оставшихся слов
    result_parts = []
    word_idx = 0
    
    for match in re.finditer(r'\b\w+\b|[^\w\s]', text):
        token = match.group()
        
        if re.match(r'\w+', token):  # Это слово
            if word_idx not in removed_positions:
                result_parts.append(token)
            word_idx += 1
        else:  # Это пунктуация
            # Добавляем только если предыдущее слово не удалено
            if result_parts:
                result_parts.append(token)
    
    cleaned_text = ' '.join(result_parts)
    
    # Очистка множественных пробелов и пунктуации
    cleaned_text = re.sub(r'\s+', ' ', cleaned_text)
    cleaned_text = re.sub(r'\s+([.,;:!?])', r'\1', cleaned_text)
    cleaned_text = re.sub(r'([.,;:!?])\s*\1+', r'\1', cleaned_text)  # "... ..." → "..."
    
    if debug:
        print(f"  ✅ LOOP удалён: {len(text)} → {len(cleaned_text)} символов")
        print(f"     БЫЛО: {text[:80]}...")
        print(f"     СТАЛО: {cleaned_text[:80]}...")
    
    return cleaned_text.strip()

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
    🆕 v16.23: Комплексная очистка текста от галлюцинаций
    
    Выполняет:
    1. Удаление loop patterns (новое!)
    2. Удаление дублированных фраз
    3. Удаление ending hallucinations
    4. Очистка multiple пробелов и пунктуации
    
    Args:
        text: Текст для очистки
        speaker: Спикер (для контекста)
        is_gap_filled: True если сегмент был добавлен через gap filling
        debug: Показывать debug output
    
    Returns:
        Очищенный текст
    """
    if not text or not text.strip():
        return text
    
    original_text = text
    
    # 1. Удаление loop patterns (БАГ #3 FIX!)
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
    🆕 v16.23: Фильтрует сегменты от галлюцинаций (обновлено для gap-filled)
    
    Применяет clean_hallucinations_from_text() к каждому сегменту.
    Удаляет сегменты, ставшие пустыми после очистки.
    
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
        
        # Проверяем, является ли сегмент gap-filled
        is_gap_filled = seg.get('raw_speaker_id') == 'GAP_FILLED'
        
        cleaned_text = clean_hallucinations_from_text(
            text, 
            speaker, 
            is_gap_filled=is_gap_filled,
            debug=debug
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
