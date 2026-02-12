#!/usr/bin/env python3
"""
tests/test_timestamp_fixer.py - Unit tests для timestamp_fixer v16.22

🆕 v16.22: Тесты для БАГ #1 - дублирующиеся timestamp
🆕 v16.22: Тесты для БАГ #2 - timestamp идёт назад
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'scripts'))

import unittest
from corrections.timestamp_fixer import insert_intermediate_timestamps, correct_timestamp_drift
from core.utils import seconds_to_hms


class TestInsertIntermediateTimestamps(unittest.TestCase):
    """Тесты для insert_intermediate_timestamps()"""
    
    def test_no_duplicate_timestamps_at_sentence_start(self):
        """
        🐛 БАГ #1: Дублирующиеся timestamp
        
        Сценарий:
        - Блок >30 сек
        - Предложение начинается с timestamp (например, вставленного ранее)
        - insert_intermediate_timestamps() НЕ должен вставлять дубль!
        
        ОЖИДАЕТСЯ:
        00:00:55 Текст...  (НЕТ дубля!)
        
        РЕАЛЬНОСТЬ (баг):
        00:00:55 00:00:55 Текст...
        """
        segments = [
            {
                'start': 0.0,
                'end': 65.0,  # 65 сек → нужна вставка timestamp
                'time': '00:00:00',
                'speaker': 'Исаев',
                'text': 'Первое предложение длинное. 00:00:55 Второе предложение уже имеет timestamp в начале. Третье предложение.'
            }
        ]
        
        result = insert_intermediate_timestamps(segments, interval=30.0, debug=False)
        
        # Проверяем, что НЕТ дублей timestamp
        text = result[0]['text']
        
        # Считаем количество вхождений "00:00:55"
        count_timestamp = text.count('00:00:55')
        
        self.assertEqual(
            count_timestamp, 
            1,  # Только ОДИН timestamp!
            f"Найден дубль timestamp! Текст: {text}"
        )
        
        # Проверяем, что НЕТ двух timestamp подряд
        self.assertNotIn(
            '00:00:55 00:00:55',
            text,
            f"Найден дубль timestamp подряд! Текст: {text}"
        )
    
    def test_insert_timestamp_in_long_block(self):
        """
        ✅ Позитивный тест: вставка timestamp в блок >30 сек
        
        Блок 65 сек без timestamp внутри → вставить ~00:00:30
        """
        segments = [
            {
                'start': 0.0,
                'end': 65.0,
                'time': '00:00:00',
                'speaker': 'Исаев',
                'text': 'Первое предложение очень длинное и занимает много времени. Второе предложение тоже длинное. Третье предложение.'
            }
        ]
        
        result = insert_intermediate_timestamps(segments, interval=30.0, debug=False)
        
        text = result[0]['text']
        
        # Проверяем, что timestamp вставлен
        self.assertIn(
            '00:00:',  # Должен быть хотя бы один timestamp внутри
            text
        )
    
    def test_no_insert_in_short_block(self):
        """
        ✅ Позитивный тест: НЕТ вставки в блоки <=30 сек
        """
        segments = [
            {
                'start': 0.0,
                'end': 25.0,  # 25 сек → слишком коротко
                'time': '00:00:00',
                'speaker': 'Исаев',
                'text': 'Короткий текст без промежуточных timestamp.'
            }
        ]
        
        original_text = segments[0]['text']
        result = insert_intermediate_timestamps(segments, interval=30.0, debug=False)
        
        # Текст НЕ должен измениться
        self.assertEqual(
            result[0]['text'],
            original_text,
            "Короткий блок (<30s) не должен получить промежуточные timestamp!"
        )


class TestCorrectTimestampDrift(unittest.TestCase):
    """Тесты для correct_timestamp_drift()"""
    
    def test_no_backward_timestamp_movement(self):
        """
        🐛 БАГ #2: Timestamp идёт назад
        
        Сценарий:
        - Gap filling вставил сегмент с overlap
        - prev_seg.end = 183.5 (00:03:03)
        - current_seg.start = 186.2 (00:03:06)
        - correct_timestamp_drift() сдвигает current_seg.start = prev_seg.end
        - Результат: 00:03:06 → 00:03:03 (НАЗАД!)
        
        ОЖИДАЕТСЯ:
        Timestamp НЕ должен двигаться назад! Остаётся 00:03:06
        """
        segments = [
            {
                'start': 180.0,  # 00:03:00
                'end': 183.5,    # 00:03:03
                'time': '00:03:00',
                'speaker': 'Исаев',
                'text': 'Первый сегмент'
            },
            {
                'start': 186.2,  # 00:03:06 (gap = 2.7s)
                'end': 190.0,
                'time': '00:03:06',
                'speaker': 'Исаев',
                'text': 'Второй сегмент'
            }
        ]
        
        # Сохраняем оригинальный start
        original_start = segments[1]['start']
        
        result = correct_timestamp_drift(segments, debug=False)
        
        # Проверяем, что timestamp НЕ сдвинулся назад
        new_start = result[1]['start']
        
        self.assertGreaterEqual(
            new_start,
            original_start,
            f"Timestamp сдвинулся НАЗАД! {original_start} → {new_start}"
        )
    
    def test_correct_overlap_adjustment(self):
        """
        ✅ Позитивный тест: корректировка overlap (сдвиг ВПЕРЁД допустим)
        
        Сценарий:
        - prev_seg.end = 186.0 (00:03:06)
        - current_seg.start = 185.5 (00:03:05) ← overlap -0.5s
        - Корректируем: current_seg.start = 186.0 (сдвиг ВПЕРЁД +0.5s)
        """
        segments = [
            {
                'start': 180.0,
                'end': 186.0,  # 00:03:06
                'time': '00:03:00',
                'speaker': 'Исаев',
                'text': 'Первый сегмент'
            },
            {
                'start': 185.5,  # 00:03:05 (overlap -0.5s)
                'end': 190.0,
                'time': '00:03:05',
                'speaker': 'Журналист',
                'text': 'Второй сегмент с overlap'
            }
        ]
        
        result = correct_timestamp_drift(segments, debug=False)
        
        # Проверяем, что overlap исправлен (current_seg.start >= prev_seg.end)
        self.assertGreaterEqual(
            result[1]['start'],
            result[0]['end'],
            "Overlap не исправлен!"
        )
    
    def test_no_correction_for_large_gap(self):
        """
        ✅ Позитивный тест: НЕТ корректировки для больших пауз
        
        Сценарий:
        - Gap = 5 сек (больше 0.5s threshold)
        - Timestamp НЕ должен корректироваться
        """
        segments = [
            {
                'start': 180.0,
                'end': 185.0,
                'time': '00:03:00',
                'speaker': 'Исаев',
                'text': 'Первый сегмент'
            },
            {
                'start': 190.0,  # Gap = 5s
                'end': 195.0,
                'time': '00:03:10',
                'speaker': 'Исаев',
                'text': 'Второй сегмент после паузы'
            }
        ]
        
        original_start = segments[1]['start']
        result = correct_timestamp_drift(segments, debug=False)
        
        # Timestamp НЕ должен измениться
        self.assertEqual(
            result[1]['start'],
            original_start,
            "Большой gap (>0.5s) не должен корректироваться!"
        )


if __name__ == '__main__':
    unittest.main()
