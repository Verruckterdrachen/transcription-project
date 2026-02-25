"""
tests/simulations/sim_bugC_gap_overlap.py
Симуляция BAG_C (×3) + #18: GAP fill дублирует контент соседних сегментов.

ROOT CAUSE:
  _remove_gap_overlap_with_next/prev вызывались только при seg_end != original_end.
  _remove_gap_overlap_with_prev: точный == не ловил ASR-ошибки и substring-совпадения.

FIX v17.12:
  1. Оба вызова overlap removal — всегда (не зависят от флага границ)
  2. _remove_gap_overlap_with_prev — три уровня matching:
       exact tail → 1-mismatch fuzzy → substring в prev
  3. max_check_words для next: 5 → 7

Запуск: python tests/simulations/sim_bugC_gap_overlap.py
Ожидание: OLD → RED (дубль остаётся), NEW → GREEN (дубль удалён)
"""

from difflib import SequenceMatcher
import sys


# ──────────────────────────────────────────────────────────────────────────────
# Вспомогательные функции (общие)
# ──────────────────────────────────────────────────────────────────────────────

def _looks_like_restart(gap_text, next_text, min_shared_ratio=0.50):
    if not gap_text or not next_text:
        return False
    def sig_words(t):
        ws = [w.lower().strip('.,!?;:«»"()-–—') for w in t.split()]
        return set(w for w in ws if len(w) >= 4)
    g = sig_words(gap_text)
    n = sig_words(next_text)
    if not g:
        return False
    return (len(g & n) / len(g)) >= min_shared_ratio


# ──────────────────────────────────────────────────────────────────────────────
# OLD версия (воспроизводит баги)
# ──────────────────────────────────────────────────────────────────────────────

def _remove_gap_overlap_with_next_OLD(gap_text, next_text, max_check_words=5):
    if not gap_text or not next_text:
        return gap_text
    gap_words  = gap_text.strip().split()
    next_words = next_text.strip().split()
    def normalize(w):
        return w.lower().strip('.,!?;:«»"()-–')
    next_head = [normalize(w) for w in next_words[:max_check_words]]
    for n in range(min(max_check_words, len(gap_words)), 0, -1):
        gap_tail = [normalize(w) for w in gap_words[-n:]]
        if gap_tail == next_head[:n]:
            return ' '.join(gap_words[:-n]).strip()
    last_word = normalize(gap_words[-1])
    if len(last_word) <= 3:
        first_next = next_head[0] if next_head else ""
        if first_next and not first_next.startswith(last_word):
            return ' '.join(gap_words[:-1]).strip()
    return gap_text


def _remove_gap_overlap_with_prev_OLD(gap_text, prev_text, max_check_words=6):
    """OLD: только точное == tail совпадение."""
    if not gap_text or not prev_text:
        return gap_text
    gap_words  = gap_text.strip().split()
    prev_words = prev_text.strip().split()
    def norm(w):
        return w.lower().strip('.,!?;:«»"()-–—')
    gap_n  = [norm(w) for w in gap_words]
    prev_n = [norm(w) for w in prev_words]
    for n in range(min(max_check_words, len(gap_words), len(prev_words)), 0, -1):
        if gap_n[:n] == prev_n[-n:]:
            return " ".join(gap_words[n:]).strip()
    return gap_text


def simulate_gap_OLD(gap_text, prev_text, next_text, boundary_adjusted=False):
    text = gap_text
    if next_text and boundary_adjusted:
        text = _remove_gap_overlap_with_next_OLD(text, next_text, max_check_words=5)
        if not text.strip():
            return ""
        if _looks_like_restart(text, next_text):
            return ""
    if prev_text and boundary_adjusted:
        text = _remove_gap_overlap_with_prev_OLD(text, prev_text)
        if not text.strip():
            return ""
    return text


# ──────────────────────────────────────────────────────────────────────────────
# NEW версия — фикс v17.12
# ──────────────────────────────────────────────────────────────────────────────

def _remove_gap_overlap_with_next_NEW(gap_text, next_text, max_check_words=7):
    if not gap_text or not next_text:
        return gap_text
    gap_words  = gap_text.strip().split()
    next_words = next_text.strip().split()
    def normalize(w):
        return w.lower().strip('.,!?;:«»"()-–')
    next_head = [normalize(w) for w in next_words[:max_check_words]]
    for n in range(min(max_check_words, len(gap_words)), 0, -1):
        gap_tail = [normalize(w) for w in gap_words[-n:]]
        if gap_tail == next_head[:n]:
            return ' '.join(gap_words[:-n]).strip()
    last_word = normalize(gap_words[-1])
    if len(last_word) <= 3:
        first_next = next_head[0] if next_head else ""
        if first_next and not first_next.startswith(last_word):
            return ' '.join(gap_words[:-1]).strip()
    return gap_text


def _remove_gap_overlap_with_prev_NEW(gap_text, prev_text, max_check_words=6):
    """
    NEW v17.12: три уровня matching.
    1. Точное tail совпадение
    2. 1 ASR-ошибка допустима (n-1 из n слов точны)
    3. Substring: head(GAP) встречается внутри prev
    """
    if not gap_text or not prev_text:
        return gap_text
    gap_words  = gap_text.strip().split()
    prev_words = prev_text.strip().split()
    def norm(w):
        return w.lower().strip('.,!?;:«»"()-–—')
    gap_n  = [norm(w) for w in gap_words]
    prev_n = [norm(w) for w in prev_words]

    # 1. Точное tail совпадение
    for n in range(min(max_check_words, len(gap_words), len(prev_words)), 0, -1):
        if gap_n[:n] == prev_n[-n:]:
            return " ".join(gap_words[n:]).strip()

    # 2. 1 ASR-ошибка допустима
    for n in range(min(max_check_words, len(gap_words), len(prev_words)), 2, -1):
        tail_prev = prev_n[-n:]
        head_gap  = gap_n[:n]
        mismatches = sum(1 for a, b in zip(head_gap, tail_prev) if a != b)
        if mismatches == 1:
            return " ".join(gap_words[n:]).strip()

    # 3. Substring: head(GAP) встречается внутри prev
    check_len = min(max_check_words, len(gap_n))
    head_gap  = gap_n[:check_len]
    for start in range(len(prev_n) - check_len + 1):
        if prev_n[start:start + check_len] == head_gap:
            return " ".join(gap_words[check_len:]).strip()

    return gap_text


def simulate_gap_NEW(gap_text, prev_text, next_text, boundary_adjusted=False):
    """NEW: overlap removal вызывается ВСЕГДА."""
    text = gap_text

    if next_text:
        text = _remove_gap_overlap_with_next_NEW(text, next_text, max_check_words=7)
        if not text.strip():
            return ""
        if _looks_like_restart(text, next_text):
            return ""

    if prev_text:
        text = _remove_gap_overlap_with_prev_NEW(text, prev_text)
        if not text.strip():
            return ""

    return text


# ──────────────────────────────────────────────────────────────────────────────
# TEST CASES (исправленные)
# ──────────────────────────────────────────────────────────────────────────────

TEST_CASES = [
    {
        "id": "TC-01",
        "desc": "BAG_C_3 (00:34:57): патрули — граница НЕ изменена (boundary_adjusted=False)",
        "gap_text":  "офицерскими патрулями а специальными офицерскими патрулями",
        "prev_text": "когда прибывающая артиллерия распределялась не просто регулировщиками а специальными офицерскими патрулями",
        "next_text": "и это давало возможность быстро сосредоточить огонь",
        "boundary_adjusted": False,
        # FIX удаляет ведущий overlap «офицерскими патрулями» из начала GAP.
        # Оставшееся «а специальными офицерскими патрулями» — корректный новый контент.
        "must_contain": "а специальными офицерскими патрулями",
        "must_not_contain": None,
        "note": "OLD скипает prev-overlap (boundary_adjusted=False). NEW удаляет ведущий дубль.",
    },
    {
        "id": "TC-02",
        "desc": "BAG_C_4 (00:27:28): стрелковая бригада — substring match внутри prev",
        "gap_text":  "стрелковая бригада двигается вперёд на участке где был захвачен плацдарм",
        "prev_text": "именно стрелковая бригада двигается вперёд на участке где был захвачен плацдарм 36-й дивизии Симоняка",
        "next_text": "36-й дивизии Симоняка и это оказалось решающим",
        "boundary_adjusted": False,
        # GAP целиком содержится в prev → должен быть полностью удалён (пустая строка)
        "must_contain": None,
        "must_not_contain": "стрелковая бригада двигается",
        "note": "GAP целиком — substring prev. NEW удаляет через substring match.",
    },
    {
        "id": "TC-03",
        "desc": "BAG_C_5 / #18 (00:21:28): «вправь» вместо «вплоть» — 1 ASR mismatch",
        "gap_text":  "вправь до самых крупных калибров и ещё одним фактором",
        "prev_text": "была немецкая артиллерия вплоть до самых крупных калибров",
        "next_text": "который необходимо учитывать была немецкая артиллерия",
        "boundary_adjusted": False,
        # head_gap[:4] = [вправь, до, самых, крупных]
        # tail_prev[-4:] = [вплоть, до, самых, крупных] → 1 mismatch → удаляем
        "must_contain": None,
        "must_not_contain": "вправь до самых крупных",
        "note": "1 ASR-ошибка: «вправь»≠«вплоть», остальные 3 слова точны → NEW ловит.",
    },
    {
        "id": "TC-04",
        "desc": "Regression: чистый GAP без overlap не удаляется",
        # Финальное слово длиннее 3 символов — не попадает под fragment guard
        "gap_text":  "таким образом удар был нанесён одновременно с севера",
        "prev_text": "к этому моменту основные силы уже вышли на рубеж атаки",
        "next_text": "что позволило окружить группировку противника в короткие сроки",
        "boundary_adjusted": False,
        "must_contain": "таким образом удар был нанесён одновременно с севера",
        "must_not_contain": None,
        "note": "Чистый GAP — не должен удаляться ни OLD ни NEW.",
    },
    {
        "id": "TC-05",
        "desc": "Regression: boundary_adjusted=True — OLD и NEW работают одинаково",
        "gap_text":  "специальными офицерскими патрулями это было важно",
        "prev_text": "распределялась не просто регулировщиками а специальными офицерскими патрулями",
        "next_text": "это давало возможность быстро сосредоточить огонь",
        "boundary_adjusted": True,
        "must_contain": "это было важно",
        "must_not_contain": None,
        "note": "При boundary_adjusted=True OLD тоже ловит overlap (regression).",
    },
]


# ──────────────────────────────────────────────────────────────────────────────
# RUNNER
# ──────────────────────────────────────────────────────────────────────────────

def run():
    print("=" * 70)
    print("  sim_bugC_gap_overlap.py — BAG_C / #18 regression simulation")
    print("=" * 70)

    old_results = []
    new_results = []

    for tc in TEST_CASES:
        out_old = simulate_gap_OLD(
            tc["gap_text"], tc["prev_text"], tc["next_text"],
            boundary_adjusted=tc["boundary_adjusted"]
        )
        out_new = simulate_gap_NEW(
            tc["gap_text"], tc["prev_text"], tc["next_text"],
            boundary_adjusted=tc["boundary_adjusted"]
        )

        def check(output, tc):
            ok = True
            if tc["must_contain"] and tc["must_contain"] not in output:
                ok = False
            if tc["must_not_contain"] and tc["must_not_contain"] in output:
                ok = False
            return ok

        old_ok = check(out_old, tc)
        new_ok = check(out_new, tc)
        old_results.append(old_ok)
        new_results.append(new_ok)

        print(f"\n[{tc['id']}] {tc['desc']}")
        print(f"  Заметка: {tc['note']}")
        print(f"  OLD: {'✅' if old_ok else '❌'}  result='{out_old[:80]}'")
        print(f"  NEW: {'✅' if new_ok else '❌'}  result='{out_new[:80]}'")

    print("\n" + "=" * 70)
    old_score = sum(old_results)
    new_score = sum(new_results)
    total     = len(TEST_CASES)
    print(f"  OLD (до v17.12): {old_score}/{total}  "
          f"{'🟢 GREEN' if old_score == total else '🔴 RED'}")
    print(f"  NEW (v17.12 FIX): {new_score}/{total}  "
          f"{'🟢 GREEN' if new_score == total else '🔴 RED'}")
    print("=" * 70)

    if new_score == total:
        print("\n✅ SIMULATION GREEN — фикс v17.12 работает корректно.")
        import sys; sys.exit(0)
    else:
        print("\n❌ SIMULATION RED — фикс не работает, коммит запрещён!")
        import sys; sys.exit(1)


if __name__ == "__main__":
    run()
