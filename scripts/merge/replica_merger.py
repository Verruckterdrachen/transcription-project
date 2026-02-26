"""
merge/replica_merger.py - Склейка реплик одного спикера

🆕 v17.10: FIX БАГ #32 - GAP_FILLED corruption + time-overlap duplicates
           GUARD A: инвертированный timestamp (end < start) → DROP
           GUARD B: start < last_gap_end (перекрывает GAP диапазон) → DROP
           GUARD C: GAP с ≥2 общими значимыми словами с lookBEHIND → DROP (corrupted)
                    GAP с 0-1 общих слов → KEEP (легитимный)
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

# ═══════════════════════════════════════════════════════════════════════════
# 🆕 v17.10: GUARD C — константы для БАГ #32
# ═══════════════════════════════════════════════════════════════════════════

GAP_LOOKBEHIND_SEGS      = 5     # глубина lookBEHIND (последние N текстов)
GAP_CORRUPTION_NGRAM_MIN = 3     # минимум значимых слов в N-грамме
GAP_CORRUPTION_SIM       = 0.85  # порог фразового совпадения

def _count_meaningful(phrase: str) -> int:
    """
    Считает количество знаменательных слов в N-грамме.
    Очищает пунктуацию, приводит к нижнему регистру.
    Знаменательное слово = не входит в RUSSIAN_STOP_WORDS.
    """
    clean = re.sub(r'[.,!?;:«»"\'()\[\]]', '', phrase.lower())
    words = clean.split()
    return sum(1 for w in words if w not in RUSSIAN_STOP_WORDS)


def _meaningful_words(text: str) -> list:
    """
    🆕 v17.10: Возвращает список значимых слов (len>3, не стоп-слово).
    Используется GUARD C для lookBEHIND анализа.
    """
    clean = re.sub(r'[.,!?;:«»"\'()\[\]]', '', text.lower())
    return [w for w in clean.split() if w not in RUSSIAN_STOP_WORDS and len(w) > 3]

def _gap_is_corrupted(gap_text: str, preceding_texts: list, debug: bool = False) -> bool:
    gap_words    = _meaningful_words(gap_text)
    behind_words = _meaningful_words(' '.join(preceding_texts[-GAP_LOOKBEHIND_SEGS:]))
    if len(gap_words) < GAP_CORRUPTION_NGRAM_MIN or \
       len(behind_words) < GAP_CORRUPTION_NGRAM_MIN:
        if debug:
            print(f"    🔎 GUARD C: мало значимых слов → KEEP")
        return False
    best_sim = 0.0
    best_ngram = ("", "")
    k_max = min(len(gap_words), len(behind_words), 6)
    for k in range(k_max, GAP_CORRUPTION_NGRAM_MIN - 1, -1):
        for gi in range(len(gap_words) - k + 1):
            gw = gap_words[gi:gi+k]
            for bi in range(len(behind_words) - k + 1):
                bw = behind_words[bi:bi+k]
                sim = SequenceMatcher(None, ' '.join(gw), ' '.join(bw)).ratio()
                if sim > best_sim:
                    best_sim = sim
                    best_ngram = (' '.join(gw), ' '.join(bw))
    if debug:
        print(f"    🔎 GUARD C ngram: best_sim={best_sim:.2f} "
              f"'{best_ngram[0]}' ≈ '{best_ngram[1]}'")
    return best_sim >= GAP_CORRUPTION_SIM

def clean_loops(text, debug=False):
    """
    🆕 v17.9: FIX БАГ #27 - Пропуск N-грамм без знаменательных слов
    🆕 v17.3: FIX БАГ #16 (v17.2) - Увеличение LOOP_WINDOW до 30
    🆕 v17.2: FIX БАГ #16 - Ограничение окна seen[] для loop detection
    🆕 v16.22: FIX БАГ #3 - Детекция вариаций с fuzzy matching
    🔧 v16.1: Удаляет зацикленные фразы (loop artifacts)
    🆕 v16.20: Добавлен debug параметр
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
            cleaned.extend(words[i:i+3])
            i += 3
            continue

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
            if debug:
                left_context = ' '.join(cleaned[-3:]) if len(cleaned) >= 3 else ' '.join(cleaned)
                last_cleaned = cleaned[-1] if cleaned else "(начало)"
                last_word    = last_cleaned.lower().rstrip('.,!?«»')
                HANGING_PREPOSITIONS = {
                    'на', 'в', 'во', 'с', 'со', 'к', 'по', 'из', 'за', 'до',
                    'при', 'через', 'о', 'об', 'у', 'для', 'от', 'под', 'над'
                }
                print(f"      ⚠️ УДАЛЯЕМ: '{phrase}'")
                print(f"         Причина: совпадение с '{prev_phrase}' (sim={similarity:.2f})")
                print(f"         Контекст слева: '...{left_context}'")
                print(f"         Слово перед удалением: '{last_cleaned}'")
                if last_word in HANGING_PREPOSITIONS:
                    print(f"         🔴 РИСК ОБРУБКА! '{last_cleaned}' — предлог без продолжения!")

            # ── v17.10 FIX БАГ #15 РЕГРЕССИЯ ──────────────────────────────
            last_word_check = cleaned[-1].lower().rstrip('.,!?«»') if cleaned else ""
            HANGING_PREPOSITIONS = {
                'на', 'в', 'во', 'с', 'со', 'к', 'по', 'из', 'за', 'до',
                'при', 'через', 'о', 'об', 'у', 'для', 'от', 'под', 'над'
            }
            if last_word_check in HANGING_PREPOSITIONS:
                if debug:
                    print(f"         🛡️ ЗАЩИТА: предлог '{last_word_check}' → пропускаем удаление")
                seen.append(phrase_lower)
                if len(seen) > LOOP_WINDOW:
                    seen.pop(0)
                cleaned.extend(words[i:i+3])
                i += 3
                continue
            # ── конец FIX ──────────────────────────────────────────────────

            i += 1
            continue

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
    🆕 v17.10: FIX БАГ #32 — три GUARD для GAP_FILLED сегментов
               GUARD A: end < start → DROP (инвертированный timestamp)
               GUARD B: start < last_gap_end → DROP (временное перекрытие)
               GUARD C: GAP corrupted по lookBEHIND → DROP
    🆕 v17.4: FIX БАГ #17 - join_texts_deduplicated вместо ' '.join
    🆕 v16.28.2: ДЕТАЛЬНЫЙ DEBUG для поиска потери текста
    🆕 v16.23: ОСЛАБЛЕНИЕ ЗАЩИТЫ v16.0 для БАГ #4
    🆕 v16.21: CRITICAL FIX - Infinite Loop в overlap handling
    """
    if not segments:
        return []

    def similarity(a, b):
        return SequenceMatcher(None, a.lower(), b.lower()).ratio() > 0.75

    merged = []
    i = 0
    merge_count = 0
    TARGET_RANGE = (590, 600)

    while i < len(segments):
        merge_count += 1
        current = segments[i]
        current_speaker = current['speaker']
        current_raw_id = current.get('raw_speaker_id', '')

        texts = [current['text']]
        current_end = current['end']
        start_time = current['start']
        all_segments_in_group = [current]

        # 🆕 v17.10: сбрасываем last_gap_end для каждой новой реплики
        last_gap_end = None

        in_target_range = (start_time <= TARGET_RANGE[1] and current_end >= TARGET_RANGE[0])

        if debug or in_target_range:
            print(f"\n  🔀 MERGE #{merge_count}: {current.get('start_hms', seconds_to_hms(start_time))} {current_speaker} — начало")
            if in_target_range:
                print(f"     🎯 TARGET RANGE БАГ #17 DETECTED! (ищем 00:09:54)")
        else:
            print(f"  🔀 {current.get('start_hms', seconds_to_hms(start_time))} {current_speaker} — начало merge")

        if in_target_range:
            print(f"     📝 Сегмент #0: [{seconds_to_hms(current['start'])}-{seconds_to_hms(current['end'])}]")
            print(f"        Текст: \"{current['text'][:80]}...\"")

        max_iterations = len(segments) * 2
        iteration_count = 0
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

            # ── ПРОВЕРКА СПИКЕРА ─────────────────────────────────────────
            if next_seg['speaker'] != current_speaker:
                merge_continue = False
                break

            if current_raw_id != next_raw_id and current_raw_id and next_raw_id:
                if current_speaker not in ("Журналист", "Оператор"):
                    print(f"    ↳ ⚠️ raw_speaker_id разные ({current_raw_id} vs {next_raw_id}), но speaker={current_speaker} → ✅ merge anyway")
                else:
                    print(f"    ↳ ❌ raw_speaker_id разные ({current_raw_id} vs {next_raw_id}) для {current_speaker} → STOP")
                    merge_continue = False
                    break

            # ══════════════════════════════════════════════════════════════
            # 🆕 v17.10: GUARD A — инвертированный timestamp
            # ══════════════════════════════════════════════════════════════
            if next_seg['end'] < next_seg['start']:
                print(f"    ↳ ⛔ GUARD A: [{next_seg['start']:.2f}–{next_seg['end']:.2f}] инвертирован → DROP '{next_seg['text'][:40]}'")
                current_end = max(current_end, next_seg['end'])
                j += 1
                continue

            # ══════════════════════════════════════════════════════════════
            # 🆕 v17.10: GUARD B — временное перекрытие с GAP диапазоном
            # ══════════════════════════════════════════════════════════════
            if last_gap_end is not None and next_seg['start'] < last_gap_end:
                print(f"    ↳ ⛔ GUARD B: start({next_seg['start']:.2f}) < gap_end({last_gap_end:.2f}) → DROP '{next_seg['text'][:40]}'")
                current_end = max(current_end, next_seg['end'])
                j += 1
                continue

            # ══════════════════════════════════════════════════════════════
            # 🆕 v17.10: GUARD C — GAP_FILLED corruption check
            # ══════════════════════════════════════════════════════════════
            if next_seg.get('from_gap'):
                last_gap_end = next_seg['end']   # запоминаем ВСЕГДА
                if _gap_is_corrupted(next_seg['text'], texts, debug=debug):
                    print(f"    ↳ ⛔ GUARD C: GAP corrupted → DROP '{next_seg['text'][:50]}'")
                    current_end = max(current_end, next_seg['end'])
                    j += 1
                    continue
                else:
                    print(f"    ↳ ✅ GUARD C: GAP легитимен → KEEP '{next_seg['text'][:50]}'")
                    # продолжаем в штатную pause-логику

            # ── ШТАТНАЯ PAUSE-ЛОГИКА ─────────────────────────────────────
            if pause < 0:
                sim = SequenceMatcher(None, texts[-1] if texts else "", next_seg['text']).ratio()

                if sim > 0.85:
                    if len(next_seg['text']) > len(texts[-1]):
                        texts[-1] = next_seg['text']
                        all_segments_in_group[-1] = next_seg
                        if in_target_range:
                            print(f"     🔄 Сегмент #{segment_index-1} ЗАМЕНЁН (дубликат, более длинный)")
                    current_end = next_seg['end']
                    j += 1
                    continue

                if sim > 0.60:
                    texts.append(next_seg['text'])
                    all_segments_in_group.append(next_seg)
                    if in_target_range:
                        print(f"     ➕ Сегмент #{segment_index}: (overlap, sim={sim:.2f}) \"{next_seg['text'][:80]}\"")
                    segment_index += 1
                    current_end = next_seg['end']
                    j += 1
                    continue

                if abs(pause) <= 2.0:
                    texts.append(next_seg['text'])
                    all_segments_in_group.append(next_seg)
                    if in_target_range:
                        print(f"     ➕ Сегмент #{segment_index}: (overlap {abs(pause):.1f}s) \"{next_seg['text'][:80]}\"")
                    segment_index += 1
                    current_end = next_seg['end']
                    j += 1
                    continue
                else:
                    print(f"    ↳ Overlap {abs(pause):.1f}s без similarity → ❌ STOP")
                    merge_continue = False
                    break

            else:
                if current_speaker != "Журналист":
                    if pause <= 2.0:
                        texts.append(next_seg['text'])
                        all_segments_in_group.append(next_seg)
                        if in_target_range:
                            print(f"     ➕ Сегмент #{segment_index}: (пауза {pause:.1f}s) \"{next_seg['text'][:80]}\"")
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
                            print(f"     ➕ Сегмент #{segment_index}: (пауза {pause:.1f}s, similarity) \"{next_seg['text'][:80]}\"")
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

        total_words = sum(len(t.split()) for t in texts)
        if in_target_range:
            print(f"\n     📊 Всего собрано: {len(texts)} сегментов, {total_words} слов")
            print(f"     📊 Финальный диапазон: [{seconds_to_hms(start_time)}-{seconds_to_hms(current_end)}]")
        elif debug:
            print(f"    📊 Собрано: {len(texts)} сегментов, {total_words} слов")

        dominant_segment = max(all_segments_in_group, key=lambda s: len(s.get('text', '')))

        if len(all_segments_in_group) > 1:
            print(f"    🎯 Доминирующий: {dominant_segment.get('speaker')} / {dominant_segment.get('raw_speaker_id')} (длина: {len(dominant_segment.get('text', ''))} символов)")

        if in_target_range or debug:
            print(f"    🔗 Вызов join_texts_deduplicated для {len(texts)} текстов...")

        final_text = join_texts_deduplicated(texts, debug=(in_target_range or debug))

        if in_target_range:
            print(f"\n     📝 После join_texts_deduplicated:")
            print(f"        \"{final_text[:100]}...\"")

        if debug or in_target_range:
            print(f"    🧹 Вызов clean_loops ({len(final_text)} символов)...")

        final_text = clean_loops(final_text, debug=(debug or in_target_range))

        if debug or in_target_range:
            print(f"    🧹 Вызов clean_hallucinations_from_text...")

        final_text = clean_hallucinations_from_text(final_text, current_speaker, debug=(debug or in_target_range))

        if in_target_range:
            print(f"\n     ✅ ФИНАЛЬНЫЙ текст ({len(final_text)} символов):")
            print(f"        \"{final_text[:100]}...\"")
            if "достаточно достаточно" in final_text.lower():
                print(f"        ❌ ДУБЛЬ «достаточно Достаточно» ВСЁ ЕЩЁ ЕСТЬ!")
            else:
                print(f"        ✅ Дубль «достаточно Достаточно» УСТРАНЁН!")
        elif debug:
            print(f"    ✅ Очистка завершена, финальный текст: {len(final_text)} символов")

        if final_text:
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
