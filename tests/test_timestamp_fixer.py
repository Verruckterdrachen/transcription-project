#!/usr/bin/env python3
"""
tests/test_timestamp_fixer.py - Unit tests для timestamp_fixer v16.22

🆕 v16.22: Тесты для БАГ #1 - дублирующиеся timestamp
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'scripts'))

import unittest
from corrections.timestamp_fixer import insert_intermediate_timestamps
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


if __name__ == '__main__':
    unittest.main()
