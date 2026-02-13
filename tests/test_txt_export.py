#!/usr/bin/env python3
"""
tests/test_txt_export.py - Unit tests для БАГ #1 + БАГ #2

🔧 v16.23.2: Исправлены условия тестов - checkpoint через 30s
🔧 v16.23.1: Исправлены тесты - длинные предложения для inner timestamps
🆕 v16.23: Тестируем insert_inner_timestamps() - нет дублей, нет "назад"
"""

import pytest
from scripts.export.txt_export import insert_inner_timestamps


def test_no_duplicate_timestamps():
    """
    🐛 БАГ #1: Дубли timestamp
    
    Проверяем, что inner timestamp НЕ создаёт дубль если следующий сегмент
    начинается с того же времени.
    """
    # 🔧 v16.23.2: 5 предложений, duration 70s → checkpoint через ~30s
    long_sentence = (
        "Это очень длинное предложение для тестирования inner timestamps, "
        "которое занимает достаточно много символов и времени для корректной работы, "
        "а также содержит дополнительные слова чтобы растянуть его ещё больше. "
    )
    text = (long_sentence + ". ") * 5  # 5 предложений с точками
    
    start_sec = 100.0
    end_sec = 170.0  # 70 секунд (каждое предложение ~14s)
    next_segment_exists = True
    
    result = insert_inner_timestamps(text, start_sec, end_sec, next_segment_exists)
    
    # Inner timestamp должен быть на отдельной строке (начинается с \n)
    assert "\n" in result, f"Inner timestamp должен содержать перенос строки \\n. Результат: {result[:300]}"
    
    # Проверяем, что НЕТ двух timestamp подряд без \n между ними
    lines = result.split('\n')
    
    for line in lines:
        # Подсчитываем timestamp в одной строке
        timestamps = [word for word in line.split() if word.count(':') == 2 and len(word) == 8]
        # В одной строке может быть МАКСИМУМ 1 timestamp
        assert len(timestamps) <= 1, f"БАГ #1: Найдено {len(timestamps)} timestamp в одной строке: {line[:100]}"


def test_timestamps_monotonic():
    """
    🐛 БАГ #2: Timestamp идёт назад
    
    Проверяем, что все timestamp идут строго ВПЕРЁД (монотонность).
    """
    long_sentence = (
        "Это очень длинное предложение для тестирования inner timestamps, "
        "которое занимает достаточно много символов и времени для корректной работы, "
        "а также содержит дополнительные слова чтобы растянуть его ещё больше. "
    )
    text = (long_sentence + ". ") * 5
    
    start_sec = 100.0
    end_sec = 170.0
    next_segment_exists = True
    
    result = insert_inner_timestamps(text, start_sec, end_sec, next_segment_exists)
    
    # Извлекаем все timestamp из результата
    import re
    timestamps = re.findall(r'(\d{2}:\d{2}:\d{2})', result)
    
    if len(timestamps) < 2:
        # Если нет inner timestamps, тест пропускаем (но это не норма для 70s реплики)
        pytest.skip("Нет inner timestamps для проверки монотонности")
    
    # Конвертируем в секунды
    def hms_to_seconds(hms_str):
        h, m, s = map(int, hms_str.split(':'))
        return h * 3600 + m * 60 + s
    
    timestamps_sec = [hms_to_seconds(ts) for ts in timestamps]
    
    # Проверяем монотонность
    for i in range(1, len(timestamps_sec)):
        prev_ts = timestamps_sec[i-1]
        curr_ts = timestamps_sec[i]
        assert curr_ts >= prev_ts, f"БАГ #2: Timestamp идёт назад: {timestamps[i-1]} → {timestamps[i]}"


def test_inner_timestamp_on_new_line():
    """
    🔧 v16.23: Inner timestamp должен быть на новой строке
    
    Проверяем, что inner timestamp всегда начинается с \n
    """
    long_sentence = (
        "Это очень длинное предложение для тестирования inner timestamps, "
        "которое занимает достаточно много символов и времени для корректной работы, "
        "а также содержит дополнительные слова чтобы растянуть его ещё больше. "
    )
    text = (long_sentence + ". ") * 5
    
    start_sec = 100.0
    end_sec = 170.0
    next_segment_exists = True
    
    result = insert_inner_timestamps(text, start_sec, end_sec, next_segment_exists)
    
    # Находим все inner timestamps (те, что с \n перед ними)
    import re
    inner_timestamps = re.findall(r'\n(\d{2}:\d{2}:\d{2})', result)
    
    # Должен быть хотя бы один inner timestamp (реплика >30s)
    assert len(inner_timestamps) > 0, f"Не найдено ни одного inner timestamp для длинной реплики (70s)! Результат: {result[:300]}"


def test_short_text_no_inner_timestamps():
    """
    Проверяем, что короткие реплики (<30s) НЕ получают inner timestamps
    """
    text = "Короткий текст."
    start_sec = 100.0
    end_sec = 105.0  # 5 секунд
    next_segment_exists = True
    
    result = insert_inner_timestamps(text, start_sec, end_sec, next_segment_exists)
    
    # Результат должен быть идентичен исходному тексту
    assert result == text, "Короткий текст не должен содержать inner timestamps"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
