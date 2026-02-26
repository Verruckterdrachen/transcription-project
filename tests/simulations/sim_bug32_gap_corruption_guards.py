#!/usr/bin/env python3
"""
sim_bug32_gap_corruption_guards.py

Симуляция BAG_C_3 (00:34:57 патрули) и BAG_C_5 (00:21:28 артиллерия).
ROOT CAUSE: GAP_FILLED сегменты содержат Whisper-повтор соседних сегментов.
Guards A+B+C в merge_replicas() должны их отфильтровать.

Запуск: python tests/simulations/sim_bug32_gap_corruption_guards.py
Ожидание: 4/4 GREEN
"""

from difflib import SequenceMatcher
import re
import sys

# ──────────────────────────────────────────────────────────────────
# Заглушки для импортов пайплайна
# ──────────────────────────────────────────────────────────────────
def join_texts_deduplicated(texts, debug=False):
    if not texts: return ""
    result = texts[0]
    for i in range(1, len(texts)):
        rw = result.split(); cw = texts[i].split()
        ol = 0
        for k in range(min(5, len(rw), len(cw)), 0, -1):
            if [w.lower() for w in rw[-k:]] == [w.lower() for w in cw[:k]]:
                ol = k; break
        result = result + ' ' + (' '.join(cw[ol:]) if ol else texts[i])
    return result.strip()

RUSSIAN_STOP_WORDS = {'был','была','было','были','в','на','с','к','по','из','за','до',
    'и','а','но','или','что','как','если','когда','где','это','этот','эта','эти',
    'вот','же','не','да','то','так','уже','еще','ещё','он','она','они','мы','вы'}
def _count_meaningful(phrase):
    clean = re.sub(r'[.,!?;:«»"\'()\[\]]', '', phrase.lower())
    return sum(1 for w in clean.split() if w not in RUSSIAN_STOP_WORDS)

def clean_loops(text, debug=False):
    LOOP_WINDOW = 30
    words = text.split(); seen = []; cleaned = []; i = 0
    while i < len(words):
        phrase = ' '.join(words[i:i+3])
        phrase_lower = phrase.lower()
        if _count_meaningful(phrase_lower) < 2:
            cleaned.extend(words[i:i+3]); i += 3; continue
        is_loop = False
        for prev in seen:
            if SequenceMatcher(None, phrase_lower, prev).ratio() >= 0.75:
                is_loop = True; break
        if is_loop:
            last = cleaned[-1].lower().rstrip('.,!?«»') if cleaned else ''
            if last in {'на','в','во','с','со','к','по','из','за','до','при','через','о','об','у','для','от','под','над'}:
                seen.append(phrase_lower)
                if len(seen) > LOOP_WINDOW: seen.pop(0)
                cleaned.extend(words[i:i+3]); i += 3; continue
            i += 1; continue
        seen.append(phrase_lower)
        if len(seen) > LOOP_WINDOW: seen.pop(0)
        cleaned.extend(words[i:i+3]); i += 3
    return re.sub(r'([.,!?])\1{2,}', r'\1', ' '.join(cleaned)).strip()

def clean_hallucinations_from_text(text, speaker, debug=False):
    return text

# ──────────────────────────────────────────────────────────────────
# GUARDS — то, что мы добавляем в merge_replicas()
# ──────────────────────────────────────────────────────────────────
GAP_SIM_THRESHOLD = 0.65
GAP_LOOKAHEAD     = 5
GAP_WINDOW_WORDS  = 4

def _is_gap_corrupted(gap_seg, segments, j):
    """GUARD C: GAP_FILLED содержит контент следующих сегментов."""
    gap_words = gap_seg['text'].lower().split()
    lookahead = segments[j+1 : j+1+GAP_LOOKAHEAD]
    for la in lookahead:
        la_words = re.sub(r'[.,!?]','', la['text'].lower()).split()
        k_max = min(len(la_words), len(gap_words), 8)
        for k in range(max(GAP_WINDOW_WORDS, k_max), GAP_WINDOW_WORDS - 1, -1):
            for si in range(len(gap_words) - k + 1):
                window = gap_words[si:si+k]
                sim = SequenceMatcher(None,' '.join(window),' '.join(la_words[:k])).ratio()
                if sim >= GAP_SIM_THRESHOLD:
                    return True
    return False


def merge_replicas_with_guards(segments, debug=False):
    """merge_replicas с Guards A+B+C."""
    merged = []; i = 0
    while i < len(segments):
        current = segments[i]
        texts = [current['text']]
        current_end = current['end']
        start_time = current['start']
        all_segs = [current]
        j = i + 1
        last_gap_end = None
        gap_was_dropped = False

        while j < len(segments):
            ns = segments[j]
            if ns['speaker'] != current['speaker']:
                break

            # ── GUARD A ──────────────────────────────────────────
            if ns['end'] < ns['start']:
                if debug: print(f"    GUARD A DROP: '{ns['text']}'")
                j += 1; continue

            # ── GUARD B ──────────────────────────────────────────
            if gap_was_dropped and last_gap_end is not None:
                if ns['start'] < last_gap_end:
                    if debug: print(f"    GUARD B DROP: '{ns['text']}'")
                    current_end = max(current_end, ns['end'])
                    j += 1; continue
                else:
                    gap_was_dropped = False; last_gap_end = None

            # ── GUARD C ──────────────────────────────────────────
            if ns.get('from_gap'):
                if _is_gap_corrupted(ns, segments, j):
                    if debug: print(f"    GUARD C DROP GAP: '{ns['text'][:50]}'")
                    last_gap_end = ns['end']
                    gap_was_dropped = True
                    current_end = max(current_end, ns['end'])
                    j += 1; continue

            pause = ns['start'] - current_end
            if pause <= 2.0:
                texts.append(ns['text']); all_segs.append(ns)
                current_end = ns['end']; j += 1
            else:
                break

        ft = join_texts_deduplicated(texts)
        ft = clean_loops(ft)
        ft = clean_hallucinations_from_text(ft, current['speaker'])
        if ft:
            merged.append({"speaker": current['speaker'], "start": start_time,
                           "end": current_end, "text": ft})
        i = j
    return merged


# ──────────────────────────────────────────────────────────────────
# ТЕСТ-КЕЙСЫ
# ──────────────────────────────────────────────────────────────────
PASS = "✅ GREEN"; FAIL = "❌ RED"
results = []

def check(name, got, must_contain, must_not_contain):
    ok = True
    for s in must_contain:
        if s.lower() not in got.lower():
            print(f"  MISSING: '{s}'"); ok = False
    for s in must_not_contain:
        if s.lower() in got.lower():
            print(f"  PRESENT (должен быть удалён): '{s}'"); ok = False
    status = PASS if ok else FAIL
    results.append(ok)
    print(f"{status}  {name}")
    if not ok: print(f"       Получили: '{got[:120]}'")
    return ok


# ── Тест 1: BAG_C_5 — артиллерия ──────────────────────────────────
segs_c5 = [
    {"start":1289.92,"end":1292.08,"text":"И еще одним фактором,",     "speaker":"Исаев","raw_speaker_id":"SPEAKER_00"},
    {"start":1292.22,"end":1294.30,"text":"который необходимо учитывать,","speaker":"Исаев","raw_speaker_id":"SPEAKER_00"},
    {"start":1294.30,"end":1299.28,"text":"была немецкая артиллерия вправь до еще одним фактором которые надо учитывать это было немецкая",
                                         "speaker":"Исаев","raw_speaker_id":"GAP_FILLED","from_gap":True},
    {"start":1299.28,"end":1296.74,"text":"вплоть до...","speaker":"Исаев","raw_speaker_id":"SPEAKER_00"},
    {"start":1298.12,"end":1299.16,"text":"который надо учитывать,","speaker":"Исаев","raw_speaker_id":"SPEAKER_00"},
    {"start":1299.28,"end":1301.18,"text":"это была немецкая артиллерия,","speaker":"Исаев","raw_speaker_id":"SPEAKER_00"},
    {"start":1301.38,"end":1302.92,"text":"вплоть до самых крупных калибров.","speaker":"Исаев","raw_speaker_id":"SPEAKER_00"},
    {"start":1303.24,"end":1304.50,"text":"Самый большой калибр,","speaker":"Исаев","raw_speaker_id":"SPEAKER_00"},
]

res_c5 = merge_replicas_with_guards(segs_c5)
text_c5 = res_c5[0]['text'] if res_c5 else ""
check("BAG_C_5: дубль удалён",         text_c5,
      must_contain=["немецкая артиллерия", "вплоть до самых крупных калибров"],
      must_not_contain=["вправь до", "надо учитывать это было"])

check("BAG_C_5: начало сохранено",     text_c5,
      must_contain=["И еще одним фактором", "который необходимо учитывать"],
      must_not_contain=[])


# ── Тест 2: BAG_C_3 — патрули ─────────────────────────────────────
segs_c3 = [
    {"start":2093.42,"end":2093.88,"text":"например,",            "speaker":"Исаев","raw_speaker_id":"SPEAKER_00"},
    {"start":2094.08,"end":2094.66,"text":"такой мерой",           "speaker":"Исаев","raw_speaker_id":"SPEAKER_00"},
    {"start":2094.66,"end":2095.00,"text":"были",                  "speaker":"Исаев","raw_speaker_id":"SPEAKER_00"},
    {"start":2095.00,"end":2096.48,"text":"офицерские,",           "speaker":"Исаев","raw_speaker_id":"SPEAKER_00"},
    {"start":2096.66,"end":2097.58,"text":"командирские",          "speaker":"Исаев","raw_speaker_id":"SPEAKER_00"},
    {"start":2097.58,"end":2105.58,"text":"патрули, когда прибывающая артиллерия распределялась не просто регулировщиками, а специальными офицерскими",
                                         "speaker":"Исаев","raw_speaker_id":"GAP_FILLED","from_gap":True},
    {"start":2105.58,"end":2098.56,"text":"когда",                 "speaker":"Исаев","raw_speaker_id":"SPEAKER_00"},
    {"start":2098.56,"end":2099.42,"text":"прибывающая",           "speaker":"Исаев","raw_speaker_id":"SPEAKER_00"},
    {"start":2099.42,"end":2100.10,"text":"артиллерия,",           "speaker":"Исаев","raw_speaker_id":"SPEAKER_00"},
    {"start":2100.10,"end":2101.46,"text":"она распределялась",    "speaker":"Исаев","raw_speaker_id":"SPEAKER_00"},
    {"start":2101.46,"end":2102.12,"text":"не просто",             "speaker":"Исаев","raw_speaker_id":"SPEAKER_00"},
    {"start":2102.12,"end":2103.64,"text":"регулировщиками,",      "speaker":"Исаев","raw_speaker_id":"SPEAKER_00"},
    {"start":2103.80,"end":2104.90,"text":"а специальными",        "speaker":"Исаев","raw_speaker_id":"SPEAKER_00"},
    {"start":2104.90,"end":2105.58,"text":"офицерскими",           "speaker":"Исаев","raw_speaker_id":"SPEAKER_00"},
    {"start":2105.58,"end":2106.20,"text":"патрулями,",            "speaker":"Исаев","raw_speaker_id":"SPEAKER_00"},
    {"start":2106.36,"end":2107.46,"text":"что способствовало",    "speaker":"Исаев","raw_speaker_id":"SPEAKER_00"},
    {"start":2107.46,"end":2109.80,"text":"упорядочиванию",        "speaker":"Исаев","raw_speaker_id":"SPEAKER_00"},
    {"start":2109.80,"end":2110.56,"text":"движения",              "speaker":"Исаев","raw_speaker_id":"SPEAKER_00"},
]

res_c3 = merge_replicas_with_guards(segs_c3)
text_c3 = res_c3[0]['text'] if res_c3 else ""
check("BAG_C_3: дубль удалён",          text_c3,
      must_contain=["патрулями", "что способствовало", "упорядочиванию"],
      must_not_contain=["когда прибывающая артиллерия распределялась не просто регулировщиками, а специальными офицерскими когда"])

check("BAG_C_3: преамбула сохранена",   text_c3,
      must_contain=["например", "такой мерой", "были", "офицерские", "командирские"],
      must_not_contain=[])

print()
total = len(results)
passed = sum(results)
print(f"{'='*40}")
print(f"ИТОГ: {passed}/{total} GREEN {'✅ ALL PASS' if passed==total else '❌ ЕСТЬ ОШИБКИ'}")
