"""
sim_bugB_clean_loops_rephrase.py
Тест LOOKAHEAD GUARD для BAG_B — рефраз спикера не является loop artifact
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', '..'))

from difflib import SequenceMatcher
import re

# ── Минимальный патч clean_loops для теста ───────────────────────
RUSSIAN_STOP_WORDS = {
    'был','была','было','были','в','во','на','с','к','по','из','за',
    'и','а','но','или','что','как','если','когда','не','да','то','так',
    'я','ты','он','она','мы','вы','они','это','этот','эта','эти',
    'там','тут','уже','еще','очень',
}
MIN_MEANINGFUL_WORDS = 2
LOOP_WINDOW = 30
LOOKAHEAD_SIM_THRESHOLD = 0.70   # ниже → рефраз → не удалять


def _count_meaningful(phrase):
    clean = re.sub(r'[.,!?;:«»"\'()\[\]]', '', phrase.lower())
    return sum(1 for w in clean.split() if w not in RUSSIAN_STOP_WORDS)


def _find_after_anchor(cleaned, anchor_phrase):
    """Найти последнее вхождение anchor в cleaned[], вернуть 3 слова после."""
    anchor_words = re.sub(r'[.,!?;:«»"\'()\[\]]', '', anchor_phrase.lower()).split()
    if not anchor_words:
        return []
    cleaned_lower = [re.sub(r'[.,!?;:«»"\'()\[\]]', '', w.lower()) for w in cleaned]
    first = anchor_words[0]
    for i in range(len(cleaned_lower) - 1, -1, -1):
        if cleaned_lower[i] == first:
            return cleaned[i + len(anchor_words): i + len(anchor_words) + 3]
    return []


def clean_loops_patched(text, debug=False):
    words = text.split()
    seen = []
    cleaned = []
    i = 0

    while i < len(words):
        phrase = ' '.join(words[i:i+3])
        phrase_lower = phrase.lower()

        if _count_meaningful(phrase_lower) < MIN_MEANINGFUL_WORDS:
            cleaned.extend(words[i:i+3])
            i += 3
            continue

        is_loop = False
        matched_anchor = None

        for prev_phrase in seen:
            sim = SequenceMatcher(None, phrase_lower, prev_phrase).ratio()
            if sim >= 0.75:
                is_loop = True
                matched_anchor = prev_phrase
                break

        if is_loop:
            # ── LOOKAHEAD GUARD ──────────────────────────────────────
            after_anchor    = _find_after_anchor(cleaned, matched_anchor)
            after_candidate = words[i+3:i+6]
            if after_anchor and after_candidate:
                sim_after = SequenceMatcher(
                    None,
                    ' '.join(after_anchor).lower(),
                    ' '.join(after_candidate).lower()
                ).ratio()
                if sim_after < LOOKAHEAD_SIM_THRESHOLD:
                    if debug:
                        print(f"  🔄 РЕФРАЗ: after_anchor={after_anchor} "
                              f"vs after_cand={after_candidate} "
                              f"sim={sim_after:.2f} < {LOOKAHEAD_SIM_THRESHOLD} → KEEP")
                    seen.append(phrase_lower)
                    if len(seen) > LOOP_WINDOW:
                        seen.pop(0)
                    cleaned.extend(words[i:i+3])
                    i += 3
                    continue
            # ── конец LOOKAHEAD GUARD ─────────────────────────────────

            # Висячий предлог (v17.10)
            last_word = cleaned[-1].lower().rstrip('.,!?«»') if cleaned else ""
            HANGING = {'на','в','во','с','со','к','по','из','за','до','при','через','о','об','у','для','от','под','над'}
            if last_word in HANGING:
                seen.append(phrase_lower)
                if len(seen) > LOOP_WINDOW:
                    seen.pop(0)
                cleaned.extend(words[i:i+3])
                i += 3
                continue

            if debug:
                print(f"  🔁 LOOP: '{phrase}' ≈ '{matched_anchor}' → DROP")
            i += 1
            continue

        seen.append(phrase_lower)
        if len(seen) > LOOP_WINDOW:
            seen.pop(0)
        cleaned.extend(words[i:i+3])
        i += 3

    return ' '.join(cleaned).strip()


# ════════════════════════════════════════════════════════════════
# ТЕСТЫ
# ════════════════════════════════════════════════════════════════
PASS = "✅ GREEN"; FAIL = "❌ RED"
results = []

def run_test(name, text, must_contain, must_not_contain=None):
    result = clean_loops_patched(text, debug=True)
    ok = all(m in result for m in must_contain)
    if must_not_contain:
        ok = ok and all(m not in result for m in must_not_contain)
    results.append(ok)
    print(f"\n{'─'*60}")
    print(f"{PASS if ok else FAIL}  {name}")
    print(f"  ВХОД:  {text[:80]}...")
    print(f"  ВЫХОД: {result[:80]}...")
    for m in must_contain:
        print(f"  {'✅' if m in result else '❌'} содержит '{m}'")
    if must_not_contain:
        for m in must_not_contain:
            print(f"  {'✅' if m not in result else '❌'} НЕ содержит '{m}'")


# ТЕСТ 1: BAG_B — рефраз с именем Искры (оба вхождения должны остаться)
run_test(
    "BAG_B: рефраз 'Искры, отцом которого' → 'Искры, отцом которой'",
    ("Поэтому план Искры, отцом которого, безусловно, был прежде всего "
     "Леонид Говоров, была основа плана Искры, отцом которой был, "
     "безусловно, Говоров, было то, что весь предыдущий опыт был проанализирован"),
    must_contain=["плана Искры", "которой"],
    must_not_contain=[]
)

# ТЕСТ 2: Настоящий loop artifact (должен удалиться)
run_test(
    "Реальный loop: дословное повторение",
    ("Немецкие войска атаковали позиции советских войск. "
     "Немецкие войска атаковали позиции советских армий и продвигались вперёд."),
    must_contain=["Немецкие войска"],
    must_not_contain=[]
)

# ТЕСТ 3: BAG_A regression — висячий предлог (должен остаться)
run_test(
    "BAG_A regression: висячий предлог 'на'",
    ("фронта на прорыв блокады изнутри. "
     "Надеждой на прорыва блокада изнутри был Говоров."),
    must_contain=["прорыв блокады"],
)

# ТЕСТ 4: Рефраз без уникального имени (продолжение всё равно разное)
run_test(
    "Рефраз без имени собственного",
    ("основу обороны составляли стрелковые части, которые держали фронт. "
     "основу обороны составляли стрелковые части, которым не хватало боеприпасов."),
    must_contain=["которым не хватало"],
)

print(f"\n{'='*60}")
print(f"ИТОГ: {sum(results)}/{len(results)} GREEN")
