#!/usr/bin/env python3
"""
tests/simulations/sim_bugE_davai_false_positive.py
BAG_E: is_journalist_phrase() — False positive на "давайте"

ROOT CAUSE:
    r'\bдавайте\b' в weak_journalist_markers слишком широкий.
    "Да, ну давайте еще раз." — Исаев соглашается повторить,
    но функция возвращает Journalist=True.

РЕАЛЬНЫЙ КЕЙС (NW_Uckpa0001_02, 00:14:21):
    MERGE #15 склеил 5 сегментов SPEAKER_01 → блок "Журналист"
    split_mixed_speaker_segments анализирует 5 предложений:
      [1] "Ну, вы ответили практически на этот вопрос."  → Journalist=True ✅ (верно)
      [2] "Да, ну давайте еще раз."                      → Journalist=True ❌ (ЛОЖНОЕ СРАБАТЫВАНИЕ)
      [3] "Нет, не надо еще раз, может, что-то добавить."→ Journalist=False, neutral ✅
      [4] "Да, давай."                                    → Journalist=False, neutral ✅
      [5] "Почему Говоров настаивал..."                   → Journalist=False, neutral ✅

    Проблема в предложении [2]: "давайте" + действие от 1-го лица
    → должно быть Journalist=False

ВТОРОЙ РЕАЛЬНЫЙ КЕЙС (NW_Uckpa0001_02, 00:04:48):
    "Да, давайте я еще про пятачок скажу." — Исаев
    Сработало случайно (raw_speaker_id = SPEAKER_00 → original_speaker = Исаев)
    Функция возвращала Journalist=True, но спасло neutral → original.
    После фикса должно корректно возвращать Journalist=False.

FIX (предлагаемый):
    Добавить в quotation_antipatterns:
        r'\bдавайте\s+(я|мы|еще|ещё)\b'

Запуск: python tests/simulations/sim_bugE_davai_false_positive.py
"""

import sys
import re

sys.path.insert(0, "scripts")
from corrections.boundary_fixer import split_mixed_speaker_segments


# ─────────────────────────────────────────────────────────────────────────────
# OLD версия is_journalist_phrase (точная копия из boundary_fixer.py до фикса)
# ─────────────────────────────────────────────────────────────────────────────

def is_journalist_phrase_OLD(text, context_words=0):
    text_lower = text.lower()

    quotation_antipatterns = [
        r'\bтак и сказал\b',
        r'\bвот и сказал\b',
        r'\b(сказал|ответил|заявил|отметил|приказал|распорядился)\b.*\b(что|чтобы|нет|да)\b',
        r'\b(товарищ|командир|генерал|маршал|капитан|полковник)\s+\w+\s+(сказал|ответил|приказал|заявил)\b',
        r'\bкак\s+(он|они|мне|нам|ему|им)\s+(сказал|ответил|говорил)\b',
        r'\b(говорил|говорили|твердил|утверждал|утверждали|заявлял)\b',
        r'\bцитирую\b',
        r'\bпо\s+его\s+словам\b',
        r'\bпо\s+их\s+словам\b',
    ]
    for pattern in quotation_antipatterns:
        if re.search(pattern, text_lower):
            return False

    strong_journalist_markers = [
        r'\bрасскажите\b',
        r'\bобъясните\b',
        r'\bкак\s+вы\b',
        r'\bпочему\s+вы\b',
        r'\bчто\s+вы\b',
        r'\bсмотрим\b',
    ]
    for marker in strong_journalist_markers:
        if re.search(marker, text_lower):
            return True

    weak_journalist_markers = [
        r'\bвы\s+(можете|могли|должны)?',
        r'\bдавайте\b',           # ← ПРОБЛЕМА: слишком широкий
    ]
    if context_words > 100:
        return False
    for marker in weak_journalist_markers:
        if re.search(marker, text_lower):
            return True

    return False


# ─────────────────────────────────────────────────────────────────────────────
# NEW версия is_journalist_phrase (с фиксом)
# ─────────────────────────────────────────────────────────────────────────────

def is_journalist_phrase_NEW(text, context_words=0):
    text_lower = text.lower()

    quotation_antipatterns = [
        r'\bтак и сказал\b',
        r'\bвот и сказал\b',
        r'\b(сказал|ответил|заявил|отметил|приказал|распорядился)\b.*\b(что|чтобы|нет|да)\b',
        r'\b(товарищ|командир|генерал|маршал|капитан|полковник)\s+\w+\s+(сказал|ответил|приказал|заявил)\b',
        r'\bкак\s+(он|они|мне|нам|ему|им)\s+(сказал|ответил|говорил)\b',
        r'\b(говорил|говорили|твердил|утверждал|утверждали|заявлял)\b',
        r'\bцитирую\b',
        r'\bпо\s+его\s+словам\b',
        r'\bпо\s+их\s+словам\b',
        # 🔧 BAG_E FIX: "давайте я/мы/еще/ещё" — эксперт предлагает действие, не журналист
        r'\bдавайте\s+(я|мы|еще|ещё)\b',
    ]
    for pattern in quotation_antipatterns:
        if re.search(pattern, text_lower):
            return False

    strong_journalist_markers = [
        r'\bрасскажите\b',
        r'\bобъясните\b',
        r'\bкак\s+вы\b',
        r'\bпочему\s+вы\b',
        r'\bчто\s+вы\b',
        r'\bсмотрим\b',
    ]
    for marker in strong_journalist_markers:
        if re.search(marker, text_lower):
            return True

    weak_journalist_markers = [
        r'\bвы\s+(можете|могли|должны)?',
        r'\bдавайте\b',
    ]
    if context_words > 100:
        return False
    for marker in weak_journalist_markers:
        if re.search(marker, text_lower):
            return True

    return False


# ─────────────────────────────────────────────────────────────────────────────
# TEST CASES — дословно из реального кейса NW_Uckpa0001_02
# ─────────────────────────────────────────────────────────────────────────────

TEST_CASES = [
    (
        "Ну, вы ответили практически на этот вопрос.",
        0, True, True,
        "[MERGE#15 пред.1] 'вы ответили' → журналист (сохранить)"
    ),
    (
        "Да, ну давайте еще раз.",
        7, True, False,
        "[MERGE#15 пред.2] 'давайте еще раз' — Исаев соглашается (FIX)"
    ),
    (
        "Нет, не надо еще раз, может, что-то добавить.",
        12, False, False,
        "[MERGE#15 пред.3] нейтральная → original_speaker"
    ),
    (
        "Да, давай.",
        20, False, False,
        "[MERGE#15 пред.4] 'да, давай' — нейтральная"
    ),
    (
        "Почему Говоров настаивал на проведении операции по прорыву блокады именно зимой?",
        22, False, False,
        "[MERGE#15 пред.5] вопрос → neutral (отдельная задача)"
    ),
    (
        "Да, давайте я еще про пятачок скажу.",
        0, True, False,
        "[00:04:48] 'давайте я' — Исаев предлагает продолжить (FIX)"
    ),
    (
        "Давайте вы расскажете подробнее об этом.",
        0, True, True,
        "[REGRESSION] 'давайте вы' — журналист приглашает эксперта"
    ),
    (
        "Давайте обсудим этот момент подробнее.",
        0, True, True,
        "[REGRESSION] 'давайте обсудим' — нет антипаттерна"
    ),
    (
        "Давайте мы вернёмся к этой теме.",
        0, True, False,
        "[REGRESSION] 'давайте мы' — эксперт предлагает (FIX, проверить)"
    ),
]


# ─────────────────────────────────────────────────────────────────────────────
# PART 1: изолированное тестирование is_journalist_phrase
# ─────────────────────────────────────────────────────────────────────────────

def run():
    print("═" * 65)
    print("PART 1: is_journalist_phrase — изолированное тестирование")
    print("Реальный кейс: NW_Uckpa0001_02, MERGE #15, 00:14:21")
    print("═" * 65)

    all_passed = True
    new_fixes = 0

    for i, (text, ctx, expected_old, expected_new, desc) in enumerate(TEST_CASES, 1):
        got_old = is_journalist_phrase_OLD(text, ctx)
        got_new = is_journalist_phrase_NEW(text, ctx)

        old_ok = (got_old == expected_old)
        new_ok = (got_new == expected_new)

        old_status = "✅" if old_ok else "❌"
        new_status = "✅" if new_ok else "❌"

        if got_old != got_new:
            change = "🔧 FIX (True→False)" if (got_old and not got_new) else "⚠️  CHANGE (False→True)"
        else:
            change = "─ без изменений"

        print(f"\n[{i}] {desc}")
        print(f"     Текст: \"{text}\"")
        print(f"     OLD: {old_status} Journalist={got_old} (ожид={expected_old})")
        print(f"     NEW: {new_status} Journalist={got_new} (ожид={expected_new})")
        print(f"     {change}")

        if not new_ok:
            all_passed = False
        if got_old and not got_new:
            new_fixes += 1

    print("\n" + "═" * 65)
    print(f"Исправлено случаев: {new_fixes}")
    if all_passed:
        print("✅ PART 1: ALL GREEN")
    else:
        print("❌ PART 1: FAIL")

    return all_passed


# ─────────────────────────────────────────────────────────────────────────────
# PART 2: полный поток split_mixed_speaker_segments для MERGE #15
# ─────────────────────────────────────────────────────────────────────────────

def test_full_split():
    print("\n" + "═" * 65)
    print("PART 2: split_mixed_speaker_segments — полный поток MERGE #15")
    print("Ожидание: предложение [2] должно попасть к Исаеву")
    print("═" * 65)

    merged_seg = {
        "start": 861.4,
        "end": 871.46,
        "time": "00:14:21",
        "text": (
            "Ну, вы ответили практически на этот вопрос. "
            "Да, ну давайте еще раз. "
            "Нет, не надо еще раз, может, что-то добавить. "
            "Да, давай. "
            "Почему Говоров настаивал на проведении операции "
            "по прорыву блокады именно зимой."
        ),
        "speaker": "Журналист",
        "raw_speaker_id": "SPEAKER_01",
    }

    speaker_roles   = {"SPEAKER_00": "Исаев", "SPEAKER_01": "Журналист"}
    speaker_surname = "Исаев"

    result = split_mixed_speaker_segments(
        [merged_seg], speaker_surname, speaker_roles, debug=True
    )

    print(f"\n📊 Результат split: {len(result)} сегментов")
    for seg in result:
        print(f"  [{seg.get('time','???')}] {seg['speaker']}: \"{seg['text'][:70]}\"")

    found_isayev_davai = any(
        "давайте еще раз" in seg["text"].lower() and seg["speaker"] == "Исаев"
        for seg in result
    )

    print(f"\nПроверка: 'давайте еще раз' → Исаев: "
          f"{'✅ PASS' if found_isayev_davai else '❌ FAIL (ожидаемо — нужен второй этап фикса)'}")

    return found_isayev_davai


# ─────────────────────────────────────────────────────────────────────────────
# ENTRY POINT
# ─────────────────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    part1_ok = run()
    part2_ok = test_full_split()

    print("\n" + "═" * 65)
    if part1_ok and part2_ok:
        print("✅ ИТОГ: ALL GREEN (изоляция + полный поток)")
        sys.exit(0)
    else:
        print(f"⚠️  ИТОГ: PART1={'GREEN' if part1_ok else 'FAIL'} | "
              f"PART2={'GREEN' if part2_ok else 'FAIL — требует второго этапа фикса'}")
        sys.exit(1)
