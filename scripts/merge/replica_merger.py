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
    🆕 v16.22: FIX БАГ #3 - Детекция вариаций с fuzzy matching
    🔧 v16.1: Удаляет зацикленные фразы (loop artifacts)
    🆕 v16.20: Добавлен debug параметр
    
    **ПРОБЛЕМА (БАГ #3):**
    Функция детектировала только ТОЧНЫЕ повторы:
    - "учитывать была немецкая" ← phrase1
    - "учитывать это было" ← phrase2 (РАЗНЫЕ слова!)
    - phrase1 ≠ phrase2 → НЕ детектируется!
    
    **FIX v16.22:**
    Используем fuzzy matching (SequenceMatcher) для детекции вариаций:
    - Если фразы похожи ≥75% → считаем повтором
    - Удаляем ВСЕ вариации, оставляем только первую
    
    Args:
        text: Текст для очистки
        debug: Показывать debug output
    
    Returns:
        Очищенный текст без loop artifacts
    """
    if debug:
        print(f"    🧹 clean_loops: обработка текста ({len(text)} символов, {len(text.split())} слов)")
    
    words = text.split()
    seen = []  # Список увиденных фраз для fuzzy matching
    cleaned = []
    
    removed_count = 0
    i = 0
    
    while i < len(words):
        phrase = ' '.join(words[i:i+3])  # 3 слова
        phrase_lower = phrase.lower()
        
        # 🆕 v16.22: Fuzzy matching с предыдущими фразами
        is_loop = False
        
        for prev_phrase in seen:
            similarity = SequenceMatcher(None, phrase_lower, prev_phrase).ratio()
            
            if similarity >= 0.75:  # Похожесть ≥75%
                is_loop = True
                removed_count += 1
                
                if debug:
                    print(f"      🔁 LOOP (similarity={similarity:.2f}): '{phrase}' ≈ '{prev_phrase}'")
                
                break
        
        if is_loop:
            i += 1  # Пропускаем повтор
            continue
        
        # Добавляем фразу в seen
        seen.append(phrase_lower)
        
        # Добавляем слова в результат
        cleaned.extend(words[i:i+3])
        i += 3
    
    final = ' '.join(cleaned)
    
    # Удаляем повторяющуюся пунктуацию
    final = re.sub(r'([.,!?])\1{2,}', r'\1', final)
    
    if debug:
        if removed_count > 0:
            print(f"    ✅ clean_loops: готово ({len(final)} символов, удалено {removed_count} loop artifacts)")
        else:
            print(f"    ✅ clean_loops: готово ({len(final)} символов, loops не найдены)")
    
    return final.strip()

def merge_replicas(segments, debug=False):
    """
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

        if debug:
            print(f"  🔀 MERGE #{merge_count}: {current.get('start_hms', seconds_to_hms(start_time))} {current_speaker} — начало")
        else:
            print(f"  🔀 {current.get('start_hms', seconds_to_hms(start_time))} {current_speaker} — начало merge")

        # Защита от infinite loop
        max_iterations = len(segments) * 2
        iteration_count = 0

        # Ищем соседние сегменты того же спикера
        j = i + 1
        merge_continue = True

        while j < len(segments) and merge_continue:
            iteration_count += 1
            if iteration_count > max_iterations:
                print(f"    ⚠️ ЗАЩИТА: превышено {max_iterations} итераций на merge #{merge_count}")
                break

            next_seg = segments[j]
            next_raw_id = next_seg.get('raw_speaker_id', '')
            pause = next_seg['start'] - current_end

            # 🆕 v16.23: ОСЛАБЛЕННАЯ ПРОВЕРКА СПИКЕРА для БАГ #4
            # СТАРАЯ логика v16.0:
            #   if next_seg['speaker'] != current_speaker:
            #       break
            #
            # НОВАЯ логика v16.23:
            #   Проверяем speaker, НО игнорируем различия raw_speaker_id
            #   если speaker одинаковый и это НЕ "Журналист"/"Оператор"
            
            if next_seg['speaker'] != current_speaker:
                merge_continue = False
                break
            
            # 🆕 v16.23: Если speaker одинаковый, но raw_speaker_id разные
            # → Это БАГ split, НО мы всё равно СЛИВАЕМ (для основного спикера)
            if current_raw_id != next_raw_id and current_raw_id and next_raw_id:
                if current_speaker not in ("Журналист", "Оператор"):
                    # Для основного спикера игнорируем различия raw_speaker_id
                    print(f"    ↳ ⚠️ raw_speaker_id разные ({current_raw_id} vs {next_raw_id}), но speaker={current_speaker} → ✅ merge anyway")
                else:
                    # Для Журналиста/Оператора НЕ игнорируем (защита v16.0)
                    print(f"    ↳ ❌ raw_speaker_id разные ({current_raw_id} vs {next_raw_id}) для {current_speaker} → STOP")
                    merge_continue = False
                    break

            # Далее идёт обычная логика overlap/pause...
            # (копируем всё остальное из текущей версии)

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
                        # 🆕 v16.14: Заменяем и в группе
                        all_segments_in_group[-1] = next_seg
                    current_end = next_seg['end']
                    j += 1
                    continue

                if sim > 0.60:
                    # Похожие - добавляем
                    texts.append(next_seg['text'])
                    all_segments_in_group.append(next_seg)  # 🆕 v16.14
                    current_end = next_seg['end']
                    j += 1
                    continue

                # Малая overlap - склеиваем
                if abs(pause) <= 2.0:
                    texts.append(next_seg['text'])
                    all_segments_in_group.append(next_seg)  # 🆕 v16.14
                    current_end = next_seg['end']
                    j += 1
                    continue
                else:
                    # 🆕 v16.21: FIX - Слишком большая overlap без similarity → STOP
                    # Было: j += 1; continue → infinite loop!
                    # Стало: break → завершаем merge
                    print(f"    ↳ Overlap {abs(pause):.1f}s без similarity → ❌ STOP")
                    merge_continue = False
                    break

            # Обработка обычной паузы
            else:
                # Для НЕ-Журналиста
                if current_speaker != "Журналист":
                    if pause <= 2.0:
                        texts.append(next_seg['text'])
                        all_segments_in_group.append(next_seg)  # 🆕 v16.14
                        print(f"    ↳ {next_seg.get('start_hms', '')} ⏸️ {pause:.1f}s → ✅ merge")
                        current_end = next_seg['end']
                        j += 1
                        continue
                    elif pause <= 5.0 and any(similarity(next_seg['text'], t) for t in texts[-2:]):
                        # Пауза 2-5s, но есть similarity с предыдущими
                        texts.append(next_seg['text'])
                        all_segments_in_group.append(next_seg)  # 🆕 v16.14
                        print(f"    ↳ {next_seg.get('start_hms', '')} ⏸️ {pause:.1f}s → ✅ merge (similarity)")
                        current_end = next_seg['end']
                        j += 1
                        continue
                    else:
                        print(f"    ↳ {current_speaker} пауза {pause:.1f}s > 5.0s → ❌ STOP")
                        merge_continue = False
                        break

                # Для Журналиста НЕ склеиваем при паузе > 3s
                if current_speaker == "Журналист":
                    if pause <= 3.0 and pause >= -12.0:
                        texts.append(next_seg['text'])
                        all_segments_in_group.append(next_seg)  # 🆕 v16.14
                        print(f"    ↳ {next_seg.get('start_hms', '')} ⏸️ {pause:.1f}s → ✅ merge")
                        current_end = next_seg['end']
                        j += 1
                        continue
                    else:
                        print(f"    ↳ Журналист пауза {pause:.1f}s > 3.0s → ❌ STOP")
                        merge_continue = False
                        break

        # 🆕 v16.20: DEBUG - показываем количество собранных сегментов
        if debug:
            total_words = sum(len(t.split()) for t in texts)
            print(f"    📊 Собрано: {len(texts)} сегментов, {total_words} слов")

        # 🆕 v16.14: ВЫБИРАЕМ ДОМИНИРУЮЩИЙ СЕГМЕНТ (самый длинный по тексту)
        dominant_segment = max(all_segments_in_group, key=lambda s: len(s.get('text', '')))
        
        if len(all_segments_in_group) > 1:
            print(f"    🎯 Доминирующий: {dominant_segment.get('speaker')} / {dominant_segment.get('raw_speaker_id')} (длина: {len(dominant_segment.get('text', ''))} символов)")

        # 🆕 v16.20: DEBUG перед склейкой
        if debug:
            print(f"    🔗 Склейка текстов...")

        # Склеиваем тексты
        final_text = ' '.join(texts)
        
        # 🆕 v16.20: DEBUG перед clean_loops
        if debug:
            print(f"    🧹 Вызов clean_loops ({len(final_text)} символов)...")
        
        final_text = clean_loops(final_text, debug=debug)
        
        # 🆕 v16.20: DEBUG перед clean_hallucinations
        if debug:
            print(f"    🧹 Вызов clean_hallucinations_from_text...")
        
        final_text = clean_hallucinations_from_text(final_text, current_speaker, debug=debug)
        
        # 🆕 v16.20: DEBUG после очистки
        if debug:
            print(f"    ✅ Очистка завершена, финальный текст: {len(final_text)} символов")

        if final_text:
            # 🆕 v16.14: Берём speaker и raw_speaker_id от ДОМИНИРУЮЩЕГО сегмента!
            merged.append({
                "speaker": dominant_segment.get('speaker', current_speaker),  # 🆕 v16.14
                "time": current.get('start_hms', seconds_to_hms(start_time)),
                "start": start_time,
                "end": current_end,
                "text": final_text,
                "confidence": current.get('confidence', ''),
                "raw_speaker_id": dominant_segment.get('raw_speaker_id', '')  # 🆕 v16.14
            })

            if len(texts) > 1:
                print(f"  ✅ Склеено {len(texts)} сегментов → {len(final_text.split())} слов")

        i = j

    if debug:
        print(f"\n✅ merge_replicas завершён: {len(merged)} merged сегментов из {len(segments)} исходных")

    return merged
