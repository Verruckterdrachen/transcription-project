#!/usr/bin/env python3
"""
corrections/hallucinations.py - Удаление галлюцинаций Whisper v16.19

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


def clean_hallucinations_from_text(text, speaker=None, debug=False):
    """
    🆕 v16.19: Комплексная очистка текста от галлюцинаций
    
    Выполняет:
    1. Удаление дублированных фраз
    2. Удаление ending hallucinations
    3. Очистка multiple пробелов и пунктуации
    
    Args:
        text: Текст для очистки
        speaker: Спикер (для контекста)
        debug: Показывать debug output
    
    Returns:
        Очищенный текст
    """
    if not text or not text.strip():
        return text
    
    original_text = text
    
    # 1. Удаление дублей
    has_dupl, text = is_duplicate_phrase(text, debug=debug)
    
    # 2. Удаление ending hallucinations
    text = remove_ending_hallucinations(text, debug=debug)
    
    # 3. Очистка пробелов и пунктуации
    text = re.sub(r'\s+', ' ', text)  # Multiple spaces → one
    text = re.sub(r'([.!?]){2,}', r'\1', text)  # Multiple punctuation → one
    text = text.strip()
    
    if debug and text != original_text:
        print(f"  ✅ Очищено: {len(original_text)} → {len(text)} символов")
    
    return text


def filter_hallucination_segments(segments, debug=True):
    """
    🆕 v16.19: Фильтрует сегменты от галлюцинаций
    
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
        
        cleaned_text = clean_hallucinations_from_text(text, speaker, debug=debug)
        
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

def mark_low_confidence_words(text: str, words: list, prob_threshold: float = 0.35, min_len: int = 4) -> str:
    """
    Заменяет низкоуверенные слова Whisper на [нрзб].

    Ожидается words вида: [{'word': '...', 'probability': 0.xx, ...}, ...]
    """
    if not text or not words:
        return text

    out = []
    prev_nrzb = False

    for w in words:
        wtxt = (w.get("word") or "").strip()
        prob = w.get("probability", None)

        # Нормализуем "длину слова" без пунктуации
        core = re.sub(r"[^\wа-яА-ЯёЁ]", "", wtxt)

        low_conf = (prob is not None and prob < prob_threshold and len(core) >= min_len)

        if low_conf:
            if not prev_nrzb:
                out.append("[нрзб]")
                prev_nrzb = True
            # если подряд несколько low_conf — схлопываем в один [нрзб]
        else:
            if wtxt:
                out.append(wtxt)
                prev_nrzb = False

    return " ".join(out).strip()
