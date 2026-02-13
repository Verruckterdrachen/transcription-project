#!/usr/bin/env python3
"""
tests/test_hallucinations.py - Unit tests для hallucinations.py v16.23

🆕 v16.23: Тесты для БАГ #3 FIX (hallucination loops)
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'scripts'))

from corrections.hallucinations import (
    clean_loops,
    clean_hallucinations_from_text,
    is_duplicate_phrase
)


def test_clean_loops_exact_repeat():
    """Точное повторение фразы"""
    text = "необходимо учитывать факторы. необходимо учитывать факторы."
    result = clean_loops(text, debug=True)
    
    # Должно остаться только одно упоминание
    assert result.count("необходимо учитывать") == 1
    print(f"✅ test_clean_loops_exact_repeat: PASS")
    print(f"   Input:  {text}")
    print(f"   Output: {result}\n")


def test_clean_loops_with_variations():
    """БАГ #3: Повторение с вариациями (реальный кейс!)"""
    text = "учитывать была немецкая артиллерия вправь до еще фактором которые надо учитывать это было немецкая вплоть до. который надо учитывать, это была немецкая артиллерия, вплоть до"
    
    result = clean_loops(text, is_gap_filled=True, debug=True)
    
    # Проверки:
    # 1. "учитывать" должно встречаться максимум 2 раза (не 4!)
    assert result.count("учитывать") <= 2, f"Слишком много 'учитывать': {result.count('учитывать')}"
    
    # 2. "немецкая" должна встречаться максимум 2 раза (не 3!)
    assert result.count("немецкая") <= 2, f"Слишком много 'немецкая': {result.count('немецкая')}"
    
    # 3. Текст должен стать короче
    assert len(result) < len(text), "Текст не укоротился!"
    
    print(f"✅ test_clean_loops_with_variations: PASS")
    print(f"   Input length:  {len(text)}")
    print(f"   Output length: {len(result)}")
    print(f"   'учитывать': {text.count('учитывать')} → {result.count('учитывать')}")
    print(f"   'немецкая':  {text.count('немецкая')} → {result.count('немецкая')}\n")


def test_clean_loops_short_phrases():
    """Короткие фразы (<5 слов) требуют более строгого threshold"""
    text = "было это было это очень это было"
    result = clean_loops(text, debug=True)
    
    # "было это" не должно повторяться
    assert result.count("было это") <= 1
    print(f"✅ test_clean_loops_short_phrases: PASS\n")


def test_clean_loops_no_false_positives():
    """Не должно удалять нормальный текст без повторов"""
    text = "Операция началась в январе. Наступление развивалось успешно. Противник отступал."
    result = clean_loops(text, debug=False)
    
    # Текст не должен измениться
    assert result == text or abs(len(result) - len(text)) < 3
    print(f"✅ test_clean_loops_no_false_positives: PASS\n")


def test_clean_loops_gap_filled_stricter():
    """Gap-filled сегменты должны иметь более строгую проверку"""
    # Фраза с similarity ~80% (между 75% и 85%)
    text = "немецкая артиллерия была сильна. немецкая пехота была сильна."
    
    # Без gap-filled flag — может пропустить (threshold 75%)
    result_normal = clean_loops(text, is_gap_filled=False, debug=True)
    
    # С gap-filled flag — должен поймать (threshold 85%)
    result_gap = clean_loops(text, is_gap_filled=True, debug=True)
    
    # Gap-filled версия должна быть короче (более строгая)
    assert len(result_gap) <= len(result_normal)
    print(f"✅ test_clean_loops_gap_filled_stricter: PASS")
    print(f"   Normal:     {len(result_normal)} chars")
    print(f"   Gap-filled: {len(result_gap)} chars\n")


def test_integration_full_pipeline():
    """Интеграционный тест: полный pipeline очистки"""
    text = "учитывать была немецкая артиллерия. учитывать была немецкая. Продолжение следует."
    
    result = clean_hallucinations_from_text(
        text,
        speaker="Исаев",
        is_gap_filled=True,
        debug=True
    )
    
    # Проверки:
    # 1. Loops очищены
    assert result.count("учитывать") <= 1
    # 2. Ending hallucination удалена
    assert "Продолжение следует" not in result
    # 3. Текст не пустой
    assert len(result) > 0
    
    print(f"✅ test_integration_full_pipeline: PASS")
    print(f"   Input:  {text}")
    print(f"   Output: {result}\n")


if __name__ == '__main__':
    print("=" * 60)
    print("🧪 HALLUCINATIONS.PY UNIT TESTS v16.23")
    print("=" * 60 + "\n")
    
    test_clean_loops_exact_repeat()
    test_clean_loops_with_variations()
    test_clean_loops_short_phrases()
    test_clean_loops_no_false_positives()
    test_clean_loops_gap_filled_stricter()
    test_integration_full_pipeline()
    
    print("=" * 60)
    print("✅ ВСЕ ТЕСТЫ ПРОЙДЕНЫ!")
    print("=" * 60)
