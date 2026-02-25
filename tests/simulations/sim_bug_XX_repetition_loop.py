"""
sim_bugXX_repetition_loop.py
Тест: фильтрация дублей на уровне overlapping Whisper segments
(дубли #1, #3 из Исаев 27.05)

Root cause: дубли #1 и #3 — это overlapping segments в JSON,
не петли в тексте. fix_repetition_loop на уровне TXT ненадёжен
(неразличим от параллельных конструкций). Правильный уровень — JSON segments.

Категории:
  TP = дубль есть, должен быть убран
  TN = дубля нет, сегменты не должны измениться
  FP = похожий текст, но не дубль — не трогать
"""

from difflib import SequenceMatcher


# ─── Алгоритм ─────────────────────────────────────────────────────────────────

def dedup_overlapping_segments(segments: list, min_overlap_ratio: float = 0.3) -> list:
    """
    Из группы перекрывающихся сегментов оставляет тот, у которого
    наибольший end (= финальная версия Whisper после переигрывания).
    """
    result = []
    for seg in sorted(segments, key=lambda s: s["start"]):
        merged = False
        for i, kept in enumerate(result):
            overlap_dur = (min(seg["end"], kept["end"])
                           - max(seg["start"], kept["start"]))
            seg_dur = seg["end"] - seg["start"]
            if seg_dur > 0 and overlap_dur > 0 and (overlap_dur / seg_dur) >= min_overlap_ratio:
                # побеждает тот у кого end позже — это финальная версия
                if seg["end"] > result[i]["end"]:
                    result[i] = seg
                merged = True
                break
        if not merged:
            result.append(seg)
    return result


# ─── Тест-кейсы ───────────────────────────────────────────────────────────────

SEGMENT_CASES = [

    # ── TRUE POSITIVES ─────────────────────────────────────────────────────────

    {
        "id": "TP_dup1_officer_patrol",
        "category": "TP",
        "segments": [
            # первый segment: оборванная фраза (петля Whisper)
            {"start": 2078.0, "end": 2083.0,
             "text": "специальными офицерскими когда прибывающая артиллерия, "
                     "она распределялась не просто регулировщиками, "
                     "а специальными офицерскими"},
            # второй segment: завершённая версия с перекрытием
            {"start": 2080.0, "end": 2086.0,
             "text": "специальными офицерскими патрулями, что способствовало "
                     "упорядочиванию движения колонн"},
        ],
        "expected_count": 1,
        "expected_text_contains": "патрулями",
        "note": "дубль #1 — overlapping segments, оставить завершённый"
    },
    {
        "id": "TP_dup3_artillery_triple",
        "category": "TP",
        "segments": [
            {"start": 1288.0, "end": 1291.0,
             "text": "была немецкая артиллерия вправь до"},
            {"start": 1288.5, "end": 1293.0,
             "text": "еще одним фактором которые надо учитывать это было немецкая вплоть до"},
            {"start": 1290.0, "end": 1296.0,
             "text": "который надо учитывать, это была немецкая артиллерия, "
                     "вплоть до самых крупных калибров"},
        ],
        "expected_count": 1,
        "expected_text_contains": "вплоть до самых крупных калибров",
        "note": "дубль #3 — три перекрывающихся, оставить самый длинный/полный"
    },

    # ── TRUE NEGATIVES ─────────────────────────────────────────────────────────

    {
        "id": "TN_sequential_no_overlap",
        "category": "TN",
        "segments": [
            {"start": 100.0, "end": 104.0,
             "text": "немцы отреагировали на наступление"},
            {"start": 105.0, "end": 109.0,
             "text": "и предприняли контратаку на плацдарм"},
            {"start": 110.0, "end": 114.0,
             "text": "тигры были брошены в бой немедленно"},
        ],
        "expected_count": 3,
        "expected_text_contains": None,
        "note": "3 последовательных сегмента без перекрытия — все оставить"
    },
    {
        "id": "TN_long_replica_no_overlap",
        "category": "TN",
        "segments": [
            {"start": 500.0, "end": 508.0,
             "text": "оборона опиралась на рабочие поселки торфоразработчиков "
                     "в которых было немало каменных зданий"},
            {"start": 509.0, "end": 516.0,
             "text": "это была развитая сеть окопов блиндажей "
                     "и артиллерийских позиций"},
        ],
        "expected_count": 2,
        "expected_text_contains": None,
        "note": "две длинные реплики подряд — оба оставить"
    },

    # ── FALSE POSITIVE GUARD ───────────────────────────────────────────────────

    {
        "id": "FP_guard_near_boundary",
        "category": "FP",
        "segments": [
            {"start": 200.0, "end": 204.5,
             "text": "оборона была построена ещё с сентября 1941 года"},
            {"start": 204.6, "end": 208.0,
             "text": "к январю 1943 это была оборона больше года"},
        ],
        "expected_count": 2,
        "expected_text_contains": None,
        "note": "сегменты вплотную (0.1 сек зазор) — не перекрываются, оба оставить"
    },
    {
        "id": "FP_guard_minimal_touch",
        "category": "FP",
        "segments": [
            {"start": 300.0, "end": 305.0,
             "text": "симоняк был легендой ленинграда"},
            {"start": 304.9, "end": 309.0,
             "text": "он обладал опытом командования бригадой на полуострове ханка"},
        ],
        "expected_count": 2,
        "expected_text_contains": None,
        "note": "касание 0.1 сек — overlap_ratio=0.024 < 0.3, оба оставить"
    },
]


# ─── Запуск ───────────────────────────────────────────────────────────────────

def run():
    print("=" * 60)
    print("sim_bugXX_repetition_loop  v3")
    print("(overlapping segments — дубли #1 и #3)")
    print("=" * 60)

    all_pass = True

    for case in SEGMENT_CASES:
        out_segs = dedup_overlapping_segments(case["segments"])
        count_ok = len(out_segs) == case["expected_count"]
        text_ok = (
            case["expected_text_contains"] is None
            or any(case["expected_text_contains"] in s["text"] for s in out_segs)
        )
        ok = count_ok and text_ok
        status = "GREEN" if ok else "RED"
        if not ok:
            all_pass = False

        print(f"\n[{case['category']}] [{case['id']}] {status}")
        print(f"  IN:  {len(case['segments'])} segs  →  "
              f"OUT: {len(out_segs)} segs (expected {case['expected_count']})")
        for s in out_segs:
            print(f"       [{s['start']:.1f}-{s['end']:.1f}] {s['text'][:65]}")
        if not ok:
            print(f"  ❌ text_contains='{case['expected_text_contains']}' — "
                  f"{'найдено' if text_ok else 'НЕ найдено'}")
        print(f"  NOTE: {case['note']}")

    print("\n" + "=" * 60)
    print(f"ИТОГ: {'ALL GREEN ✅' if all_pass else 'ЕСТЬ RED ❌ — фикс не готов'}")
    print("=" * 60)


if __name__ == "__main__":
    run()
