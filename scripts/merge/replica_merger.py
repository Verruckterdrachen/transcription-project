"""
merge/replica_merger.py - Склейка реплик одного спикера

🆕 v16.22: FIX БАГ #3 - Loop artifacts с вариациями слов
🆕 v16.21: CRITICAL FIX - Infinite Loop в overlap handling
🆕 v16.20: DEBUG OUTPUT для диагностики зависания
🆕 v16.14: КРИТИЧЕСКИЙ FIX - speaker от САМОГО ДЛИННОГО сегмента
"""

from difflib import SequenceMatcher
import re
from core.utils import seconds_to_hms
from corrections.hallucinations import clean_hallucinations_from_text

def clean_loops(text, debug=False):
    """
    🆕 v17.2: FIX БАГ #16 - Ограничение окна seen[] для loop detection
    🆕 v16.22: FIX БАГ #3 - Детекция вариаций с fuzzy matching
    🔧 v16.1: Удаляет зацикленные фразы (loop artifacts)
    🆕 v16.20: Добавлен debug параметр

    **ПРОБЛЕМА (БАГ #16):**
    seen[] накапливал ВСЕ фразы без ограничения по позиции.
    Фраза «прорыв блокады изнутри» в конце 228-словного блока
    сравнивалась с «точкой прорыва блокада изнутри» из начала —
    similarity=0.94 → ошибочное удаление легитимной фразы.

    **ROOT CAUSE:**
    Настоящий Whisper loop — это повтор через ~10-20 слов,
    НЕ через 60+ слов. Большое расстояние = новая мысль.

    **FIX v17.2:**
    seen[] хранит только последние LOOP_WINDOW=20 фраз (~60 слов).
    Фразы дальше этого окна не считаются повторами.

    Args:
        text: Текст для очистки
        debug: Показывать debug output

    Returns:
        Очищенный текст без loop artifacts
    """
    # Максимальное кол-во 3-словных фраз в окне сравнения (~60 слов)
    LOOP_WINDOW = 20

    if debug:
        print(f"    🧹 clean_loops: обработка текста ({len(text)} символов, {len(text.split())} слов)")

    words = text.split()
    seen = []  # Ограниченное окно последних фраз
    cleaned = []

    removed_count = 0
    i = 0

    while i < len(words):
        phrase = ' '.join(words[i:i+3])  # 3 слова
        phrase_lower = phrase.lower()

        # Fuzzy matching только в пределах окна
        is_loop = False

        for prev_phrase in seen:
            similarity = SequenceMatcher(None, phrase_lower, prev_phrase).ratio()

            if similarity >= 0.75:
                is_loop = True
                removed_count += 1

                if debug:
                    print(f"      🔁 LOOP (similarity={similarity:.2f}): '{phrase}' ≈ '{prev_phrase}'")

                break

        if is_loop:
            i += 1
            continue

        # 🆕 v17.2: Добавляем фразу в seen с ограничением окна
        seen.append(phrase_lower)
        if len(seen) > LOOP_WINDOW:
            seen.pop(0)  # Удаляем самую старую фразу

        cleaned.extend(words[i:i+3])
        i += 3

    final = ' '.join(cleaned)
    final = re.sub(r'([.,!?])\1{2,}', r'\1', final)

    if debug:
        if removed_count > 0:
            print(f"    ✅ clean_loops: готово ({len(final)} символов, удалено {removed_count} loop artifacts)")
        else:
            print(f"    ✅ clean_loops: готово ({len(final)} символов, loops не найдены)")

    return final.strip()

def merge_replicas(segments, debug=False):
    """
    🆕 v16.28.2: ДЕТАЛЬНЫЙ DEBUG для поиска потери текста
    🆕 v16.23: ОСЛАБЛЕНИЕ ЗАЩИТЫ v16.0 для БАГ #4
    🆕 v16.21: CRITICAL FIX - Infinite Loop в overlap handling
    ...
    """
    if not segments:
        return []

    def similarity(a, b):
        """Возвращает True если тексты похожи > 75%"""
        return SequenceMatcher(None, a.lower(), b.lower()).ratio() > 0.75

    merged = []
    i = 0
    merge_count = 0
    
    # 🆕 v16.28.2: Целевой диапазон для детального tracking
    TARGET_RANGE = (150, 280)  # 00:04:29 = 269 секунд

    while i < len(segments):
        merge_count += 1
        current = segments[i]
        current_speaker = current['speaker']
        
        # 🆕 v16.23: БАГ #4 FIX - берём raw_speaker_id для защиты
        current_raw_id = current.get('raw_speaker_id', '')
        
        texts = [current['text']]
        current_end = current['end']
        start_time = current['start']

        # Собираем ВСЕ сегменты группы
        all_segments_in_group = [current]
        
        # 🆕 v16.28.2: Проверка - попадает ли этот merge в целевой диапазон?
        in_target_range = (start_time <= TARGET_RANGE[1] and current_end >= TARGET_RANGE[0])

        if debug or in_target_range:
            print(f"\n  🔀 MERGE #{merge_count}: {current.get('start_hms', seconds_to_hms(start_time))} {current_speaker} — начало")
            if in_target_range:
                print(f"     🎯 TARGET RANGE DETECTED! (ищем 00:04:29)")
        else:
            print(f"  🔀 {current.get('start_hms', seconds_to_hms(start_time))} {current_speaker} — начало merge")
        
        # 🆕 v16.28.2: Показываем первый сегмент
        if in_target_range:
            print(f"     📝 Сегмент #0: [{seconds_to_hms(current['start'])}-{seconds_to_hms(current['end'])}]")
            print(f"        Текст: \"{current['text'][:80]}...\"")

        # Защита от infinite loop
        max_iterations = len(segments) * 2
        iteration_count = 0

        # Ищем соседние сегменты того же спикера
        j = i + 1
        merge_continue = True
        segment_index = 1  # 🆕 v16.28.2: Счётчик сегментов

        while j < len(segments) and merge_continue:
            iteration_count += 1
            if iteration_count > max_iterations:
                print(f"    ⚠️ ЗАЩИТА: превышено {max_iterations} итераций на merge #{merge_count}")
                break

            next_seg = segments[j]
            next_raw_id = next_seg.get('raw_speaker_id', '')
            pause = next_seg['start'] - current_end

            # 🆕 v16.23: ОСЛАБЛЕННАЯ ПРОВЕРКА СПИКЕРА для БАГ #4
            if next_seg['speaker'] != current_speaker:
                merge_continue = False
                break
            
            # 🆕 v16.23: Если speaker одинаковый, но raw_speaker_id разные
            if current_raw_id != next_raw_id and current_raw_id and next_raw_id:
                if current_speaker not in ("Журналист", "Оператор"):
                    print(f"    ↳ ⚠️ raw_speaker_id разные ({current_raw_id} vs {next_raw_id}), но speaker={current_speaker} → ✅ merge anyway")
                else:
                    print(f"    ↳ ❌ raw_speaker_id разные ({current_raw_id} vs {next_raw_id}) для {current_speaker} → STOP")
                    merge_continue = False
                    break

            # Обработка overlap (отрицательная пауза)
            if pause < 0:
                sim = SequenceMatcher(
                    None, 
                    texts[-1] if texts else "", 
                    next_seg['text']
                ).ratio()

                if sim > 0.85:
                    # Дубликат - берём более длинный
                    if len(next_seg['text']) > len(texts[-1]):
                        texts[-1] = next_seg['text']
                        all_segments_in_group[-1] = next_seg
                        
                        # 🆕 v16.28.2: Debug замены
                        if in_target_range:
                            print(f"     🔄 Сегмент #{segment_index-1} ЗАМЕНЁН (дубликат, более длинный)")
                            print(f"        Новый текст: \"{next_seg['text'][:80]}...\"")
                    
                    current_end = next_seg['end']
                    j += 1
                    continue

                if sim > 0.60:
                    # Похожие - добавляем
                    texts.append(next_seg['text'])
                    all_segments_in_group.append(next_seg)
                    
                    # 🆕 v16.28.2: Debug добавления
                    if in_target_range:
                        print(f"     ➕ Сегмент #{segment_index}: [{seconds_to_hms(next_seg['start'])}-{seconds_to_hms(next_seg['end'])}] (overlap, sim={sim:.2f})")
                        print(f"        Текст: \"{next_seg['text'][:80]}...\"")
                    
                    segment_index += 1
                    current_end = next_seg['end']
                    j += 1
                    continue

                # Малая overlap - склеиваем
                if abs(pause) <= 2.0:
                    texts.append(next_seg['text'])
                    all_segments_in_group.append(next_seg)
                    
                    # 🆕 v16.28.2: Debug добавления
                    if in_target_range:
                        print(f"     ➕ Сегмент #{segment_index}: [{seconds_to_hms(next_seg['start'])}-{seconds_to_hms(next_seg['end'])}] (overlap {abs(pause):.1f}s)")
                        print(f"        Текст: \"{next_seg['text'][:80]}...\"")
                    
                    segment_index += 1
                    current_end = next_seg['end']
                    j += 1
                    continue
                else:
                    print(f"    ↳ Overlap {abs(pause):.1f}s без similarity → ❌ STOP")
                    merge_continue = False
                    break

            # Обработка обычной паузы
            else:
                # Для НЕ-Журналиста
                if current_speaker != "Журналист":
                    if pause <= 2.0:
                        texts.append(next_seg['text'])
                        all_segments_in_group.append(next_seg)
                        
                        # 🆕 v16.28.2: Debug добавления
                        if in_target_range:
                            print(f"     ➕ Сегмент #{segment_index}: [{seconds_to_hms(next_seg['start'])}-{seconds_to_hms(next_seg['end'])}] (пауза {pause:.1f}s)")
                            print(f"        Текст: \"{next_seg['text'][:80]}...\"")
                        else:
                            print(f"    ↳ {next_seg.get('start_hms', '')} ⏸️ {pause:.1f}s → ✅ merge")
                        
                        segment_index += 1
                        current_end = next_seg['end']
                        j += 1
                        continue
                    elif pause <= 5.0 and any(similarity(next_seg['text'], t) for t in texts[-2:]):
                        texts.append(next_seg['text'])
                        all_segments_in_group.append(next_seg)
                        
                        # 🆕 v16.28.2: Debug добавления
                        if in_target_range:
                            print(f"     ➕ Сегмент #{segment_index}: [{seconds_to_hms(next_seg['start'])}-{seconds_to_hms(next_seg['end'])}] (пауза {pause:.1f}s, similarity)")
                            print(f"        Текст: \"{next_seg['text'][:80]}...\"")
                        else:
                            print(f"    ↳ {next_seg.get('start_hms', '')} ⏸️ {pause:.1f}s → ✅ merge (similarity)")
                        
                        segment_index += 1
                        current_end = next_seg['end']
                        j += 1
                        continue
                    else:
                        print(f"    ↳ {current_speaker} пауза {pause:.1f}s > 5.0s → ❌ STOP")
                        merge_continue = False
                        break

                # Для Журналиста
                if current_speaker == "Журналист":
                    if pause <= 3.0 and pause >= -12.0:
                        texts.append(next_seg['text'])
                        all_segments_in_group.append(next_seg)
                        print(f"    ↳ {next_seg.get('start_hms', '')} ⏸️ {pause:.1f}s → ✅ merge")
                        segment_index += 1
                        current_end = next_seg['end']
                        j += 1
                        continue
                    else:
                        print(f"    ↳ Журналист пауза {pause:.1f}s > 3.0s → ❌ STOP")
                        merge_continue = False
                        break

        # 🆕 v16.28.2: Итоговая статистика склеенных сегментов
        total_words = sum(len(t.split()) for t in texts)
        if in_target_range:
            print(f"\n     📊 Всего собрано: {len(texts)} сегментов, {total_words} слов")
            print(f"     📊 Финальный диапазон: [{seconds_to_hms(start_time)}-{seconds_to_hms(current_end)}]")
        elif debug:
            print(f"    📊 Собрано: {len(texts)} сегментов, {total_words} слов")

        # 🆕 v16.14: ВЫБИРАЕМ ДОМИНИРУЮЩИЙ СЕГМЕНТ
        dominant_segment = max(all_segments_in_group, key=lambda s: len(s.get('text', '')))
        
        if len(all_segments_in_group) > 1:
            print(f"    🎯 Доминирующий: {dominant_segment.get('speaker')} / {dominant_segment.get('raw_speaker_id')} (длина: {len(dominant_segment.get('text', ''))} символов)")

        # Склеиваем тексты
        final_text = ' '.join(texts)
        
        # 🆕 v16.28.2: Показываем текст ДО очистки
        if in_target_range:
            print(f"\n     📝 Склеенный текст ДО очистки ({len(final_text)} символов, {len(final_text.split())} слов):")
            print(f"        Начало: \"{final_text[:100]}...\"")
            print(f"        Конец:  \"...{final_text[-100:]}\"")
        
        # Очистка
        if debug or in_target_range:
            print(f"    🧹 Вызов clean_loops ({len(final_text)} символов)...")
        
        final_text = clean_loops(final_text, debug=(debug or in_target_range))
        
        # 🆕 v16.28.2: Показываем текст ПОСЛЕ clean_loops
        if in_target_range:
            print(f"\n     📝 После clean_loops ({len(final_text)} символов, {len(final_text.split())} слов):")
            print(f"        Начало: \"{final_text[:100]}...\"")
            print(f"        Конец:  \"...{final_text[-100:]}\"")
        
        if debug or in_target_range:
            print(f"    🧹 Вызов clean_hallucinations_from_text...")
        
        final_text = clean_hallucinations_from_text(final_text, current_speaker, debug=(debug or in_target_range))
        
        # 🆕 v16.28.2: Показываем ФИНАЛЬНЫЙ текст
        if in_target_range:
            print(f"\n     ✅ ФИНАЛЬНЫЙ текст ({len(final_text)} символов, {len(final_text.split())} слов):")
            print(f"        Начало: \"{final_text[:100]}...\"")
            print(f"        Конец:  \"...{final_text[-100:]}\"")
            
            # Проверяем наличие целевой фразы
            target_phrase = "то есть это был такой пункт"
            if target_phrase in final_text.lower():
                print(f"        ✅ Целевая фраза \"{target_phrase}\" НАЙДЕНА!")
            else:
                print(f"        ❌ Целевая фраза \"{target_phrase}\" НЕ НАЙДЕНА!")
        elif debug:
            print(f"    ✅ Очистка завершена, финальный текст: {len(final_text)} символов")

        if final_text:
            # 🆕 v16.14: Берём speaker и raw_speaker_id от ДОМИНИРУЮЩЕГО сегмента!
            merged.append({
                "speaker": dominant_segment.get('speaker', current_speaker),
                "time": current.get('start_hms', seconds_to_hms(start_time)),
                "start": start_time,
                "end": current_end,
                "text": final_text,
                "confidence": current.get('confidence', ''),
                "raw_speaker_id": dominant_segment.get('raw_speaker_id', '')
            })

            if len(texts) > 1:
                print(f"  ✅ Склеено {len(texts)} сегментов → {len(final_text.split())} слов")

        i = j

    if debug:
        print(f"\n✅ merge_replicas завершён: {len(merged)} merged сегментов из {len(segments)} исходных")

    return merged
