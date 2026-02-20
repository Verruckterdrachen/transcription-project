"""
merge/replica_merger.py - Склейка реплик одного спикера

🆕 v17.9: FIX БАГ #27 - Ложное удаление слов с low-meaningful N-граммами
🆕 v17.4: FIX БАГ #17 - Дубли слов на стыках при склейке
🆕 v16.22: FIX БАГ #3 - Loop artifacts с вариациями слов
🆕 v16.21: CRITICAL FIX - Infinite Loop в overlap handling
🆕 v16.20: DEBUG OUTPUT для диагностики зависания
🆕 v16.14: КРИТИЧЕСКИЙ FIX - speaker от САМОГО ДЛИННОГО сегмента
"""

from difflib import SequenceMatcher
import re
from core.utils import seconds_to_hms
from corrections.hallucinations import clean_hallucinations_from_text
from merge.deduplicator import join_texts_deduplicated

# ═══════════════════════════════════════════════════════════════════════════
# 🆕 v17.9: FIX БАГ #27 — стоп-слова для фильтрации бессодержательных N-грамм
# ROOT CAUSE: clean_loops сравнивал N-граммы из грамматических слов
# ("был. И вот" ≈ "было. и, в", sim=0.80) и ошибочно удалял "был."
# FIX: N-граммы с < MIN_MEANINGFUL_WORDS знаменательных слов — пропускаем,
# не добавляем в seen[] и не удаляем.
# ═══════════════════════════════════════════════════════════════════════════

RUSSIAN_STOP_WORDS = {
    # Формы "быть" — ключевые для данного бага
    'был', 'была', 'было', 'были', 'буду', 'будет',
    'будут', 'будем', 'будете', 'бывает', 'есть', 'быть',
    # Предлоги
    'в', 'во', 'на', 'с', 'со', 'к', 'ко', 'по', 'из',
    'за', 'до', 'при', 'через', 'об', 'о', 'у', 'для',
    'от', 'под', 'над', 'про', 'без', 'между', 'среди',
    # Союзы
    'и', 'а', 'но', 'или', 'что', 'как', 'если', 'когда',
    'где', 'чтобы', 'потому', 'тоже', 'также', 'либо',
    'ни', 'хотя', 'зато', 'однако',
    # Частицы
    'вот', 'же', 'ли', 'бы', 'ну', 'не', 'да', 'то', 'так',
    'лишь', 'только', 'даже', 'уж',
    # Личные местоимения (все падежи)
    'я', 'ты', 'он', 'она', 'оно', 'мы', 'вы', 'они',
    'меня', 'тебя', 'его', 'её', 'ее', 'нас', 'вас', 'их',
    'мне', 'тебе', 'ему', 'ей', 'нам', 'вам', 'им',
    # Указательные местоимения (только "это"-группа)
    'это', 'этот', 'эта', 'эти',
    # Наречия с низким семантическим весом
    'там', 'тут', 'здесь', 'тогда', 'уже', 'еще', 'ещё',
    'очень', 'совсем', 'весьма',
}
MIN_MEANINGFUL_WORDS = 2


def _count_meaningful(phrase: str) -> int:
    """
    Считает количество знаменательных слов в N-грамме.
    Очищает пунктуацию, приводит к нижнему регистру.
    Знаменательное слово = не входит в RUSSIAN_STOP_WORDS.
    """
    clean = re.sub(r'[.,!?;:«»"\'()\[\]]', '', phrase.lower())
    words = clean.split()
    return sum(1 for w in words if w not in RUSSIAN_STOP_WORDS)


def clean_loops(text, debug=False):
    """
    🆕 v17.9: FIX БАГ #27 - Пропуск N-грамм без знаменательных слов
    🆕 v17.3: FIX БАГ #16 (v17.2) - Увеличение LOOP_WINDOW до 30
    🆕 v17.2: FIX БАГ #16 - Ограничение окна seen[] для loop detection
    🆕 v16.22: FIX БАГ #3 - Детекция вариаций с fuzzy matching
    🔧 v16.1: Удаляет зацикленные фразы (loop artifacts)
    🆕 v16.20: Добавлен debug параметр

    **ПРОБЛЕМА (БАГ #27):**
    clean_loops удалял слово "был." из фразы "но Жуков не был. И вот немцы".
    N-грамма "был. И вот" сравнивалась с якорем "было. и, в" (sim=0.80 ≥ 0.75)
    и ошибочно считалась loop artifact.

    **ROOT CAUSE:**
    N-граммы из чисто грамматических слов (формы "быть" + союзы + частицы)
    дают высокое fuzzy-сходство без семантической связи.
    Порог 0.75 не защищал от таких коллизий.

    **FIX v17.9:**
    Перед добавлением N-граммы в seen[] и перед loop-проверкой:
    считаем знаменательные слова. Если < MIN_MEANINGFUL_WORDS=2 —
    слова сохраняем в output, но в seen[] не добавляем и loop не проверяем.

    Args:
        text: Текст для очистки
        debug: Показывать debug output

    Returns:
        Очищенный текст без loop artifacts
    """
    LOOP_WINDOW = 30

    if debug:
        print(f"    🧹 clean_loops: обработка текста ({len(text)} символов, {len(text.split())} слов)")

    words = text.split()
    seen = []
    cleaned = []

    removed_count = 0
    i = 0

    while i < len(words):
        phrase = ' '.join(words[i:i+3])
        phrase_lower = phrase.lower()

        # 🆕 v17.9: FIX БАГ #27 - пропуск N-грамм без знаменательных слов
        if _count_meaningful(phrase_lower) < MIN_MEANINGFUL_WORDS:
            # Слова сохраняем в output
            # В seen[] НЕ добавляем — не создаём ложных якорей
            cleaned.extend(words[i:i+3])
            i += 3
            continue

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

        # 🆕 v17.3: Добавляем фразу в seen с ограничением окна
        seen.append(phrase_lower)
        if len(seen) > LOOP_WINDOW:
            seen.pop(0)

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
    🆕 v17.4: FIX БАГ #17 - join_texts_deduplicated вместо ' '.join
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

    # 🆕 v17.4: Целевой диапазон для БАГ #17 (00:09:54 = 594 секунды)
    TARGET_RANGE = (590, 600)

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

        # 🆕 v17.4: Проверка - попадает ли этот merge в целевой диапазон БАГ #17?
        in_target_range = (start_time <= TARGET_RANGE[1] and current_end >= TARGET_RANGE[0])

        if debug or in_target_range:
            print(f"\n  🔀 MERGE #{merge_count}: {current.get('start_hms', seconds_to_hms(start_time))} {current_speaker} — начало")
            if in_target_range:
                print(f"     🎯 TARGET RANGE БАГ #17 DETECTED! (ищем 00:09:54)")
        else:
            print(f"  🔀 {current.get('start_hms', seconds_to_hms(start_time))} {current_speaker} — начало merge")

        # 🆕 v17.4: Показываем первый сегмент
        if in_target_range:
            print(f"     📝 Сегмент #0: [{seconds_to_hms(current['start'])}-{seconds_to_hms(current['end'])}]")
            print(f"        Текст: \"{current['text'][:80]}...\"")

        # Защита от infinite loop
        max_iterations = len(segments) * 2
        iteration_count = 0

        # Ищем соседние сегменты того же спикера
        j = i + 1
        merge_continue = True
        segment_index = 1

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
                    if len(next_seg['text']) > len(texts[-1]):
                        texts[-1] = next_seg['text']
                        all_segments_in_group[-1] = next_seg

                        if in_target_range:
                            print(f"     🔄 Сегмент #{segment_index-1} ЗАМЕНЁН (дубликат, более длинный)")
                            print(f"        Новый текст: \"{next_seg['text'][:80]}...\"")

                    current_end = next_seg['end']
                    j += 1
                    continue

                if sim > 0.60:
                    texts.append(next_seg['text'])
                    all_segments_in_group.append(next_seg)

                    if in_target_range:
                        print(f"     ➕ Сегмент #{segment_index}: [{seconds_to_hms(next_seg['start'])}-{seconds_to_hms(next_seg['end'])}] (overlap, sim={sim:.2f})")
                        print(f"        Текст: \"{next_seg['text'][:80]}...\"")

                    segment_index += 1
                    current_end = next_seg['end']
                    j += 1
                    continue

                if abs(pause) <= 2.0:
                    texts.append(next_seg['text'])
                    all_segments_in_group.append(next_seg)

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

        # 🆕 v17.4: Итоговая статистика склеенных сегментов
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

        # 🆕 v17.4: Склеиваем тексты через join_texts_deduplicated (FIX БАГ #17)
        if in_target_range or debug:
            print(f"    🔗 Вызов join_texts_deduplicated для {len(texts)} текстов...")

        final_text = join_texts_deduplicated(texts, debug=(in_target_range or debug))

        if in_target_range:
            print(f"\n     📝 После join_texts_deduplicated ({len(final_text)} символов, {len(final_text.split())} слов):")
            print(f"        Начало: \"{final_text[:100]}...\"")
            print(f"        Конец:  \"...{final_text[-100:]}\"")

        if debug or in_target_range:
            print(f"    🧹 Вызов clean_loops ({len(final_text)} символов)...")

        final_text = clean_loops(final_text, debug=(debug or in_target_range))

        if in_target_range:
            print(f"\n     📝 После clean_loops ({len(final_text)} символов, {len(final_text.split())} слов):")
            print(f"        Начало: \"{final_text[:100]}...\"")
            print(f"        Конец:  \"...{final_text[-100:]}\"")

        if debug or in_target_range:
            print(f"    🧹 Вызов clean_hallucinations_from_text...")

        final_text = clean_hallucinations_from_text(final_text, current_speaker, debug=(debug or in_target_range))

        if in_target_range:
            print(f"\n     ✅ ФИНАЛЬНЫЙ текст ({len(final_text)} символов, {len(final_text.split())} слов):")
            print(f"        Начало: \"{final_text[:100]}...\"")
            print(f"        Конец:  \"...{final_text[-100:]}\"")

            if "достаточно достаточно" in final_text.lower():
                print(f"        ❌ ДУБЛЬ «достаточно Достаточно» ВСЁ ЕЩЁ ЕСТЬ!")
            else:
                print(f"        ✅ Дубль «достаточно Достаточно» УСТРАНЁН!")
        elif debug:
            print(f"    ✅ Очистка завершена, финальный текст: {len(final_text)} символов")

        if final_text:
            # 🆕 v17.10: sub_segments для точного timestamp injection (Вариант A)
            # Сохраняем границы оригинальных Whisper-сегментов ДО clean_loops
            merged.append({
                "speaker": dominant_segment.get('speaker', current_speaker),
                "time": current.get('start_hms', seconds_to_hms(start_time)),
                "start": start_time,
                "end": current_end,
                "text": final_text,
                "confidence": current.get('confidence', ''),
                "raw_speaker_id": dominant_segment.get('raw_speaker_id', ''),
                "sub_segments": [
                    {
                        "start": s["start"],
                        "end":   s["end"],
                        "words": len(s.get("text", "").split())
                    }
                    for s in all_segments_in_group
                ]
            })

            if len(texts) > 1:
                print(f"  ✅ Склеено {len(texts)} сегментов → {len(final_text.split())} слов")

        i = j

    if debug:
        print(f"\n✅ merge_replicas завершён: {len(merged)} merged сегментов из {len(segments)} исходных")

    return merged
