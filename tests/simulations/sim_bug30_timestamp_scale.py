#!/usr/bin/env python3
"""
sim_bug30_timestamp_scale.py
Симуляция BAG_F (FIX 2): Инверсия timestamp после split — scale-аномалия

ROOT CAUSE (доказан логом NW Uckpa0003_01_04_postprocess.log):
  split_mixed_speaker_segments() наследует sub_segments от родителя целиком.
  Дочерний сегмент [00:15:05] Исаев: words_post=87, но total_pre_words=199
  → scale = 199/87 = 2.287
  → _get_real_time_for_word(word_idx=56) → scaled_idx=128 → попадает в sub[~30]
  → inject_timestamp=00:16:26 > seg.end=00:15:59 → ИНВЕРСИЯ в TXT

FIX (v17.11): guard в insert_intermediate_timestamps()
  if scale > 1.8 → sub_segments=[], has_real_data=False → fallback ESTIMATED
  → inject_timestamp строго внутри [seg.start, seg.end]

КЕЙСЫ:
  CASE 1: Нормальный сегмент (scale≈1.01) — REAL mode, timestamp корректны
  CASE 2: Child A после split (scale=2.287) — guard срабатывает, ESTIMATED, нет инверсии
  CASE 3: Child B после split (scale=2.764) — то же
  CASE 4: Граничный scale=1.5 (ниже порога) — REAL mode используется
"""

import sys
import os
import re
import io

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..', 'scripts'))

from corrections.timestamp_fixer import insert_intermediate_timestamps

# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

def extract_injected_timestamps(text):
    """Извлекает все HH:MM:SS из середины текста (не в начале строки)."""
    return re.findall(r'\s(\d{2}:\d{2}:\d{2})\s', text)

def hms_to_sec(hms):
    h, m, s = hms.split(':')
    return int(h) * 3600 + int(m) * 60 + int(s)

def check_injected_within_bounds(seg, output_text):
    """
    Все инжектированные timestamp должны быть в [seg.start, seg.end].
    Возвращает (ok: bool, violations: list)
    """
    timestamps = extract_injected_timestamps(seg.get('text', ''))
    seg_start_hms = seg.get('time', '00:00:00')
    seg_start = seg.get('start', 0)
    seg_end   = seg.get('end', 0)
    violations = []
    for ts in timestamps:
        t = hms_to_sec(ts)
        if t < seg_start or t > seg_end:
            violations.append(f"{ts} (сегмент: {seg_start_hms}–{seg_end:.0f}s)")
    return len(violations) == 0, violations

def run_insert(segments_in):
    """Запускает insert_intermediate_timestamps, перехватывает stdout."""
    buf = io.StringIO()
    saved = sys.stdout
    sys.stdout = buf
    result = insert_intermediate_timestamps(
        [dict(s) for s in segments_in], interval=30.0, debug=True
    )
    sys.stdout = saved
    return result, buf.getvalue()

# ─────────────────────────────────────────────────────────────────────────────
# Тестовые данные (из лога NW Uckpa0003_01_04_postprocess.log)
# ─────────────────────────────────────────────────────────────────────────────

# Родительские sub_segments (упрощены до 5 блоков, total=199 слов)
PARENT_SUB_SEGS = [
    {'start': 905.0, 'end': 920.0, 'words': 40},  # 00:15:05-00:15:20
    {'start': 920.0, 'end': 940.0, 'words': 45},  # 00:15:20-00:15:40
    {'start': 940.0, 'end': 959.0, 'words': 42},  # 00:15:40-00:15:59
    {'start': 959.0, 'end': 990.0, 'words': 38},  # 00:15:59-00:16:30
    {'start': 990.0, 'end': 1028.0, 'words': 34}, # 00:16:30-00:17:08
]
# Сумма: 40+45+42+38+34 = 199 слов (total_pre_words)

def make_text(n_words):
    """Генерирует текст с ровно n_words слов, с точками каждые ~12 слов."""
    word = "слово"
    sentences = []
    while n_words > 0:
        size = min(12, n_words)
        sentences.append(' '.join([word] * size) + '.')
        n_words -= size
    return ' '.join(sentences)

# CASE 1: Нормальный сегмент — sub_segments совпадают с текстом
NORMAL_SUB_SEGS = [
    {'start': 9.0,  'end': 29.0,  'words': 35},
    {'start': 29.0, 'end': 46.0,  'words': 24},
    {'start': 46.0, 'end': 61.0,  'words': 30},
    {'start': 61.0, 'end': 64.0,  'words': 5},
    {'start': 65.0, 'end': 83.0,  'words': 26},
    {'start': 83.0, 'end': 96.0,  'words': 24},
    {'start': 96.0, 'end': 113.0, 'words': 31},
    {'start': 113.0, 'end': 125.0, 'words': 28},
    {'start': 125.0, 'end': 141.0, 'words': 20},
    {'start': 141.0, 'end': 152.0, 'words': 21},
    {'start': 152.0, 'end': 159.0, 'words': 14},
    {'start': 159.0, 'end': 163.0, 'words': 7},
    {'start': 163.0, 'end': 173.0, 'words': 23},
    {'start': 173.0, 'end': 186.0, 'words': 23},
    {'start': 186.0, 'end': 196.0, 'words': 21},
    {'start': 196.0, 'end': 203.0, 'words': 14},
    {'start': 203.0, 'end': 209.0, 'words': 11},
    {'start': 209.0, 'end': 215.0, 'words': 13},
    {'start': 215.0, 'end': 220.0, 'words': 14},
]  # total_pre=384, duration=211s, scale≈1.01

SEG_CASE1 = {
    'time': '00:00:09', 'speaker': 'Исаев',
    'start': 9.0, 'end': 220.0,  # 211s > 30s
    'text': make_text(380),       # 380 слов post-clean
    'sub_segments': NORMAL_SUB_SEGS,
}

# CASE 2: Child A после split — BAG_F (scale=2.287)
SEG_CASE2 = {
    'time': '00:15:05', 'speaker': 'Исаев',
    'start': 905.0, 'end': 959.0,   # 54s > 30s
    'text': make_text(87),           # 87 слов post-clean
    'sub_segments': PARENT_SUB_SEGS, # ← унаследованы от родителя! (199 слов)
}
# scale = 199/87 = 2.287 → БЕЗ фикса: inject~00:16:26 > end=00:15:59

# CASE 3: Child B после split — BAG_F (scale=2.764)
SEG_CASE3 = {
    'time': '00:15:59', 'speaker': 'Журналист',
    'start': 959.0, 'end': 1003.0,  # 44s > 30s
    'text': make_text(72),           # 72 слова post-clean
    'sub_segments': PARENT_SUB_SEGS, # ← те же унаследованные!
}
# scale = 199/72 = 2.764 → БЕЗ фикса: inject за пределами сегмента

# CASE 4: Граничный scale=1.5 (ниже порога 1.8) — REAL mode должен сохраниться
BORDERLINE_SUB_SEGS = [
    {'start': 200.0, 'end': 240.0, 'words': 60},
    {'start': 240.0, 'end': 280.0, 'words': 60},
]  # total_pre=120, post≈80, scale=120/80=1.5

SEG_CASE4 = {
    'time': '00:03:20', 'speaker': 'Исаев',
    'start': 200.0, 'end': 280.0,   # 80s
    'text': make_text(80),
    'sub_segments': BORDERLINE_SUB_SEGS,
}

# ─────────────────────────────────────────────────────────────────────────────
# Запуск тестов
# ─────────────────────────────────────────────────────────────────────────────

pass_count = 0
fail_count = 0

def assert_green(name, seg_result, output, expect_guard=False, expect_skip=False):
    global pass_count, fail_count
    print(f"\n{'─'*60}")
    print(f"🧪 {name}")

    if expect_skip:
        # SHORT SKIP — timestamp не должны инжектироваться
        injected = extract_injected_timestamps(seg_result.get('text', ''))
        if not injected:
            print(f"  ✅ GREEN — SHORT SKIP, timestamp не инжектированы")
            pass_count += 1
        else:
            print(f"  ❌ RED — ожидался SHORT SKIP, но найдены timestamp: {injected}")
            fail_count += 1
        return

    guard_fired = "BAG_F GUARD" in output
    in_bounds, violations = check_injected_within_bounds(seg_result, output)

    if expect_guard and not guard_fired:
        print(f"  ❌ RED — ожидался BAG_F GUARD, но не сработал")
        print(f"     scale, видимо, ≤ 1.8 или has_real_data=False изначально")
        fail_count += 1
        return

    if expect_guard and guard_fired:
        print(f"  ✅ BAG_F GUARD сработал (scale > 1.8, fallback ESTIMATED)")

    if in_bounds:
        injected = extract_injected_timestamps(seg_result.get('text', ''))
        print(f"  ✅ GREEN — инжектировано {len(injected)} timestamp, все в пределах сегмента")
        pass_count += 1
    else:
        print(f"  ❌ RED — timestamp вышли за границы сегмента:")
        for v in violations:
            print(f"     {v}")
        fail_count += 1


# ── CASE 1 ──────────────────────────────────────────────────────────────────
result1, out1 = run_insert([SEG_CASE1])
assert_green("CASE 1: Нормальный сегмент (scale≈1.01, REAL mode)", result1[0], out1)

# ── CASE 2 ──────────────────────────────────────────────────────────────────
result2, out2 = run_insert([SEG_CASE2])
assert_green(
    "CASE 2: Child A после split [00:15:05] Исаев (scale=2.287) — BAG_F",
    result2[0], out2, expect_guard=True
)

# ── CASE 3 ──────────────────────────────────────────────────────────────────
result3, out3 = run_insert([SEG_CASE3])
assert_green(
    "CASE 3: Child B после split [00:15:59] Журналист (scale=2.764) — BAG_F",
    result3[0], out3, expect_guard=True
)

# ── CASE 4 ──────────────────────────────────────────────────────────────────
result4, out4 = run_insert([SEG_CASE4])
assert_green(
    "CASE 4: Граничный scale=1.5 (< порога 1.8) — REAL mode сохранён",
    result4[0], out4, expect_guard=False
)

# ─────────────────────────────────────────────────────────────────────────────
print(f"\n{'═'*60}")
print(f"ИТОГО: {pass_count} GREEN / {fail_count} RED")
if fail_count == 0:
    print("✅ ALL GREEN — фикс BAG_F работает корректно")
else:
    print("❌ ЕСТЬ КРАСНЫЕ — проверь guard в timestamp_fixer.py")
print(f"{'═'*60}")
