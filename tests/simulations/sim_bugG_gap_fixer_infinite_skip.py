"""
tests/simulations/sim_bugG_gap_fixer_infinite_skip.py

БАГ G: gap_fixer_v2 — бесконечный перебор слов после SKIP.

Точные данные из лога сегмента [00:16:12] Исаев:
  - GAP: 00:16:12 → 00:17:05 = 53s
  - gap_fixer пытается вставить inject, но все позиции
    слишком близко к 00:17:05 (dist_to_next < 25s)
  - Итог: 35+ строк SKIP, gap остаётся пустым

ROOT CAUSE: после SKIP делается i += 1 и цикл продолжается.
last_t не обновляется → на следующей итерации est_t - last_t
снова >= interval → снова проверка → снова SKIP.
Нет условия выхода когда весь оставшийся gap < MIN_NEIGHBOR_GAP.

EXPECTED (BUG):  35+ SKIP строк, 0 inject
EXPECTED (FIX):  первый SKIP → break, 0 inject, 1 строка лога
"""

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))

from corrections.timestamp_fixer import gap_fixer_v2
from core.utils import seconds_to_hms

SEG_START = 16 * 60 + 12   # 972s
SEG_END   = 18 * 60 + 53   # 1133s

PLANNED_INJECT_STR = "00:17:05"
PLANNED_INJECT_SEC = 17 * 60 + 5  # 1025s

seg_text = (
    "В начале декабря сорок второго года план операции который был представлен "
    "Ставке Верховного Главнокомандования предусматривал нанесение удара не "
    "только для прорыва блокады Ленинграда но и для более широких задач. "
    "Вызвано это было явно успехами под Сталинградом когда советские войска "
    "окружили крупную группировку немцев и планировалось расширить успех "
    "и на северном участке советско-германского фронта. "
    f"{PLANNED_INJECT_STR} "
    "Соответственно Сталин внес коррективы в план то есть была поставлена "
    "задача после прорыва блокады развить наступление в глубину с тем чтобы "
    "отбросить немцев от Ленинграда на значительное расстояние и тем самым "
    "обеспечить надежную сухопутную связь города с остальной страной."
)

words_clean = [t for t in seg_text.split()
               if not re.match(r'^\d{2}:\d{2}:\d{2}$', t)]
n_words = len(words_clean)
duration = SEG_END - SEG_START  # 161s

sub_segments = []
for i in range(43):
    t_start = SEG_START + (i / 43) * duration
    t_end   = SEG_START + ((i + 1) / 43) * duration
    sub_segments.append({"start": t_start, "end": t_end,
                         "words": max(1, round(n_words / 43))})
total_pre = sum(s["words"] for s in sub_segments)

print("=" * 60)
print("БАГ G: gap_fixer_v2 — бесконечный перебор после SKIP")
print("=" * 60)
print(f"Segment:   {seconds_to_hms(SEG_START)}–{seconds_to_hms(SEG_END)} ({duration:.0f}s)")
print(f"Плановый:  {PLANNED_INJECT_STR}")
print()

# Считаем строки SKIP в выводе
import io, contextlib
buf = io.StringIO()
with contextlib.redirect_stdout(buf):
    new_text, log = gap_fixer_v2(
        seg_text, SEG_START, SEG_END,
        sub_segments, total_pre,
        interval=30.0, threshold=45.0,
        lookahead=12, debug=True
    )
output = buf.getvalue()
print(output)

skip_lines = [l for l in output.splitlines() if "SKIP next-neighbor" in l]
inject_lines = [l for l in output.splitlines() if l.strip().startswith("inject=")]

print()
print("── ВАЛИДАЦИЯ ──────────────────────────────────────────────")
print(f"  Строк SKIP:    {len(skip_lines)}")
print(f"  inject:        {len(inject_lines)}")
print()

if len(skip_lines) > 5:
    print(f"  ❌ БАГ ВОСПРОИЗВЕДЁН: {len(skip_lines)} строк SKIP (ожидалось ≤ 1 при фиксе)")
    print("🔴 РЕЗУЛЬТАТ: БАГ ВОСПРОИЗВЕДЁН (RED)")
else:
    print(f"  ✅ Строк SKIP ≤ 5 — цикл завершился сразу")
    print("🟢 РЕЗУЛЬТАТ: GREEN — фикс применён")
