#!/usr/bin/env python3
"""
corrections/timestamp_fixer.py - Исправление timestamp

🆕 v17.14: FIX BAG_D — gap_fixer_v2: пост-проход по готовому тексту сегмента.
           При gaps > 45s (длинное предложение, нет точки в нужном месте)
           вставляет inject через word-level walk + _get_real_time_for_word().
           Идемпотентен: повторный вызов → 0 inject если gaps уже ≤ 45s.
🆕 v17.11: FIX BAG_F — guard против scale-аномалии после split
🆕 v17.10: Вариант A — точные timestamp через sub_segments из merge_replicas
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
# 🆕 v17.14: gap_fixer_v2 — пост-проход для BAG_D
# ═══════════════════════════════════════════════════════════════════════════

def gap_fixer_v2(seg_text, seg_start, seg_end, sub_segments, total_pre,
                 interval=30.0, threshold=45.0, lookahead=12, debug=True):
    """
    🆕 v17.14: FIX BAG_D — пост-проход по тексту сегмента.

    Проблема: длинные предложения (>30s, нет промежуточных точек) полностью
    поглощают временной интервал — основной проход inject не вставляет.
    Решение: после основного прохода — доп. проход по токенам текста,
    поиск gaps > threshold, word-level walk с lookahead до точки.

    Идемпотентен: повторный вызов при gaps ≤ threshold → 0 inject.

    Args:
        seg_text:     текст сегмента после основного прохода (уже с ts)
        seg_start:    float — начало сегмента (сек)
        seg_end:      float — конец сегмента (сек)
        sub_segments: list[{start,end,words}] из merge_replicas
        total_pre:    int — сумма words из sub_segments
        interval:     порог вставки внутри gap (сек), default 30.0
        threshold:    минимальный gap для обработки (сек), default 45.0
        lookahead:    макс. слов вперёд в поиске конца предложения, default 12
        debug:        вывод отладки

    Returns:
        new_text: str — текст с добавленными ts
        log:      list[dict] — детали каждого inject
    """
    duration = seg_end - seg_start

    # ── Токенизация: слова + ts-метки ─────────────────────────────────────
    token_pattern = re.compile(r'(\b\d{2}:\d{2}:\d{2}\b|\S+)')
    raw_tokens = token_pattern.findall(seg_text)

    tokens      = []
    word_to_tok = []   # word_idx → token_idx
    tok_is_ts   = []

    for tok in raw_tokens:
        is_ts = bool(re.match(r'^\d{2}:\d{2}:\d{2}$', tok))
        tokens.append(tok)
        tok_is_ts.append(is_ts)
        if not is_ts:
            word_to_tok.append(len(tokens) - 1)

    words_total = len(word_to_tok)

    if debug:
        print(f"     🔧 gap_fixer_v2 [{seconds_to_hms(seg_start)}–{seconds_to_hms(seg_end)}] "
              f"dur={duration:.0f}s words={words_total} threshold={threshold}s")

    # ── Находим existing ts → anchors ────────────────────────────────────
    all_ts_sec = sorted(set(
        int(tok.split(':')[0]) * 3600 + int(tok.split(':')[1]) * 60 + int(tok.split(':')[2])
        for tok, is_t in zip(tokens, tok_is_ts) if is_t
    ))
    anchors = sorted(set(all_ts_sec + [int(seg_start)]))

    gaps_to_fix = []
    for i in range(1, len(anchors)):
        gap_sec = anchors[i] - anchors[i - 1]
        if gap_sec > threshold:
            gaps_to_fix.append((anchors[i - 1], anchors[i], gap_sec))
            if debug:
                print(f"       GAP: {seconds_to_hms(anchors[i-1])} → "
                      f"{seconds_to_hms(anchors[i])} = {gap_sec}s ❌")

    if not gaps_to_fix:
        if debug:
            print(f"       gaps > {threshold}s не найдено ✅")
        return seg_text, []

    # ── Обрабатываем каждый gap ───────────────────────────────────────────
    inserts = []  # (token_idx, ts_str) — применяем после всех gaps
    log     = []

    for gap_start_sec, gap_end_sec, gap_dur in gaps_to_fix:
        w_start = round((gap_start_sec - seg_start) / duration * words_total)
        w_end   = round((gap_end_sec   - seg_start) / duration * words_total)
        w_start = max(0, min(w_start, words_total - 1))
        w_end   = max(0, min(w_end,   words_total))
        gap_len = w_end - w_start

        if gap_len <= 0:
            continue

        last_t = float(gap_start_sec)
        i      = 0

        while i < gap_len:
            est_t = gap_start_sec + (i / gap_len) * gap_dur

            if est_t - last_t >= interval:
                inject_at      = i
                found_sent_end = False
                for look in range(min(lookahead, gap_len - i)):
                    w_abs = w_start + i + look
                    if w_abs < words_total:
                        tok = tokens[word_to_tok[w_abs]]
                        if re.search(r'[.!?]$', tok):
                            inject_at      = i + look + 1
                            found_sent_end = True
                            break

                inject_at    = min(inject_at, gap_len - 1)
                abs_word_idx = min(w_start + inject_at, words_total - 1)
                tok_idx      = word_to_tok[abs_word_idx]

                est_inj_t = gap_start_sec + (inject_at / gap_len) * gap_dur
                real_t    = _get_real_time_for_word(
                    abs_word_idx, words_total,
                    seg_start, seg_end,
                    sub_segments, total_pre, debug=False
                )
                delta    = real_t - est_inj_t
                gap_from = real_t - last_t

                ctx_lo  = max(0, abs_word_idx - 2)
                ctx_hi  = min(words_total, abs_word_idx + 3)
                ctx     = ' '.join(tokens[word_to_tok[j]] for j in range(ctx_lo, ctx_hi))

                warn = "✅" if gap_from <= 35 else ("⚠️" if gap_from <= 45 else "❌")
                method = "REAL" if sub_segments else "ESTIMATED"
                if debug:
                    print(f"       inject={seconds_to_hms(real_t)} Δ={delta:+.1f}s "
                          f"gap_from={gap_from:.0f}s {warn} [{method}] "
                          f"sent_end={found_sent_end}")
                    print(f"       «...{ctx}...»")

                inserts.append((tok_idx, seconds_to_hms(real_t)))
                log.append({
                    "real_t":   real_t,
                    "delta":    round(delta, 1),
                    "gap_from": round(gap_from, 1),
                    "ctx":      ctx,
                    "method":   method,
                })
                last_t = real_t
                i = inject_at + 1
                continue
            i += 1

    if not inserts:
        return seg_text, log

    # ── Вставляем ts в токены (справа налево → не сдвигаем индексы) ──────
    result = list(tokens)
    for tok_idx, ts_str in sorted(inserts, key=lambda x: -x[0]):
        result.insert(tok_idx + 1, ts_str)

    return ' '.join(result), log


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
    🆕 v17.14: FIX BAG_D — gap_fixer_v2 пост-проход после основного inject.
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
    🆕 v16.19: КРИТИЧЕСКИЙ FИX - Timestamp injection в блоки >30 сек
    """
    if debug:
        print(f"\n🕒 Вставка промежуточных timestamp (interval={interval}s, mode=v17.14)...")

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
            # 🆕 v17.14: sentences<2 — всё равно запускаем gap_fixer_v2
            seg['text'], _gap_log = gap_fixer_v2(
                text, start, end,
                sub_segments, total_pre_words,
                interval=interval, threshold=45.0,
                lookahead=12, debug=debug
            )
            if _gap_log:
                injection_count += len(_gap_log)
                if debug:
                    print(f"     🔧 gap_fixer_v2 (sentences<2): +{len(_gap_log)} inject(s)")
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
                for si, sub in enumerate(sub_segments):
                    print(f"       sub[{si}]: [{seconds_to_hms(sub['start'])}-"
                          f"{seconds_to_hms(sub['end'])}] words={sub['words']}")
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
                and (end - current_time) > 15.0  # guard: не ставить TS в хвост <15s
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

        # 🆕 v17.14: FIX BAG_D — gap_fixer_v2 пост-проход
        seg['text'], _gap_log = gap_fixer_v2(
            seg['text'], start, end,
            sub_segments, total_pre_words,
            interval=interval, threshold=45.0,
            lookahead=12, debug=debug
        )
        if _gap_log:
            injection_count += len(_gap_log)
            if debug:
                print(f"     🔧 gap_fixer_v2: +{len(_gap_log)} inject(s)")

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
