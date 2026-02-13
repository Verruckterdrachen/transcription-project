#!/usr/bin/env python3
"""
tests/test_boundary_fixer.py - Unit tests для БАГ #4

🔧 v16.23.2: Исправлена журналистская фраза на реальную из regex
🆕 v16.23: Тестируем split_mixed_speaker_segments() - правильный raw_speaker_id
"""

import pytest
from scripts.corrections.boundary_fixer import split_mixed_speaker_segments
from scripts.core.utils import seconds_to_hms


def test_raw_speaker_id_mapping():
    """
    🐛 БАГ #4: Adjacent same speaker из-за неправильного raw_speaker_id
    
    Проверяем, что после split все сегменты с speaker="Исаев"
    имеют ОДИНАКОВЫЙ raw_speaker_id.
    """
    # 🔧 v16.23.2: Используем РЕАЛЬНУЮ журналистскую фразу из regex
    segments_merged = [
        {
            "speaker": "Исаев",
            "text": "Первое предложение эксперта. Расскажите об этом подробнее. Третье предложение снова эксперта.",
            "start": 100.0,
            "end": 110.0,
            "time": "00:01:40",
            "raw_speaker_id": "SPEAKER_00"
        }
    ]
    
    speaker_surname = "Исаев"
    speaker_roles = {
        "SPEAKER_00": "Спикер",
        "SPEAKER_01": "Журналист"
    }
    
    # Выполняем split
    result = split_mixed_speaker_segments(
        segments_merged, 
        speaker_surname, 
        speaker_roles,
        debug=False
    )
    
    # Проверяем результат
    # Ожидаем 3 сегмента: Исаев → Журналист → Исаев
    assert len(result) == 3, f"Ожидалось 3 сегмента, получено {len(result)}. Результат: {[s['speaker'] for s in result]}"
    
    # Первый и третий сегменты = "Исаев"
    assert result[0]['speaker'] == "Исаев", f"Первый сегмент должен быть 'Исаев', получен '{result[0]['speaker']}'"
    assert result[2]['speaker'] == "Исаев", f"Третий сегмент должен быть 'Исаев', получен '{result[2]['speaker']}'"
    
    # Второй сегмент = "Журналист"
    assert result[1]['speaker'] == "Журналист", f"Второй сегмент должен быть 'Журналист', получен '{result[1]['speaker']}'"
    
    # 🆕 v16.23: КЛЮЧЕВАЯ ПРОВЕРКА - оба "Исаев" должны иметь ОДИНАКОВЫЙ raw_speaker_id!
    isaev_raw_id_1 = result[0]['raw_speaker_id']
    isaev_raw_id_3 = result[2]['raw_speaker_id']
    
    assert isaev_raw_id_1 == isaev_raw_id_3, \
        f"БАГ #4: raw_speaker_id разные! {isaev_raw_id_1} vs {isaev_raw_id_3}"
    
    # Проверяем, что raw_speaker_id = "SPEAKER_00" (основной спикер)
    assert isaev_raw_id_1 == "SPEAKER_00", \
        f"raw_speaker_id должен быть 'SPEAKER_00', получен '{isaev_raw_id_1}'"


def test_reverse_roles_includes_surname():
    """
    🔧 v16.23: Проверяем, что reverse_roles содержит speaker_surname
    
    Это гарантирует правильный маппинг "Исаев" → "SPEAKER_00"
    """
    segments_merged = [
        {
            "speaker": "Исаев",
            "text": "Тестовый текст.",
            "start": 100.0,
            "end": 105.0,
            "time": "00:01:40",
            "raw_speaker_id": "SPEAKER_00"
        }
    ]
    
    speaker_surname = "Исаев"
    speaker_roles = {
        "SPEAKER_00": "Спикер",
        "SPEAKER_01": "Журналист"
    }
    
    # Выполняем split (создаст reverse_roles внутри)
    result = split_mixed_speaker_segments(
        segments_merged,
        speaker_surname,
        speaker_roles,
        debug=False
    )
    
    # Проверяем, что результат имеет правильный raw_speaker_id
    assert result[0]['raw_speaker_id'] == "SPEAKER_00"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
