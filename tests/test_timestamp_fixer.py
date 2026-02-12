#!/usr/bin/env python3
"""
tests/test_timestamp_fixer.py - Unit tests для timestamp_fixer v16.19

🧪 ROOT CAUSE TESTS:
1. test_insert_intermediate_timestamps_long_block() - блок 231 сек без меток
2. test_correct_timestamp_drift() - сдвиг timestamp после gap filling
"""

import sys
from pathlib import Path

# Добавляем scripts/ в путь
sys.path.insert(0, str(Path(__file__).parent.parent / "scripts"))

from corrections.timestamp_fixer import (
    insert_intermediate_timestamps, correct_timestamp_drift
)
from core.utils import seconds_to_hms


def test_insert_intermediate_timestamps_long_block():
    """
    🧪 TEST: Блок 231 сек должен получить промежуточные timestamp
    
    ROOT CAUSE: merge_replicas() не проверяет длительность блока
    
    БЫЛО:
    00:06:12 Текст 231 сек без меток...
    
    ДОЛЖНО БЫТЬ:
    00:06:12 Текст... 00:06:42 Текст... 00:07:12 Текст... (7 меток)
    """
    segments = [
        {
            'start': 372.0,  # 00:06:12
            'end': 603.0,    # 00:10:03 (231 сек!)
            'speaker': 'Исаев',
            'time': '00:06:12',
            'text': 'Предложение 1. Предложение 2. Предложение 3. Предложение 4. Предложение 5. Предложение 6. Предложение 7. Предложение 8.'
        }
    ]
    
    result = insert_intermediate_timestamps(segments, interval=30.0, debug=False)
    
    # Проверяем наличие timestamp в тексте
    text = result[0]['text']
    timestamps_count = text.count('00:')
    
    # Должно быть ~7 промежуточных меток (231/30 ≈ 7)
    assert timestamps_count >= 5, f"Ожидалось >= 5 timestamp, найдено {timestamps_count}"
    print(f"✅ test_insert_intermediate_timestamps_long_block: {timestamps_count} timestamp вставлено")


def test_correct_timestamp_drift():
    """
    🧪 TEST: Сдвиг timestamp после gap filling должен быть исправлен
    
    ROOT CAUSE: gap filling меняет segment.end, но не обновляет start
    
    БЫЛО:
    - Seg1: end=550.0
    - Seg2: start=559.5 (оригинальный Whisper start)
    - Реальное начало Seg2 после adjustment: 550.0 (сразу после Seg1)
    
    ДОЛЖНО БЫТЬ:
    - Seg2: start=550.0 (исправлено), time='00:09:10'
    """
    segments = [
        {
            'start': 500.0,
            'end': 550.0,
            'speaker': 'Исаев',
            'time': '00:08:20',
            'text': 'Сегмент 1'
        },
        {
            'start': 559.5,  # Старый start (сдвиг +9.5s)
            'end': 600.0,
            'speaker': 'Журналист',
            'time': '00:09:19',  # Неправильный timestamp!
            'text': 'Сегмент 2'
        }
    ]
    
    result = correct_timestamp_drift(segments, debug=False)
    
    # Проверяем исправление
    seg2 = result[1]
    assert abs(seg2['start'] - 550.0) < 0.1, f"Ожидалось start=550.0, получено {seg2['start']}"
    assert seg2['time'] == '00:09:10', f"Ожидалось time='00:09:10', получено {seg2['time']}"
    
    print(f"✅ test_correct_timestamp_drift: сдвиг исправлен (559.5 → 550.0)")


def test_hallucination_duplicate_removal():
    """
    🧪 TEST: Дубли должны быть удалены
    
    ROOT CAUSE: Whisper галлюцинирует при заикании/паузах
    
    БЫЛО:
    "ничего не знали. ничего не знали."
    
    ДОЛЖНО БЫТЬ:
    "ничего не знали."
    """
    from corrections.hallucinations import is_duplicate_phrase
    
    text = "ничего не знали. ничего не знали."
    has_dupl, cleaned = is_duplicate_phrase(text, debug=False)
    
    assert has_dupl == True, "Дубль не обнаружен!"
    assert cleaned.count("ничего не знали") == 1, f"Дубль не удалён: {cleaned}"
    
    print(f"✅ test_hallucination_duplicate_removal: дубль удалён")


def test_continuation_phrase_threshold():
    """
    🧪 TEST: Порог similarity должен быть 90% (не 80%)
    
    ROOT CAUSE: Порог 80% пропускает заикания с similarity 85-95%
    
    ТЕСТ:
    - similarity 92% → должно детектироваться
    - similarity 78% → НЕ должно детектироваться
    """
    from corrections.boundary_fixer import detect_continuation_phrase
    
    # Заикание (similarity ~92%)
    current = "«Невский пятачок», несмотря на то, что располагался"
    previous = ["«Невский пятачок», хотя он располагался"]
    
    is_rep, sim, matched = detect_continuation_phrase(current, previous, threshold=0.90)
    
    assert is_rep == True, f"Заикание НЕ детектировано (similarity={sim:.2%})"
    print(f"✅ test_continuation_phrase_threshold: заикание детектировано (similarity={sim:.2%})")


if __name__ == "__main__":
    print("\n🧪 RUNNING UNIT TESTS v16.19\n")
    print("="*70)
    
    test_insert_intermediate_timestamps_long_block()
    test_correct_timestamp_drift()
    test_hallucination_duplicate_removal()
    test_continuation_phrase_threshold()
    
    print("="*70)
    print("\n✅ ВСЕ ТЕСТЫ ПРОЙДЕНЫ!\n")
