"""
compare_snapshot.py — сравнение текущего вывода с baseline snapshot.

Использование:
    python scripts/compare_snapshot.py \
        --snapshot test-results/snapshots/v17.8_pre-fix_2026-02-24 \
        --latest   test-results/latest
"""

import argparse
import json
import re
from pathlib import Path
from difflib import unified_diff

# ── Конфигурация ───────────────────────────────────────────────────────────────

SPEAKER_NAME = "Исаев (27.05)"

# Фразы из BAG_REGISTRY — что должно ИСПРАВИТЬСЯ (было неверно)
BUG_CHECKS = {
    "BAG_A": {
        "wrong":   "фронта на изнутри",
        "correct": "на прорыв блокады изнутри",
    },
    "BAG_B": {
        "wrong":   "отцом которой был, безусловно, Говоров",  # без слова Искры перед этим
        "correct": "план Искры",
    },
    "BAG_C_3": {
        "wrong":   None,  # дубль — проверяем через счётчик вхождений
        "correct": None,
        "phrase":  "офицерскими патрулями, что способствовало",
        "max_count": 1,
    },
    "BAG_D": {
        "wrong":   None,  # структурный — проверяем через timestamp gaps
        "correct": None,
        "max_gap_seconds": 30,
    },
}

# Фразы, которые сейчас ВЕРНЫ — не должны пропасть (регрессия)
HEALTHY_PHRASES = [
    "36-й дивизии Симоняка",
    "офицерскими патрулями, что способствовало упорядочиванию",
    "Леонид Говоров",
    "Дорогу жизни",
    "командирские патрули",
    "кольцо блокады не прорвано",
    "Невский пятачок, хотя он располагался",
    "план Искры",
    "67-й армии",
    "второго эшелона",
]

# ── Вспомогательные функции ────────────────────────────────────────────────────

def read_txt(folder: Path) -> str:
    candidates = list(folder.glob(f"{SPEAKER_NAME}*.txt"))
    if not candidates:
        candidates = list(folder.glob("*.txt"))
    if not candidates:
        return ""
    return candidates[0].read_text(encoding="utf-8")


def read_log(folder: Path) -> str:
    candidates = list(folder.glob("*.log"))
    return candidates[0].read_text(encoding="utf-8") if candidates else ""


def read_jsons(folder: Path) -> list[dict]:
    json_dir = folder / "json"
    if not json_dir.exists():
        return []
    result = []
    for f in sorted(json_dir.glob("*.json")):
        try:
            result.append(json.loads(f.read_text(encoding="utf-8")))
        except Exception:
            pass
    return result


def count_loop_artifacts(log: str) -> int:
    return log.count("🔁 LOOP")


def count_gaps_filled(log: str) -> int:
    return log.count("GAP_FILLED") + log.count("✅ Добавлено из gaps")


def count_timestamp_shifts(log: str) -> int:
    return len(re.findall(r"⏱️.*сдвиг \+", log))


def find_timestamp_gaps(txt: str, max_gap: int = 30) -> list[tuple[str, str, int]]:
    """Найти места в TXT где между таймкодами >max_gap секунд."""
    pattern = re.compile(r"\[(\d{2}):(\d{2}):(\d{2})\]")
    matches = pattern.findall(txt)
    times = [int(h) * 3600 + int(m) * 60 + int(s) for h, m, s in matches]
    gaps = []
    for i in range(1, len(times)):
        delta = times[i] - times[i - 1]
        if delta > max_gap:
            ts_prev = f"{matches[i-1][0]}:{matches[i-1][1]}:{matches[i-1][2]}"
            ts_curr = f"{matches[i][0]}:{matches[i][1]}:{matches[i][2]}"
            gaps.append((ts_prev, ts_curr, delta))
    return gaps


def segment_count(jsons: list[dict]) -> int:
    total = 0
    for j in jsons:
        if isinstance(j, list):
            total += len(j)
        elif isinstance(j, dict) and "segments" in j:
            total += len(j["segments"])
    return total

# ── Главный отчёт ──────────────────────────────────────────────────────────────

def compare(snapshot_dir: Path, latest_dir: Path):
    snap_txt  = read_txt(snapshot_dir)
    new_txt   = read_txt(latest_dir)
    snap_log  = read_log(snapshot_dir)
    new_log   = read_log(latest_dir)
    snap_json = read_jsons(snapshot_dir)
    new_json  = read_jsons(latest_dir)

    W = "\033[0m"; G = "\033[32m"; R = "\033[31m"; Y = "\033[33m"; B = "\033[1m"

    print(f"\n{B}{'='*60}{W}")
    print(f"{B}  СРАВНЕНИЕ SNAPSHOT vs LATEST{W}")
    print(f"  Snapshot: {snapshot_dir.name}")
    print(f"  Latest:   {latest_dir}")
    print(f"{'='*60}{W}\n")

    # ── TXT: базовые метрики ───────────────────────────────────────────────────
    snap_lines = snap_txt.splitlines()
    new_lines  = new_txt.splitlines()
    delta_lines = len(new_lines) - len(snap_lines)
    sign = "▲" if delta_lines >= 0 else "▼"
    print(f"{B}[TXT — базовые метрики]{W}")
    print(f"  Строк было:  {len(snap_lines)}")
    print(f"  Строк стало: {len(new_lines)}  {sign} {abs(delta_lines):+d}")

    # ── TXT: проверка BAG-фраз ─────────────────────────────────────────────────
    print(f"\n{B}[TXT — статус багов]{W}")
    for bag_id, cfg in BUG_CHECKS.items():
        if cfg.get("phrase") and cfg.get("max_count") is not None:
            # дубль — считаем вхождения
            snap_n = snap_txt.count(cfg["phrase"])
            new_n  = new_txt.count(cfg["phrase"])
            if new_n <= cfg["max_count"]:
                status = f"{G}✅ FIXED{W}   (было {snap_n}×, стало {new_n}×)"
            else:
                status = f"{R}❌ OPEN{W}    (было {snap_n}×, стало {new_n}×)"
            print(f"  {bag_id}: {status}")
        elif cfg.get("max_gap_seconds") is not None:
            snap_gaps = find_timestamp_gaps(snap_txt, cfg["max_gap_seconds"])
            new_gaps  = find_timestamp_gaps(new_txt,  cfg["max_gap_seconds"])
            if len(new_gaps) == 0:
                status = f"{G}✅ FIXED{W}   (было {len(snap_gaps)} пробелов, стало 0)"
            elif len(new_gaps) < len(snap_gaps):
                status = f"{Y}⚠️ PARTIAL{W} (было {len(snap_gaps)}, стало {len(new_gaps)})"
                for g in new_gaps:
                    status += f"\n      → {g[0]}–{g[1]} ({g[2]}s)"
            else:
                status = f"{R}❌ OPEN{W}    (пробелов: {len(new_gaps)})"
            print(f"  {bag_id}: {status}")
        else:
            wrong   = cfg.get("wrong")
            correct = cfg.get("correct")
            was_wrong   = wrong   in snap_txt if wrong   else False
            now_correct = correct in new_txt  if correct else False
            now_wrong   = wrong   in new_txt  if wrong   else False
            if now_correct and not now_wrong:
                status = f"{G}✅ FIXED{W}"
            elif now_correct and now_wrong:
                status = f"{Y}⚠️ PARTIAL{W} (правильное есть, но ошибочное тоже)"
            elif was_wrong and now_wrong:
                status = f"{R}❌ OPEN{W}"
            elif not was_wrong and not now_wrong:
                status = f"{Y}⚠️ N/A{W}     (фраза не найдена ни там, ни там)"
            else:
                status = f"{G}✅ FIXED{W}   (ошибочная фраза исчезла)"
            print(f"  {bag_id}: {status}")

    # ── TXT: регрессионная защита здоровых фраз ────────────────────────────────
    print(f"\n{B}[TXT — регрессия (HEALTHY_PHRASES)]{W}")
    regression_ok = True
    for phrase in HEALTHY_PHRASES:
        in_snap = phrase in snap_txt
        in_new  = phrase in new_txt
        if in_snap and in_new:
            print(f"  {G}✅{W} {phrase!r}")
        elif in_snap and not in_new:
            print(f"  {R}🔴 REGRESSION!{W} Пропала: {phrase!r}")
            regression_ok = False
        elif not in_snap and in_new:
            print(f"  {Y}➕{W} Появилась (новая): {phrase!r}")
        else:
            print(f"  {Y}⚠️{W} Не было и нет: {phrase!r}")

    # ── LOG: метрики ──────────────────────────────────────────────────────────
    print(f"\n{B}[LOG — метрики пайплайна]{W}")
    snap_loops  = count_loop_artifacts(snap_log)
    new_loops   = count_loop_artifacts(new_log)
    snap_gaps   = count_gaps_filled(snap_log)
    new_gaps    = count_gaps_filled(new_log)
    snap_shifts = count_timestamp_shifts(snap_log)
    new_shifts  = count_timestamp_shifts(new_log)

    def log_metric(label, old, new):
        d = new - old
        color = G if d <= 0 else R
        arrow = "▼" if d < 0 else ("▲" if d > 0 else "≈")
        print(f"  {label:<30} {old} → {new}  {color}{arrow} {d:+d}{W}")

    log_metric("LOOP артефактов:",    snap_loops,  new_loops)
    log_metric("GAP filled:",         snap_gaps,   new_gaps)
    log_metric("Timestamp сдвигов ⏱️:", snap_shifts, new_shifts)

    # ── JSON: структурные метрики ─────────────────────────────────────────────
    print(f"\n{B}[JSON — структура]{W}")
    snap_segs = segment_count(snap_json)
    new_segs  = segment_count(new_json)
    d_segs    = new_segs - snap_segs
    color = G if d_segs >= 0 else Y
    print(f"  Сегментов: {snap_segs} → {new_segs}  {color}{'▲' if d_segs>0 else '▼'} {d_segs:+d}{W}")

    # ── Итог ─────────────────────────────────────────────────────────────────
    print(f"\n{B}{'='*60}{W}")
    if regression_ok:
        print(f"{G}  ✅ Регрессия не обнаружена{W}")
    else:
        print(f"{R}  🔴 ВНИМАНИЕ: обнаружена регрессия! Не коммить без проверки.{W}")
    print(f"{B}{'='*60}{W}\n")

# ── РЕЖИМ FULL: полный diff TXT ───────────────────────────────────────────────

def full_txt_diff(snap_txt: str, new_txt: str):
    W = "\033[0m"; R = "\033[31m"; G = "\033[32m"; B = "\033[1m"; Y = "\033[33m"
    snap_lines = snap_txt.splitlines(keepends=True)
    new_lines  = new_txt.splitlines(keepends=True)
    diff = list(unified_diff(
        snap_lines, new_lines,
        fromfile="snapshot (v17.8)",
        tofile="latest",
        lineterm=""
    ))
    if not diff:
        print(f"  {G}✅ TXT идентичен snapshot{W}")
        return
    added   = sum(1 for l in diff if l.startswith("+") and not l.startswith("+++"))
    removed = sum(1 for l in diff if l.startswith("-") and not l.startswith("---"))
    print(f"  Изменено строк: {R}-{removed}{W} удалено  {G}+{added}{W} добавлено\n")
    for line in diff:
        if line.startswith("@@"):
            print(f"  {Y}{line}{W}")
        elif line.startswith("+") and not line.startswith("+++"):
            print(f"  {G}{line}{W}")
        elif line.startswith("-") and not line.startswith("---"):
            print(f"  {R}{line}{W}")
        else:
            print(f"  {line}")


# ── РЕЖИМ FULL: полный анализ LOG ────────────────────────────────────────────

def full_log_diff(snap_log: str, new_log: str):
    W = "\033[0m"; R = "\033[31m"; G = "\033[32m"; B = "\033[1m"; Y = "\033[33m"

    # Паттерны важных строк лога
    PATTERNS = {
        "🔁 LOOP":       ("LOOP артефакты",      Y),
        "🚨 GAP":        ("GAP обнаружены",      Y),
        "⏱️":            ("Timestamp сдвиги",    R),
        "⚠️ GAP overlap": ("GAP overlap warnings", R),
        "🔧 Removed":    ("Удалённые фрагменты", Y),
        "❌":            ("Ошибки",              R),
        "speaker=":      ("Speaker decisions",   W),
    }

    for pattern, (label, color) in PATTERNS.items():
        snap_lines = [l.strip() for l in snap_log.splitlines() if pattern in l]
        new_lines  = [l.strip() for l in new_log.splitlines()  if pattern in l]

        if snap_lines == new_lines:
            print(f"  {G}≈{W}  {label}: без изменений ({len(new_lines)} строк)")
            continue

        print(f"\n  {B}{label}:{W}")
        # Что пропало
        for l in snap_lines:
            if l not in new_lines:
                print(f"    {R}- {l}{W}")
        # Что появилось
        for l in new_lines:
            if l not in snap_lines:
                print(f"    {G}+ {l}{W}")


# ── РЕЖИМ FULL: JSON посегментно ─────────────────────────────────────────────

def full_json_diff(snap_json: list[dict], new_json: list[dict]):
    W = "\033[0m"; R = "\033[31m"; G = "\033[32m"; B = "\033[1m"; Y = "\033[33m"

    def flatten(jsons):
        segs = []
        for j in jsons:
            if isinstance(j, list):
                segs.extend(j)
            elif isinstance(j, dict) and "segments" in j:
                segs.extend(j["segments"])
        return segs

    snap_segs = flatten(snap_json)
    new_segs  = flatten(new_json)

    # Индексируем по (start_time, speaker) для сравнения
    def key(seg):
        start = seg.get("start", seg.get("timestamp", {}).get("start", "?"))
        spk   = seg.get("speaker", seg.get("role", "?"))
        return (str(start), str(spk))

    snap_index = {key(s): s for s in snap_segs}
    new_index  = {key(s): s for s in new_segs}

    snap_keys = set(snap_index.keys())
    new_keys  = set(new_index.keys())

    # Исчезнувшие сегменты
    lost = snap_keys - new_keys
    if lost:
        print(f"\n  {R}🔴 Потеряно сегментов: {len(lost)}{W}")
        for k in sorted(lost)[:10]:
            s = snap_index[k]
            txt = s.get("text", s.get("content", ""))[:80]
            print(f"    {R}- [{k[0]}] [{k[1]}] {txt}{W}")
        if len(lost) > 10:
            print(f"    ... и ещё {len(lost)-10}")

    # Новые сегменты
    gained = new_keys - snap_keys
    if gained:
        print(f"\n  {G}✅ Новых сегментов: {len(gained)}{W}")
        for k in sorted(gained)[:10]:
            s = new_index[k]
            txt = s.get("text", s.get("content", ""))[:80]
            print(f"    {G}+ [{k[0]}] [{k[1]}] {txt}{W}")
        if len(gained) > 10:
            print(f"    ... и ещё {len(gained)-10}")

    # Изменённый текст в совпавших сегментах
    changed = []
    for k in snap_keys & new_keys:
        s_txt = snap_index[k].get("text", snap_index[k].get("content", ""))
        n_txt = new_index[k].get("text",  new_index[k].get("content", ""))
        if s_txt != n_txt:
            changed.append((k, s_txt, n_txt))

    if changed:
        print(f"\n  {Y}⚠️ Изменён текст в {len(changed)} сегментах:{W}")
        for k, old, new in changed[:15]:
            print(f"    [{k[0]}] [{k[1]}]")
            print(f"      {R}- {old[:100]}{W}")
            print(f"      {G}+ {new[:100]}{W}")
        if len(changed) > 15:
            print(f"    ... и ещё {len(changed)-15}")

    # Изменённый спикер
    spk_changed = []
    for k in snap_keys & new_keys:
        s_spk = snap_index[k].get("speaker", snap_index[k].get("role", ""))
        n_spk = new_index[k].get("speaker",  new_index[k].get("role", ""))
        if s_spk != n_spk:
            spk_changed.append((k, s_spk, n_spk))

    if spk_changed:
        print(f"\n  {R}🔴 Изменена атрибуция в {len(spk_changed)} сегментах:{W}")
        for k, old_spk, new_spk in spk_changed:
            print(f"    [{k[0]}] {R}{old_spk}{W} → {G}{new_spk}{W}")

    if not lost and not gained and not changed and not spk_changed:
        print(f"  {G}✅ JSON идентичен snapshot{W}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--snapshot", required=True)
    parser.add_argument("--latest",   required=True)
    parser.add_argument(
        "--mode",
        choices=["quick", "full"],
        default="quick",
        help="quick = только BAG-фразы и метрики | full = полный diff всех файлов"
    )
    args = parser.parse_args()

    snapshot_dir = Path(args.snapshot)
    latest_dir   = Path(args.latest)

    snap_txt  = read_txt(snapshot_dir)
    new_txt   = read_txt(latest_dir)
    snap_log  = read_log(snapshot_dir)
    new_log   = read_log(latest_dir)
    snap_json = read_jsons(snapshot_dir)
    new_json  = read_jsons(latest_dir)

    W = "\033[0m"; B = "\033[1m"

    # Всегда запускаем базовую проверку
    compare(snapshot_dir, latest_dir)

    if args.mode == "full":
        print(f"\n{B}{'='*60}{W}")
        print(f"{B}  FULL MODE: ПОЛНЫЙ DIFF TXT{W}")
        print(f"{'='*60}{W}\n")
        full_txt_diff(snap_txt, new_txt)

        print(f"\n{B}{'='*60}{W}")
        print(f"{B}  FULL MODE: АНАЛИЗ LOG{W}")
        print(f"{'='*60}{W}\n")
        full_log_diff(snap_log, new_log)

        print(f"\n{B}{'='*60}{W}")
        print(f"{B}  FULL MODE: JSON ПОСЕГМЕНТНО{W}")
        print(f"{'='*60}{W}\n")
        full_json_diff(snap_json, new_json)
