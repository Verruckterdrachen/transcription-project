#!/usr/bin/env python3
"""
corrections/timestamp_fixer.py - Исправление timestamp

🆕 v17.11: FIX BAG_F — guard против scale-аномалии после split
           split_mixed_speaker_segments() наследует sub_segments от родителя.
           У дочернего сегмента scale = total_pre_words/words_post >> 1.8
           → _get_real_time_for_word() выходит за пределы seg.end → инверсия.
           FIX: if scale > 1.8 → fallback ESTIMATED (линейная интерполяция)
🆕 v17.10: Вариант A — точные timestamp через sub_segments из merge_replicas
           Вместо word-proportion по всему блоку используем реальные границы
           оригинальных Whisper-сегментов. Debug: estimated vs real vs Δ.
🆕 v16.28: FIX БАГ #3 - Потеря последнего предложения
🆕 v16.22: FIX БАГ #1 - Дублирующиеся timestamp
🆕 v16.22: FIX БАГ #2 - Timestamp назад
🆕 v16.19: КРИТИЧЕСКИЙ FIX - Timestamp injection в блоки >30 сек
"""

import re
from core.utils import seconds_to_hms


# ═══════════════════════════════════════════════════════════════════════════
# 🆕 v17.10: Helper — реальное время через sub_segments
# ═══════════════════════════════════════════════════════════════════════════

def _get_real_time_for_word(word_idx, total_words_post, seg_start, seg_end,
                             sub_segments, total_pre_words, debug=False):
    """
    🆕 v17.10: Вычисляет реальное время для позиции word_idx.

    Масштабирует позицию из post-clean пространства в pre-clean,
    затем ищет нужный sub_segment и интерполирует внутри него.

    Args:
        word_idx:           Позиция первого слова предложения (post-clean)
        total_words_post:   Всего слов в merged тексте (post-clean)
        seg_start:          seg['start'] — fallback начало
        seg_end:            seg['end']   — fallback конец
        sub_segments:       [{'start', 'end', 'words'}, ...] из merge_replicas
        total_pre_words:    Сумма words из sub_segments (pre-clean)
        debug:              Показывать детальный debug lookup

    Returns:
        float: Время в секундах
    """
    duration = seg_end - seg_start

    # Fallback: нет sub_segments → старая линейная интерполяция
    if not sub_segments or total_pre_words == 0 or total_words_post == 0:
        return seg_start + (word_idx / total_words_post) * duration

    # Масштаб: post-clean → pre-clean
    scale = total_pre_words / total_words_post
    scaled_idx = word_idx * scale

    cumulative = 0
    for sub in sub_segments:
        sub_words = max(sub.get('words', 1), 1)
        if scaled_idx <= cumulative + sub_words:
            fraction = (scaled_idx - cumulative) / sub_words
            real_time = sub['start'] + fraction * (sub['end'] - sub['start'])
            if debug:
                print(f"      🔍 word_idx={word_idx} → scaled={scaled_idx:.1f} → "
                      f"sub [{seconds_to_hms(sub['start'])}-{seconds_to_hms(sub['end'])}] "
                      f"words={sub_words} frac={fraction:.2f} → {seconds_to_hms(real_time)}")
            return real_time
        cumulative += sub_words

    return sub_segments[-1]['end']


# ═══════════════════════════════════════════════════════════════════════════

def find_existing_timestamps(text):
    """
    🆕 v17.13: Находит все уже вставленные timestamp в тексте.
    Возвращает список {'ts': '00:32:59', 'sec': 1979, 'pos': 42}
    """
    pattern = r'\b(\d{2}:\d{2}:\d{2})\b'
    found = []
    for m in re.finditer(pattern, text):
        h, mn, s = m.group(1).split(':')
        found.append({
            'ts':  m.group(1),
            'sec': int(h) * 3600 + int(mn) * 60 + int(s),
            'pos': m.start()
        })
    return found

# ═══════════════════════════════════════════════════════════════════════════

def insert_intermediate_timestamps(segments, interval=30.0, debug=True):
    """
    🆕 v17.13: FIX БАГ — повторный вызов после auto_merge.
               SKIP блоков у которых хвост (end - last_existing_ts) ≤ interval*1.5.
               Трогаем только блоки с реально необработанным хвостом > 45s.
               existing ts в тексте не пересчитываем и не восстанавливаем.
    🆕 v17.12: FIX БАГ — fallback inject перед последним предложением
    🆕 v17.11: FIX BAG_F — guard против scale-аномалии после split
    🆕 v17.10: Вариант A — точные timestamp через sub_segments из merge_replicas
    🆕 v16.28: FIX БАГ #3 - Потеря последнего предложения
    🆕 v16.22: FIX БАГ #1 - Дублирующиеся timestamp
    🆕 v16.22: FIX БАГ #2 - Timestamp назад
    🆕 v16.19: КРИТИЧЕСКИЙ FIX - Timestamp injection в блоки >30 сек
    """
    if debug:
        print(f"\n🕒 Вставка промежуточных timestamp (interval={interval}s, mode=v17.13)...")

    injection_count    = 0
    skipped_duplicates = 0
    total_delta        = 0.0
    delta_count        = 0

    for seg_idx, seg in enumerate(segments):
        start    = seg.get('start', 0)
        end      = seg.get('end',   0)
        duration = end - start

        if duration <= interval:
            if debug and duration > 25:
                print(f"  ℹ️  SHORT SKIP: [{seg.get('time','???')}] длит={duration:.0f}s ≤ {interval}s")
            continue

        text = seg.get('text', '')

        # 🆕 v17.13: Находим existing timestamp от предыдущего прохода
        existing_ts   = find_existing_timestamps(text)
        existing_secs = [e['sec'] for e in existing_ts]

        # 🆕 v17.13: SKIP если хвост уже покрыт — не трогаем блок вообще
        if existing_secs:
            tail = end - max(existing_secs)
            if tail <= interval * 1.5:
                if debug:
                    print(f"  ✅ SKIP (covered): [{seg.get('time','???')}] "
                          f"хвост={tail:.0f}s ≤ {interval * 1.5:.0f}s")
                continue

        # Для подсчёта слов и split — убираем existing ts из текста
        clean_text = re.sub(r'\s*\b\d{2}:\d{2}:\d{2}\b\s*', ' ', text).strip()

        sub_segments    = seg.get('sub_segments', [])
        total_pre_words = sum(s.get('words', 0) for s in sub_segments)
        has_real_data   = bool(sub_segments) and total_pre_words > 0

        sentences = re.split(r'([.!?]+)\s+', clean_text)
        sentences = [''.join(sentences[i:i+2]).strip()
                     for i in range(0, len(sentences), 2)]
        sentences = [s for s in sentences if s]

        if len(sentences) < 2:
            if debug:
                snippet = clean_text[:120].replace('\n', ' ')
                print(f"  ⚠️  BAG_D SKIP: блок [{seg.get('time','???')}–{seconds_to_hms(end)}] "
                      f"длит={duration:.0f}s — sentences<2, таймкод НЕ вставлен")
                print(f"      Текст (начало): '{snippet}...'")
                punct_count = len(re.findall(r'[.!?]', clean_text))
                print(f"      Знаков пунктуации [.!?]: {punct_count} | "
                      f"Слов: {len(clean_text.split())} | "
                      f"Символов: {len(clean_text)}")
            continue

        words_total = len(clean_text.split())

        _SCALE_ANOMALY_THRESHOLD = 1.8
        if has_real_data and words_total > 0:
            _scale = total_pre_words / words_total
            if _scale > _SCALE_ANOMALY_THRESHOLD:
                if debug:
                    print(f"  ⚠️  BAG_F GUARD [{seg.get('time', '???')}] "
                          f"{seg.get('speaker', '?')}: "
                          f"scale={_scale:.3f} > {_SCALE_ANOMALY_THRESHOLD} "
                          f"(pre={total_pre_words} / post={words_total}) "
                          f"— sub_segments от родителя после split, fallback ESTIMATED")
                sub_segments    = []
                total_pre_words = 0
                has_real_data   = False

        if debug:
            mode = "🎯 REAL (sub_segments)" if has_real_data else "📐 ESTIMATED (word proportion)"
            print(f"\n  ── Сегмент [{seg.get('time','???')}] {seg.get('speaker')} ──")
            print(f"     длит={duration:.1f}s | слов(post)={words_total} | режим={mode}")
            if has_real_data:
                print(f"     sub_segments: {len(sub_segments)} шт | "
                      f"words(pre-clean)={total_pre_words} | "
                      f"scale={total_pre_words/words_total:.3f}")
                for si, s in enumerate(sub_segments):
                    print(f"       sub[{si}]: [{seconds_to_hms(s['start'])}-"
                          f"{seconds_to_hms(s['end'])}] words={s['words']}")
            if existing_secs:
                print(f"     existing ts: {[e['ts'] for e in existing_ts]} "
                      f"(повторный проход, хвост > {interval * 1.5:.0f}s)")

        new_text_parts   = []
        current_word_idx = 0

        # 🆕 v17.13: стартуем от последнего existing ts
        last_inject_time  = max(existing_secs) if existing_secs else start
        all_inject_times  = list(existing_secs)
        injected_this_seg = len(existing_secs) > 0

        def _already_covered(t, window=8.0):
            return any(abs(ts - t) <= window for ts in all_inject_times)

        for sent_idx, sent in enumerate(sentences):
            sent_words = len(sent.split())
            is_last    = (sent_idx == len(sentences) - 1)

            current_time   = (start + (current_word_idx / words_total) * duration
                               if words_total > 0 else start)
            gap_since_last = current_time - last_inject_time

            should_inject_main = (
                gap_since_last >= interval
                and not is_last
            )
            # Fallback: последнее предложение, хвост > interval/2
            should_inject_fallback = (
                is_last
                and gap_since_last >= interval / 2
            )

            if should_inject_main or should_inject_fallback:
                if _already_covered(current_time):
                    if debug:
                        nearest = min(all_inject_times, key=lambda t: abs(t - current_time))
                        print(f"     ⏭️ дубль: {seconds_to_hms(current_time)} "
                              f"(Δ={abs(nearest - current_time):.1f}s от {seconds_to_hms(nearest)})")
                    skipped_duplicates += 1
                else:
                    real_time = _get_real_time_for_word(
                        current_word_idx, words_total, start, end,
                        sub_segments, total_pre_words, debug=False
                    )
                    timestamp_str = f" {seconds_to_hms(real_time)} "
                    new_text_parts.append(timestamp_str)

                    all_inject_times.append(real_time)
                    last_inject_time  = real_time
                    injected_this_seg = True
                    injection_count  += 1

                    if debug:
                        delta  = real_time - current_time
                        method = "REAL ✅    " if has_real_data else "ESTIMATED ⚠️"
                        tag    = " [FALLBACK]" if should_inject_fallback else ""
                        print(f"     📌 [{method}]{tag} inject={seconds_to_hms(real_time).strip()} "
                              f"| Δ={delta:+.1f}s "
                              f"| word#{current_word_idx}/{words_total} "
                              f"| gap={gap_since_last:.1f}s")
                        print(f"        ↳ '{sent[:60]}...'")
                        if has_real_data:
                            total_delta += abs(delta)
                            delta_count += 1

            new_text_parts.append(sent)
            current_word_idx += sent_words

        # 🆕 v17.13: existing ts в хвосте (после всех предложений) — сохраняем
        final_word_time = (start + (current_word_idx / words_total) * duration
                           if words_total > 0 else end)
        for ets in sorted(existing_ts, key=lambda x: x['sec']):
            if ets['sec'] > final_word_time:
                new_text_parts.append(f" {ets['ts']} ")

        seg['text'] = ' '.join(new_text_parts)

    if debug:
        print(f"\n{'─'*60}")
        print(f"✅ Вставлено timestamp : {injection_count}")
        if skipped_duplicates:
            print(f"⏭️ Пропущено дублей   : {skipped_duplicates}")
        if delta_count > 0:
            print(f"📊 Средний |Δ| (REAL) : {total_delta/delta_count:.1f}s "
                  f"по {delta_count} инжекциям")
        if injection_count == 0 and skipped_duplicates == 0:
            print(f"✅ Блоков >30s не найдено")

    return segments

# ═══════════════════════════════════════════════════════════════════════════

def correct_timestamp_drift(segments, debug=True):
    """
    🆕 v16.22: FIX БАГ #2 - Timestamp назад
    🆕 v16.19: Исправляет сдвиг timestamp после gap filling

    **ПРОБЛЕМА (БАГ #2):**
    Функция сдвигала timestamp НАЗАД:
    - prev_seg.end = 183.5 (00:03:03)
    - current_seg.start = 186.2 (00:03:06)
    - new_start = prev_end = 183.5  ← МЕНЬШЕ чем 186.2!
    - Результат: 00:03:06 → 00:03:03 (НАЗАД!)

    **FIX v16.22:**
    Проверяем монотонность: new_start ДОЛЖЕН быть >= old_start
    """
    if debug:
        print(f"\n🔧 Исправление сдвига timestamp после gap filling...")

    corrections      = 0
    skipped_backward = 0

    for i in range(1, len(segments)):
        prev_seg    = segments[i - 1]
        current_seg = segments[i]

        prev_end      = prev_seg.get('end',   0)
        current_start = current_seg.get('start', 0)

        gap = current_start - prev_end

        if -10.0 <= gap <= 0.5:
            old_start = current_start
            new_start = prev_end

            # 🆕 v16.22: FIX БАГ #2 — не двигаем назад
            if new_start >= old_start:
                current_seg['start'] = new_start
                current_seg['time']  = seconds_to_hms(new_start)

                if debug and abs(old_start - new_start) > 1.0:
                    print(f"  ⏱️ {seconds_to_hms(old_start)} → "
                          f"{seconds_to_hms(new_start)} "
                          f"(сдвиг {new_start - old_start:+.1f}s)")

                corrections += 1
            else:
                if debug:
                    print(f"  ⏭️ ПРОПУСКАЕМ: {seconds_to_hms(old_start)} → "
                          f"{seconds_to_hms(new_start)} "
                          f"(сдвиг назад {new_start - old_start:.1f}s)")
                skipped_backward += 1

    if debug:
        if corrections:
            print(f"✅ Исправлено timestamp: {corrections}")
        if skipped_backward:
            print(f"⏭️ Пропущено (назад): {skipped_backward}")
        if corrections == 0 and skipped_backward == 0:
            print(f"✅ Сдвигов не найдено")

    return segments
