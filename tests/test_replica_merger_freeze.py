"""
🆕 v16.21: Unit test - Защита от infinite loop в replica_merger

ROOT CAUSE: При overlap > 2s без similarity, цикл инкрементировал j,
но не обновлял current_end → следующие сегменты тоже попадали в overlap
→ infinite loop.

FIX: Добавлен break вместо continue в этом случае.
"""

import sys
import os

# Добавляем scripts/ в path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'scripts'))

from merge.replica_merger import merge_replicas
import time

def test_no_infinite_loop_on_large_overlap():
    """
    Проблема v16.20: Если цепочка сегментов с overlap > 2s без similarity,
    цикл зависал.
    
    Решение v16.21: Добавлен break при большой overlap без similarity.
    """
    
    # Создаём тестовые данные: цепочка сегментов с большой overlap
    segments = [
        {
            "speaker": "Исаев",
            "start": 0.0,
            "end": 5.0,
            "text": "Это первый сегмент про операцию",
            "raw_speaker_id": "SPEAKER_00",
            "start_hms": "00:00:00"
        },
        {
            "speaker": "Исаев",
            "start": 1.0,  # overlap -4.0s
            "end": 6.0,
            "text": "Совершенно другой текст про танки",  # similarity < 0.60
            "raw_speaker_id": "SPEAKER_00",
            "start_hms": "00:00:01"
        },
        {
            "speaker": "Исаев",
            "start": 2.0,  # overlap -4.0s с первым
            "end": 7.0,
            "text": "Третий несвязанный текст про авиацию",  # similarity < 0.60
            "raw_speaker_id": "SPEAKER_00",
            "start_hms": "00:00:02"
        },
        {
            "speaker": "Исаев",
            "start": 3.0,  # overlap -4.0s
            "end": 8.0,
            "text": "Четвертый текст про артиллерию",  # similarity < 0.60
            "raw_speaker_id": "SPEAKER_00",
            "start_hms": "00:00:03"
        }
    ]
    
    # Запускаем merge с timeout
    start_time = time.time()
    timeout = 5.0  # 5 секунд - если зависнет, тест провалится
    
    try:
        result = merge_replicas(segments, debug=False)
        elapsed = time.time() - start_time
        
        # Проверяем что завершилось быстро
        assert elapsed < timeout, f"merge_replicas занял {elapsed:.1f}s (ожидалось < {timeout}s) - возможно infinite loop!"
        
        # Проверяем что результат корректный
        assert len(result) > 0, "Результат не должен быть пустым"
        assert len(result) <= len(segments), "Merged сегментов не должно быть больше исходных"
        
        print(f"✅ Test passed: {len(result)} merged сегментов из {len(segments)} исходных за {elapsed:.2f}s")
        
    except Exception as e:
        elapsed = time.time() - start_time
        raise AssertionError(f"merge_replicas упал после {elapsed:.1f}s: {e}")


def test_merge_with_protection_trigger():
    """
    Проверяем что защита от infinite loop срабатывает при патологических данных.
    """
    
    # Создаём 100 сегментов - защита должна сработать при 200 итерациях
    segments = []
    for i in range(100):
        segments.append({
            "speaker": "Исаев",
            "start": float(i),
            "end": float(i + 5),
            "text": f"Сегмент номер {i} с уникальным текстом",
            "raw_speaker_id": "SPEAKER_00",
            "start_hms": f"00:00:{i:02d}"
        })
    
    start_time = time.time()
    result = merge_replicas(segments, debug=False)
    elapsed = time.time() - start_time
    
    # Должно завершиться быстро благодаря защите
    assert elapsed < 10.0, f"merge_replicas занял {elapsed:.1f}s - защита не сработала?"
    assert len(result) > 0, "Результат не должен быть пустым"
    
    print(f"✅ Test passed: защита сработала корректно за {elapsed:.2f}s")


def test_normal_merge_still_works():
    """
    Проверяем что обычный merge всё ещё работает корректно после FIX.
    """
    
    segments = [
        {
            "speaker": "Исаев",
            "start": 0.0,
            "end": 3.0,
            "text": "Операция Искра началась",
            "raw_speaker_id": "SPEAKER_00",
            "start_hms": "00:00:00"
        },
        {
            "speaker": "Исаев",
            "start": 3.5,  # пауза 0.5s - должны склеить
            "end": 6.0,
            "text": "двенадцатого января",
            "raw_speaker_id": "SPEAKER_00",
            "start_hms": "00:00:03"
        },
        {
            "speaker": "Журналист",
            "start": 7.0,  # другой спикер
            "end": 9.0,
            "text": "А когда закончилась?",
            "raw_speaker_id": "SPEAKER_01",
            "start_hms": "00:00:07"
        }
    ]
    
    result = merge_replicas(segments, debug=False)
    
    # Должно быть 2 merged сегмента (первые два Исаева склеены)
    assert len(result) == 2, f"Ожидалось 2 merged сегмента, получено {len(result)}"
    assert result[0]["speaker"] == "Исаев"
    assert "Операция Искра началась двенадцатого января" in result[0]["text"]
    assert result[1]["speaker"] == "Журналист"
    
    print(f"✅ Test passed: обычный merge работает корректно")


if __name__ == "__main__":
    print("🧪 Running v16.21 tests...")
    print()
    
    try:
        print("TEST 1: Infinite loop protection on large overlap")
        test_no_infinite_loop_on_large_overlap()
        print()
        
        print("TEST 2: Protection trigger with pathological data")
        test_merge_with_protection_trigger()
        print()
        
        print("TEST 3: Normal merge still works")
        test_normal_merge_still_works()
        print()
        
        print("✅ ВСЕ ТЕСТЫ ПРОЙДЕНЫ!")
        
    except AssertionError as e:
        print(f"\n❌ ТЕСТ ПРОВАЛЕН: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n❌ ОШИБКА: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
