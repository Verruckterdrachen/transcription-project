# tests/simulations/sim_bug24_gap_over_inverted.py
"""
Bug: GAP_FILLED вставляется поверх реальных сегментов
Root cause: INVERTED-сегменты (start > end) не фильтруются до gap detection.

Реальные данные из NW Uckpa0001_01.json:
  Дубль #1 (патрули):    INVERTED [2105.58–2098.56] → ложный GAP 8.0 сек
  Дубль #3 (артиллерия): INVERTED [1299.28–1296.74] → ложный GAP 4.98 сек
"""

# -------------------------------------------------------
# ДАННЫЕ: реальный порядок в массиве Whisper output
# -------------------------------------------------------
CASE_1 = {
    "name": "Дубль #1 — патрули (~2097 сек)",
    "expected_false_gap": (2097.58, 2105.58),
    "segments": [
        {"start": 2096.66, "end": 2097.58, "text": "командирские"},
        {"start": 2105.58, "end": 2098.56, "text": "когда"},          # INVERTED
        {"start": 2098.56, "end": 2099.42, "text": "прибывающая"},
        {"start": 2099.42, "end": 2100.10, "text": "артиллерия,"},
        {"start": 2100.10, "end": 2101.46, "text": "она распределялась"},
        {"start": 2101.46, "end": 2102.12, "text": "не просто"},
        {"start": 2102.12, "end": 2103.64, "text": "регулировщиками,"},
        {"start": 2103.80, "end": 2104.90, "text": "а специальными"},
        {"start": 2104.90, "end": 2105.58, "text": "офицерскими"},
        {"start": 2105.58, "end": 2106.20, "text": "патрулями,"},
    ]
}

CASE_3 = {
    "name": "Дубль #3 — артиллерия (~1294 сек)",
    "expected_false_gap": (1294.30, 1299.28),
    "segments": [
        {"start": 1292.22, "end": 1294.30, "text": "который необходимо учитывать,"},
        {"start": 1299.28, "end": 1296.74, "text": "вплоть до..."},   # INVERTED
        {"start": 1298.12, "end": 1299.16, "text": "который надо учитывать,"},
        {"start": 1299.28, "end": 1301.18, "text": "это была немецкая артиллерия,"},
        {"start": 1301.38, "end": 1302.92, "text": "вплоть до самых крупных калибров."},
    ]
}

GAP_THRESHOLD = 3.0  # секунд

# -------------------------------------------------------
# ТЕКУЩАЯ ЛОГИКА: сканирование в порядке массива, без фильтрации
# -------------------------------------------------------
def detect_gaps_current(segments, threshold=GAP_THRESHOLD):
    gaps = []
    for i in range(len(segments) - 1):
        curr, nxt = segments[i], segments[i + 1]
        gap_size = nxt["start"] - curr["end"]
        if gap_size > threshold:
            gaps.append({
                "start": curr["end"],
                "end": nxt["start"],
                "size": gap_size,
                "triggered_by_inverted": nxt["end"] < nxt["start"]
            })
    return gaps

# -------------------------------------------------------
# FIXED ЛОГИКА: фильтрация INVERTED перед gap detection
# -------------------------------------------------------
def detect_gaps_fixed(segments, threshold=GAP_THRESHOLD):
    valid    = [s for s in segments if s["end"] >= s["start"]]
    inverted = [s for s in segments if s["end"] < s["start"]]
    gaps = []
    for i in range(len(valid) - 1):
        curr, nxt = valid[i], valid[i + 1]
        gap_size = nxt["start"] - curr["end"]
        if gap_size > threshold:
            gaps.append({"start": curr["end"], "end": nxt["start"], "size": gap_size})
    return gaps, inverted

# -------------------------------------------------------
# RUN
# -------------------------------------------------------
def run_case(case):
    print(f"\n{'='*55}")
    print(f"CASE: {case['name']}")
    print(f"{'='*55}")
    segs = case["segments"]
    exp_start, exp_end = case["expected_false_gap"]

    # --- CURRENT ---
    gaps_cur = detect_gaps_current(segs)
    print(f"\n[CURRENT] Gaps detected: {len(gaps_cur)}")
    bug_reproduced = False
    for g in gaps_cur:
        inv_flag = " ← triggered by INVERTED" if g["triggered_by_inverted"] else ""
        print(f"  ❌ [{g['start']:.2f}–{g['end']:.2f}] ({g['size']:.2f} сек){inv_flag}")
        if abs(g["start"] - exp_start) < 0.1 and abs(g["end"] - exp_end) < 0.1:
            bug_reproduced = True

    # --- FIXED ---
    gaps_fix, removed = detect_gaps_fixed(segs)
    print(f"\n[FIXED]  INVERTED removed: {len(removed)}")
    for s in removed:
        print(f"  🗑️  [{s['start']:.2f}–{s['end']:.2f}] '{s['text']}'")

    false_gap_gone = not any(
        abs(g["start"] - exp_start) < 0.1 and abs(g["end"] - exp_end) < 0.1
        for g in gaps_fix
    )
    print(f"[FIXED]  Gaps remaining: {len(gaps_fix)}")
    for g in gaps_fix:
        print(f"  [{g['start']:.2f}–{g['end']:.2f}] ({g['size']:.2f} сек) — реальный gap")

    # --- VERDICT ---
    green = bug_reproduced and false_gap_gone
    print(f"\n  bug_reproduced={bug_reproduced}  |  false_gap_gone={false_gap_gone}")
    print(f"  → {'🟢 GREEN' if green else '🔴 RED'}")
    return green

if __name__ == "__main__":
    results = [run_case(CASE_1), run_case(CASE_3)]
    print(f"\n{'='*55}")
    if all(results):
        print("🟢 ALL GREEN — ROOT CAUSE подтверждён")
        print("FIX: фильтровать INVERTED-сегменты ДО gap detection")
    else:
        print("🔴 FAIL — проверь threshold или порядок массива")
    print(f"{'='*55}")
