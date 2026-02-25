"""
sim_bugXX_segment_boundary_dup.py
Тест: дубль на границе segment'ов (хвост предыдущего = голова следующего)
Дубль #2: "стрелковая бригада двигается" × 2 на 00:27:28
"""

from difflib import SequenceMatcher

CASES = [
    {
        "id": "dup2_brigade_boundary",
        "prev_text": (
            "но гораздо более успешным оказывается в бой стрелковых бригад, "
            "как раз в центре построения советской 67-й армии, "
            "и именно стрелковая бригада двигается."
        ),
        "next_text": (
            "как раз в центре построения советской 67-й армии, "
            "и именно стрелковая бригада двигается вперед на участке, "
            "где был захвачен плацдарм, 36-й дивизии Симоняка"
        ),
        "expected_overlap_words": 14,  # "как раз...двигается" = ~14 слов
        "note": "tail-head overlap: хвост prev совпадает с головой next"
    }
]

def find_tail_head_overlap(prev: str, next_: str, min_words: int = 5) -> int:
    """
    Возвращает количество слов перекрытия (хвост prev = голова next).
    """
    prev_words = prev.split()
    next_words = next_.split()
    max_check = min(len(prev_words), len(next_words), 30)
    for n in range(max_check, min_words - 1, -1):
        tail = " ".join(prev_words[-n:])
        head = " ".join(next_words[:n])
        ratio = SequenceMatcher(None, tail.lower(), head.lower()).ratio()
        if ratio > 0.75:
            return n
    return 0

def merge_with_dedup(prev: str, next_: str, overlap_words: int) -> str:
    """Объединяет реплики, удаляя задублированный хвост prev."""
    if overlap_words == 0:
        return prev + " " + next_
    prev_trimmed = " ".join(prev.split()[:-overlap_words])
    return prev_trimmed + " " + next_

# ─── Запуск ───────────────────────────────────────────────────
print("=== sim_bugXX_segment_boundary_dup ===\n")

case = CASES[0]
overlap = find_tail_head_overlap(case["prev_text"], case["next_text"])
status = "GREEN" if overlap >= case["expected_overlap_words"] * 0.6 else "RED"
print(f"[{case['id']}] {status}")
print(f"  Найдено перекрытие: {overlap} слов (ожидалось ≥{int(case['expected_overlap_words']*0.6)})")

merged = merge_with_dedup(case["prev_text"], case["next_text"], overlap)
print(f"  MERGED: {merged[:120]}...")
print(f"  NOTE: {case['note']}")
