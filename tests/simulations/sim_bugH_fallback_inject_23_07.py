#!/usr/bin/env python3
"""
tests/simulations/sim_bugH_fallback_inject_23_07.py
═══════════════════════════════════════════════════════════════════
Симуляция insert_intermediate_timestamps (v17.14) для блока
00:23:07 Исаев — «Тяжелые танки Тигр».

Реальный TXT из лога:
  00:23:07 Исаев: [345 слов, заканчивается перед 00:26:18]
  Финальный таймкод в тексте: 00:26:18

Задача: выяснить сколько inject-ов вставит функция и где.
Проверяем два сценария:
  A. Блок 191s (полный merge 00:23:07–00:26:18) → ожидаем 5 inject-ов
  B. Блок 44s  (частичный, как в логе word#46/71) → ожидаем 1 FALLBACK inject

GREEN criteria (сценарий A):
  ✅ inject_count >= 5
  ✅ первый inject ≤ 00:23:50 (в пределах первых 43s)
  ✅ все gaps между inject-ами ≤ 45s
  ✅ gap_fixer_v2 не добавил лишних (gaps > 45s не найдено)
  ✅ FALLBACK inject = последний

GREEN criteria (сценарий B):
  ✅ inject_count == 1
  ✅ inject mode == FALLBACK
  ✅ inject time ≈ 00:23:37 (±3s)
"""

import re
import sys


# ─────────────────────────────────────────────────────────────────────────────
# УТИЛИТЫ
# ─────────────────────────────────────────────────────────────────────────────

def seconds_to_hms(s):
    h = int(s // 3600); m = int((s % 3600) // 60); sec = int(s % 60)
    return f"{h:02d}:{m:02d}:{sec:02d}"

def hms_to_sec(hms):
    h, m, s = hms.split(':')
    return int(h) * 3600 + int(m) * 60 + int(s)


# ─────────────────────────────────────────────────────────────────────────────
# ДАННЫЕ
# ─────────────────────────────────────────────────────────────────────────────

FULL_TEXT = (
    "Тяжелые танки «Тигр» были новинкой, которые всю вторую половину войны стали "
    "неприятным сюрпризом для союзников, причем и на Западном фронте, и на "
    "Советско-Германском фронте. были такой квинтэссенцией германского танкостроения. "
    "Это мощное орудие 88 мм, которое поражало любые танки союзников того периода, "
    "на любых мыслимых дистанциях боя. "
    "Это толстая броня до 100 мм, лоб, который был практически непоражаем для "
    "артиллерии противотанковой и дивизионной, причем как наши, так и союзников в тот период. "
    "И хуже всего, что о танках «Тигр» мы ничего не знали. "
    "Они впервые были применены осенью 42-го года, но они были применены против "
    "окруженных войск, которые пытались пробиться на выручку к Ленинграду. "
    "И, естественно, опыт окруженцев он не был воспринят и проанализирован. "
    "Просто по той банальной причине, что немецкие танки не были захвачены в виде трофеев. "
    "То есть, о них были только некие мутные рассказы. "
    "И, соответственно, к январю 43-го года представление Красной Армии о новой "
    "бронетехнике противника было практически нулевым. "
    "Это был крайне неприятный сюрприз. "
    "И, хотя танков было немного, у немцев был только 502-й танковый батальон "
    "смешанного состава, которым было всего 6, по другим данным, 7 боеготовых тигров "
    "к началу операции «Искра». "
    "Даже это небольшое количество могло сыграть серьезную роль и оказать большое "
    "влияние на ход операции в случае удачной контратаки. "
    "Конечно, лесисто-болотистая местность не сильно благоприятствовала тиграм, но, "
    "строго говоря, в трескучии мороза когда почва была надежно скована 15-ти градусным "
    "морозом, тигры вполне могли проехать и, как показала практика, вполне были способны "
    "перемещаться в бутылочном горле соответственно, стрелять по советским танкам, советской пехоте. "
    "Это был крайне опасный противник. "
    "И, опять же, хуже всего было то, что о нем просто не знали. "
    "И наличие этого фактора, оно, конечно, было за немцев. "
    "Это был тот фактор, который благоприятствовал немцам в удержании бутылочного города. "
    "То есть, они их не обладали сведениями. "
    "Да, как раз. "
    "тяжелые танки тигров первый раз захватили именно под Ленинградом, их изучили, "
    "и только по итогам изучения были приняты меры, то есть, была принята, во-первых, "
    "тактическая подготовка, во-вторых, стали готовить новые танки и противотанковые пушки, "
    "которые предполагалось, что успеют в Курской дуге, но даже их полностью парировать "
    "этот фактор не смогли."
)

SHORT_TEXT = (
    "Тяжелые танки «Тигр» были новинкой, которые всю вторую половину 1942 года "
    "были такой квинтэссенцией германского танкостроения. "
    "Это мощное орудие 88 мм, которое поражало любые танки союзников. "
    "Это толстая броня до 100 мм, лоб, который был практически непоражаем для "
    "советских орудий того времени."
)

# Сценарий A: полный merge 00:23:07–00:26:18
SEG_A_START = hms_to_sec("00:23:07")
SEG_A_END   = hms_to_sec("00:26:18")
N_SUBS_A    = 14
sub_dur_a   = (SEG_A_END - SEG_A_START) / N_SUBS_A
words_a     = len(FULL_TEXT.split())    # 345
sub_w_a     = words_a // N_SUBS_A
SUB_SEGS_A  = [
    {"start": SEG_A_START + i * sub_dur_a,
     "end":   SEG_A_START + (i + 1) * sub_dur_a,
     "words": sub_w_a + (1 if i < words_a % N_SUBS_A else 0)}
    for i in range(N_SUBS_A)
]
TOTAL_PRE_A = sum(s["words"] for s in SUB_SEGS_A)

# Сценарий B: частичный блок 44s (как в реальном логе word#46/71)
SEG_B_START = hms_to_sec("00:23:07")
SEG_B_END   = hms_to_sec("00:23:51")
SUB_SEGS_B  = [
    {"start": SEG_B_START,         "end": SEG_B_START + 13.6, "words": 22},
    {"start": SEG_B_START + 13.6,  "end": SEG_B_START + 34.5, "words": 28},
    {"start": SEG_B_START + 34.5,  "end": SEG_B_END,           "words": 21},
]
TOTAL_PRE_B = sum(s["words"] for s in SUB_SEGS_B)  # 71


# ─────────────────────────────────────────────────────────────────────────────
# ФУНКЦИИ (точные копии из timestamp_fixer.py v17.16)
# ─────────────────────────────────────────────────────────────────────────────

def _get_real_time_for_word(word_idx, total_words_post, seg_start, seg_end,
                             sub_segments, total_pre_words):
    duration = seg_end - seg_start
    if not sub_segments or total_pre_words == 0 or total_words_post == 0:
        return seg_start + (word_idx / total_words_post) * duration
    scale = total_pre_words / total_words_post
    scaled_idx = word_idx * scale
    cumulative = 0
    for sub in sub_segments:
        sub_words = max(sub.get("words", 1), 1)
        if scaled_idx <= cumulative + sub_words:
            fraction = (scaled_idx - cumulative) / sub_words
            return sub["start"] + fraction * (sub["end"] - sub["start"])
        cumulative += sub_words
    return sub_segments[-1]["end"]


def find_existing_timestamps(text):
    found = []
    for m in re.finditer(r'\b(\d{2}:\d{2}:\d{2})\b', text):
        h, mn, s = m.group(1).split(':')
        found.append({"ts": m.group(1), "sec": int(h)*3600 + int(mn)*60 + int(s)})
    return found


def gap_fixer_v2(seg_text, seg_start, seg_end, sub_segments, total_pre,
                 interval=30.0, threshold=45.0, lookahead=12):
    MIN_NEIGHBOR_GAP = 25.0
    duration = seg_end - seg_start
    token_pattern = re.compile(r'(\b\d{2}:\d{2}:\d{2}\b|\S+)')
    tokens = []; word_to_tok = []; tok_is_ts = []
    for tok in token_pattern.findall(seg_text):
        is_ts = bool(re.match(r'^\d{2}:\d{2}:\d{2}$', tok))
        tokens.append(tok); tok_is_ts.append(is_ts)
        if not is_ts: word_to_tok.append(len(tokens) - 1)
    words_total = len(word_to_tok)
    all_ts_sec = sorted(set(
        int(t.split(':')[0])*3600 + int(t.split(':')[1])*60 + int(t.split(':')[2])
        for t, f in zip(tokens, tok_is_ts) if f
    ))
    anchors = sorted(set(all_ts_sec + [int(seg_start)]))
    gaps_to_fix = [(anchors[i-1], anchors[i], anchors[i]-anchors[i-1])
                   for i in range(1, len(anchors)) if anchors[i]-anchors[i-1] > threshold]
    if not gaps_to_fix:
        return seg_text, []
    inserts = []; log = []
    for gap_start_sec, gap_end_sec, gap_dur in gaps_to_fix:
        w_start = max(0, min(round((gap_start_sec-seg_start)/duration*words_total), words_total-1))
        w_end   = max(0, min(round((gap_end_sec  -seg_start)/duration*words_total), words_total))
        gap_len = w_end - w_start
        if gap_len <= 0: continue
        last_t = float(gap_start_sec); i = 0
        while i < gap_len:
            if gap_start_sec + (i/gap_len)*gap_dur - last_t >= interval:
                inject_at = i; found_se = False
                for look in range(min(lookahead, gap_len-i)):
                    w = w_start+i+look
                    if w < words_total and re.search(r'[.!?]$', tokens[word_to_tok[w]]):
                        inject_at = i+look+1; found_se = True; break
                inject_at    = min(inject_at, gap_len-1)
                abs_w        = min(w_start+inject_at, words_total-1)
                tok_idx      = word_to_tok[abs_w]
                est_inj_t    = gap_start_sec + (inject_at/gap_len)*gap_dur
                real_t = _get_real_time_for_word(abs_w, words_total, seg_start, seg_end,
                                                  sub_segments, total_pre)
                if gap_end_sec - real_t < MIN_NEIGHBOR_GAP:
                    if real_t >= gap_end_sec - MIN_NEIGHBOR_GAP: break
                    i += 1; continue
                inserts.append((tok_idx, seconds_to_hms(real_t)))
                log.append({"real_t": real_t, "delta": round(real_t-est_inj_t, 1)})
                last_t = real_t; i = inject_at+1; continue
            i += 1
    if not inserts: return seg_text, log
    result = list(tokens)
    for tok_idx, ts_str in sorted(inserts, key=lambda x: -x[0]):
        result.insert(tok_idx+1, ts_str)
    return ' '.join(result), log


def run_insert(text, seg_start, seg_end, sub_segs, total_pre, interval=30.0):
    duration = seg_end - seg_start
    if duration <= interval:
        return text, [], []
    existing_ts   = find_existing_timestamps(text)
    existing_secs = [e["sec"] for e in existing_ts]
    if existing_secs and (seg_end - max(existing_secs)) <= interval * 1.5:
        return text, [], []
    clean  = re.sub(r'\s*\b\d{2}:\d{2}:\d{2}\b\s*', ' ', text).strip()
    sub_s  = sub_segs[:]; t_pre = total_pre; has_real = bool(sub_s) and t_pre > 0
    words_total = len(clean.split())
    sents = re.split(r'([.!?]+)\s+', clean)
    sents = [''.join(sents[i:i+2]).strip() for i in range(0, len(sents), 2)]
    sents = [s for s in sents if s]
    if has_real and words_total > 0 and t_pre/words_total > 1.8:
        sub_s = []; t_pre = 0; has_real = False
    new_parts=[]; w_idx=0
    last_t = max(existing_secs) if existing_secs else seg_start
    all_ts = list(existing_secs); inject_log=[]
    def covered(t): return any(abs(x-t)<=8.0 for x in all_ts)
    for si, sent in enumerate(sents):
        is_last = si == len(sents)-1
        cur_t   = seg_start + (w_idx/words_total)*duration if words_total else seg_start
        gap     = cur_t - last_t
        main_ok     = gap >= interval and not is_last
        fallback_ok = is_last and gap >= interval/2 and (seg_end-cur_t) > 15.0
        if (main_ok or fallback_ok) and not covered(cur_t):
            real_t = _get_real_time_for_word(w_idx, words_total, seg_start, seg_end, sub_s, t_pre)
            new_parts.append(f" {seconds_to_hms(real_t)} ")
            all_ts.append(real_t); last_t = real_t
            inject_log.append({"mode": "FALLBACK" if fallback_ok else "MAIN",
                                "real_t": real_t, "word_idx": w_idx,
                                "words_total": words_total, "gap": round(gap,1),
                                "sent": sent[:70]})
        new_parts.append(sent); w_idx += len(sent.split())
    result = ' '.join(new_parts)
    result, gap_log = gap_fixer_v2(result, seg_start, seg_end, sub_s, t_pre,
                                    interval=interval, threshold=45.0)
    return result, inject_log, gap_log


# ─────────────────────────────────────────────────────────────────────────────
# ТЕСТЫ
# ─────────────────────────────────────────────────────────────────────────────

def check(condition, name, pass_list, fail_list):
    (pass_list if condition else fail_list).append(name)
    print(f"  {'✅' if condition else '❌'} {name}")
    return condition


def test_scenario_a():
    """Сценарий A: полный блок 191s → ≥5 inject-ов, все gaps ≤ 45s"""
    print("\n" + "="*65)
    print("СЦЕНАРИЙ A: полный merge 00:23:07–00:26:18 (191s, 345 слов)")
    print("="*65)
    result, inject_log, gap_log = run_insert(
        FULL_TEXT, SEG_A_START, SEG_A_END, SUB_SEGS_A, TOTAL_PRE_A)

    print(f"\nTXT:")
    print(f"  00:23:07 Исаев: {result[:200]}...\n")
    print(f"Inject-точки:")
    for inj in inject_log:
        warn = "✅" if inj['gap']<=35 else ("⚠️" if inj['gap']<=45 else "❌")
        print(f"  {seconds_to_hms(inj['real_t'])} [{inj['mode']}] gap={inj['gap']}s {warn}")
        print(f"    ↳ «{inj['sent'][:60]}»")

    all_ts = sorted([i["real_t"] for i in inject_log] + [g["real_t"] for g in gap_log])
    anchors = [SEG_A_START] + all_ts + [SEG_A_END]
    gaps = [anchors[i]-anchors[i-1] for i in range(1, len(anchors))]
    max_gap = max(gaps) if gaps else 0
    print(f"\nGaps: {[f'{seconds_to_hms(anchors[i])}→{g:.0f}s' for i,g in enumerate(gaps)]}")

    PASS=[]; FAIL=[]
    n_total = len(inject_log) + len(gap_log)
    check(n_total >= 5, f"inject_total >= 5 (got {n_total})", PASS, FAIL)
    first_t = inject_log[0]["real_t"] if inject_log else 9999
    check(first_t <= hms_to_sec("00:23:50"),
          f"first_inject ≤ 00:23:50 (got {seconds_to_hms(first_t)})", PASS, FAIL)
    check(max_gap <= 45, f"max_gap ≤ 45s (got {max_gap:.0f}s)", PASS, FAIL)
    check(len(gap_log) == 0, f"gap_fixer_v2 == 0 (got {len(gap_log)})", PASS, FAIL)
    last_mode = inject_log[-1]["mode"] if inject_log else "?"
    check(last_mode == "FALLBACK", f"last inject == FALLBACK (got {last_mode})", PASS, FAIL)

    print(f"\n  {'✅ ALL GREEN' if not FAIL else '❌ FAIL: '+str(FAIL)}")
    return len(FAIL) == 0


def test_scenario_b():
    """Сценарий B: частичный блок 44s → 1 FALLBACK inject ≈ 00:23:37"""
    print("\n" + "="*65)
    print("СЦЕНАРИЙ B: частичный блок 00:23:07–00:23:51 (44s)")
    print("="*65)
    result, inject_log, gap_log = run_insert(
        SHORT_TEXT, SEG_B_START, SEG_B_END, SUB_SEGS_B, TOTAL_PRE_B)

    print(f"\nTXT: {result}")
    print(f"\nInject-точки:")
    for inj in inject_log:
        print(f"  {seconds_to_hms(inj['real_t'])} [{inj['mode']}] gap={inj['gap']}s")
        print(f"    ↳ «{inj['sent'][:60]}»")

    PASS=[]; FAIL=[]
    n = len(inject_log)
    check(n == 1, f"inject_count == 1 (got {n})", PASS, FAIL)
    if inject_log:
        rt = inject_log[0]["real_t"]
        target = hms_to_sec("00:23:37")
        check(abs(rt-target) <= 3,
              f"inject_time ≈ 00:23:37 ±3s (got {seconds_to_hms(rt)}, Δ={rt-target:+.1f}s)",
              PASS, FAIL)
        check(inject_log[0]["mode"] == "FALLBACK",
              f"inject_mode == FALLBACK", PASS, FAIL)
    check(len(gap_log) == 0, f"gap_fixer_v2 == 0 (got {len(gap_log)})", PASS, FAIL)

    print(f"\n  {'✅ ALL GREEN' if not FAIL else '❌ FAIL: '+str(FAIL)}")
    return len(FAIL) == 0


if __name__ == "__main__":
    ok_a = test_scenario_a()
    ok_b = test_scenario_b()
    print("\n" + "="*65)
    if ok_a and ok_b:
        print("✅ ОБА СЦЕНАРИЯ GREEN")
    else:
        print(f"❌ ИТОГ: A={'GREEN' if ok_a else 'FAIL'}, B={'GREEN' if ok_b else 'FAIL'}")
    sys.exit(0 if (ok_a and ok_b) else 1)
