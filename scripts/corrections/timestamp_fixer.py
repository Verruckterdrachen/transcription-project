#!/usr/bin/env python3
"""
corrections/timestamp_fixer.py - Исправление timestamp

🆕 v17.17: FIX BAG_D_v2 — insert_intermediate_timestamps заменена на
           run_insert из симуляции sim_bugH_fallback_inject_23_07.py (ALL GREEN).
           Логика: ts вставляется ПЕРЕД предложением по w_idx начала предложения
           (не конца), без блока возврата existing_ts, gap_fixer_v2 идёт после.
🆕 v17.16: FIX BAG_G — gap_fixer_v2: break после SKIP когда
           real_t >= gap_end_sec - MIN_NEIGHBOR_GAP (бесконечный цикл).
🆕 v17.15: FIX БАГ A+B — gap_fixer_v2: next-neighbor guard.
           Пропуск inject если расстояние до следующего якоря < 25s.
🆕 v17.14: FIX BAG_D — gap_fixer_v2: пост-проход по готовому тексту сегмента.
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
    Вычисляет реальное время для позиции word_idx.
    Масштабирует позицию из post-clean в pre-clean,
    затем интерполирует внутри sub_segment.
    """
    duration = seg_end - seg_start

    if not sub_segments or total_pre_words == 0 or total_words_post == 0:
        return seg_start + (word_idx / total_words_post) * duration

    scale      = total_pre_words / total_words_post
    scaled_idx = word_idx * scale
    cumulative = 0

    for sub in sub_segments:
        sub_words = max(sub.get('words', 1), 1)
        if scaled_idx <= cumulative + sub_words:
            fraction  = (scaled_idx - cumulative) / sub_words
            real_time = sub['start'] + fraction * (sub['end'] - sub['start'])
            if debug:
                print(f"      🔍 word_idx={word_idx} → scaled={scaled_idx:.1f} → "
                      f"sub [{seconds_to_hms(sub['start'])}-{seconds_to_hms(sub['end'])}] "
                      f"words={sub_words} frac={fraction:.2f} → {seconds_to_hms(real_time)}")
            return real_time
        cumulative += sub_words

    return sub_segments[-1]['end']


# ═══════════════════════════════════════════════════════════════════════════
# 🆕 v17.16: gap_fixer_v2
# ═══════════════════════════════════════════════════════════════════════════

def gap_fixer_v2(seg_text, seg_start, seg_end, sub_segments, total_pre,
                 interval=30.0, threshold=45.0, lookahead=12, debug=True):
    """
    Пост-проход: находит gaps > threshold и вставляет ts по lookahead к точке.
    Идемпотентен: повторный вызов при gaps ≤ threshold → 0 inject.
    """
    MIN_NEIGHBOR_GAP = 25.0

    duration      = seg_end - seg_start
    token_pattern = re.compile(r'(\b\d{2}:\d{2}:\d{2}\b|\S+)')
    raw_tokens    = token_pattern.findall(seg_text)

    tokens      = []
    word_to_tok = []
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

    all_ts_sec = sorted(set(
        int(tok.split(':')[0]) * 3600 + int(tok.split(':')[1]) * 60 + int(tok.split(':')[2])
        for tok, is_t in zip(tokens, tok_is_ts) if is_t
    ))
    anchors     = sorted(set(all_ts_sec + [int(seg_start)]))
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

    inserts = []
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

                est_inj_t    = gap_start_sec + (inject_at / gap_len) * gap_dur
                real_t       = _get_real_time_for_word(
                    abs_word_idx, words_total,
                    seg_start, seg_end,
                    sub_segments, total_pre, debug=False
                )
                delta        = real_t - est_inj_t
                gap_from     = real_t - last_t
                dist_to_next = gap_end_sec - real_t

                if dist_to_next < MIN_NEIGHBOR_GAP:
                    if debug:
                        print(f"       SKIP next-neighbor: "
                              f"dist_to_next={dist_to_next:.0f}s "
                              f"< {MIN_NEIGHBOR_GAP:.0f}s "
                              f"({seconds_to_hms(real_t)} → "
                              f"{seconds_to_hms(gap_end_sec)})")
                    if real_t >= gap_end_sec - MIN_NEIGHBOR_GAP:
                        break
                    i += 1
                    continue

                ctx_lo = max(0, abs_word_idx - 2)
                ctx_hi = min(words_total, abs_word_idx + 3)
                ctx    = ' '.join(tokens[word_to_tok[j]] for j in range(ctx_lo, ctx_hi))
                warn   = "✅" if gap_from <= 35 else ("⚠️" if gap_from <= 45 else "❌")
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
                i      = inject_at + 1
                continue
            i += 1

    if not inserts:
        return seg_text, log

    result = list(tokens)
    for tok_idx, ts_str in sorted(inserts, key=lambda x: -x[0]):
        result.insert(tok_idx + 1, ts_str)

    return ' '.join(result), log


# ═══════════════════════════════════════════════════════════════════════════

def find_existing_timestamps(text):
    """
    Находит все уже вставленные timestamp в тексте.
    Возвращает список {'ts': '00:32:59', 'sec': 1979, 'pos': 42}
    """
    pattern = r'\b(\d{2}:\d{2}:\d{2})\b'
    found   = []
    for m in re.finditer(pattern, text):
        h, mn, s = m.group(1).split(':')
        found.append({
            'ts':  m.group(1),
            'sec': int(h) * 3600 + int(mn) * 60 + int(s),
            'pos': m.start()
        })
    return found


# ═══════════════════════════════════════════════════════════════════════════
# 🆕 v17.17: insert_intermediate_timestamps — логика run_insert из симуляции
# ═══════════════════════════════════════════════════════════════════════════

def insert_intermediate_timestamps(segments, interval=30.0, debug=True):
    """
    🆕 v17.17: Тело функции заменено на run_insert из симуляции ALL GREEN.

    Ключевые свойства (из симуляции):
    - ts вставляется ПЕРЕД предложением, w_idx = начало предложения
    - w_idx += sent_words ПОСЛЕ append(sent) — не меняет позицию инжекта
    - НЕТ блока возврата existing_ts (устранены дубли)
    - gap_fixer_v2 идёт пост-проходом, но при правильных инжектах даёт 0
    - BAG_F guard (scale > 1.8) сохранён
    - sentences < 2 → gap_fixer_v2 напрямую (сохранён)
    """
    if debug:
        print(f"\n🕒 Вставка промежуточных timestamp (interval={interval}s, mode=v17.17)...")

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

        existing_ts   = find_existing_timestamps(text)
        existing_secs = [e['sec'] for e in existing_ts]

        if existing_secs:
            tail = end - max(existing_secs)
            if tail <= interval * 1.5:
                if debug:
                    print(f"  ✅ SKIP (covered): [{seg.get('time','???')}] "
                          f"хвост={tail:.0f}s ≤ {interval * 1.5:.0f}s")
                continue

        clean_text = re.sub(r'\s*\b\d{2}:\d{2}:\d{2}\b\s*', ' ', text).strip()

        sub_segments    = seg.get('sub_segments', [])
        total_pre_words = sum(s.get('words', 0) for s in sub_segments)
        has_real_data   = bool(sub_segments) and total_pre_words > 0

        sentences = re.split(r'([.!?]+)\s+', clean_text)
        sentences = [''.join(sentences[i:i+2]).strip()
                     for i in range(0, len(sentences), 2)]
        sentences = [s for s in sentences if s]

        # sentences < 2 → gap_fixer_v2 напрямую (BAG_D fallback)
        if len(sentences) < 2:
            if debug:
                snippet    = clean_text[:120].replace('\n', ' ')
                punct_count = len(re.findall(r'[.!?]', clean_text))
                print(f"  ⚠️  BAG_D SKIP: блок [{seg.get('time','???')}–{seconds_to_hms(end)}] "
                      f"длит={duration:.0f}s — sentences<2, таймкод НЕ вставлен")
                print(f"      Текст (начало): '{snippet}...'")
                print(f"      Знаков пунктуации [.!?]: {punct_count} | "
                      f"Слов: {len(clean_text.split())} | "
                      f"Символов: {len(clean_text)}")
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

        # BAG_F guard: scale-аномалия после split
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

        # ── ОСНОВНОЙ ЦИКЛ (точная копия run_insert из симуляции) ──────────
        new_parts = []
        w_idx     = 0
        last_t    = max(existing_secs) if existing_secs else start
        all_ts    = list(existing_secs)

        def covered(t):
            return any(abs(x - t) <= 8.0 for x in all_ts)

        for si, sent in enumerate(sentences):
            is_last = si == len(sentences) - 1
            cur_t   = start + (w_idx / words_total) * duration if words_total else start
            gap     = cur_t - last_t

            main_ok     = gap >= interval and not is_last
            fallback_ok = is_last and gap >= interval / 2 and (end - cur_t) > 15.0

            if (main_ok or fallback_ok) and not covered(cur_t):
                real_t = _get_real_time_for_word(
                    w_idx, words_total, start, end,
                    sub_segments, total_pre_words, debug=False
                )
                new_parts.append(f" {seconds_to_hms(real_t)}")
                all_ts.append(real_t)
                last_t = real_t
                injection_count += 1

                if debug:
                    delta  = real_t - cur_t
                    method = "REAL ✅    " if has_real_data else "ESTIMATED ⚠️"
                    tag    = " [FALLBACK]" if fallback_ok else ""
                    print(f"     📌 [{method}]{tag} inject={seconds_to_hms(real_t).strip()} "
                          f"| Δ={delta:+.1f}s "
                          f"| word#{w_idx}/{words_total} "
                          f"| gap={gap:.1f}s")
                    print(f"        ↳ '{sent[:60]}...'")
                    if has_real_data:
                        total_delta += abs(delta)
                        delta_count += 1

            elif (main_ok or fallback_ok) and covered(cur_t):
                skipped_duplicates += 1
                if debug:
                    nearest = min(all_ts, key=lambda t: abs(t - cur_t))
                    print(f"     ⏭️ дубль: {seconds_to_hms(cur_t)} "
                          f"(Δ={abs(nearest - cur_t):.1f}s от {seconds_to_hms(nearest)})")

            new_parts.append(sent)
            w_idx += len(sent.split())
        # ── КОНЕЦ ОСНОВНОГО ЦИКЛА ─────────────────────────────────────────

        seg['text'] = re.sub(r' {2,}', ' ', ' '.join(new_parts)).strip()

        # gap_fixer_v2 пост-проход (при правильных инжектах даст 0)
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
