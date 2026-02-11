"""
merge/replica_merger.py - Склейка реплик одного спикера

🆕 v16.3.1: ПРАВИЛЬНОЕ ИСПРАВЛЕНИЕ - НЕ пропускаем сегменты других спикеров
"""

from difflib import SequenceMatcher
import re
from core.utils import seconds_to_hms
from corrections.hallucinations import clean_hallucinations_from_text

def clean_loops(text):
    """
    🔧 v16.1: Удаляет зацикленные фразы (loop artifacts)
    """
    words = text.split()
    seen = set()
    cleaned = []

    i = 0
    while i < len(words):
        phrase = ' '.join(words[i:i+3])

        if phrase.lower() in seen:
            i += 1
            continue

        seen.add(phrase.lower())
        cleaned.extend(words[i:i+3])
        i += 3

    final = ' '.join(cleaned)
    final = re.sub(r'([.,!?])\1{2,}', r'\1', final)

    return final.strip()

def merge_replicas(segments):
    """
    🔧 v16.3.1: ПРАВИЛЬНО - НЕ увеличиваем j при смене спикера

    Критическое исправление: когда встречается другой спикер, НЕ делаем j += 1,
    чтобы следующая итерация начиналась именно с этого сегмента.

    Args:
        segments: Список сегментов после alignment

    Returns:
        Список merged сегментов (ВСЕ сегменты включены)
    """
    if not segments:
        return []

    def similarity(a, b):
        """Возвращает True если тексты похожи > 75%"""
        return SequenceMatcher(None, a.lower(), b.lower()).ratio() > 0.75

    merged = []
    i = 0

    while i < len(segments):
        current = segments[i]
        current_speaker = current['speaker']
        texts = [current['text']]
        current_end = current['end']
        start_time = current['start']

        print(f"  🔀 {current.get('start_hms', seconds_to_hms(start_time))} {current_speaker} — начало merge")

        # Ищем соседние сегменты того же спикера
        j = i + 1
        merge_continue = True

        while j < len(segments) and merge_continue:
            next_seg = segments[j]
            pause = next_seg['start'] - current_end

            # 🔧 v16.3.1: ИСПРАВЛЕНО - НЕ увеличиваем j при смене спикера!
            if next_seg['speaker'] != current_speaker:
                # НЕ делаем j += 1!
                merge_continue = False
                break

            # Обработка overlap (отрицательная пауза)
            if pause < 0:
                sim = SequenceMatcher(
                    None, 
                    texts[-1] if texts else "", 
                    next_seg['text']
                ).ratio()

                if sim > 0.85:
                    # Дубликат - берём более длинный
                    if len(next_seg['text']) > len(texts[-1]):
                        texts[-1] = next_seg['text']
                    current_end = next_seg['end']
                    j += 1
                    continue

                if sim > 0.60:
                    # Похожие - добавляем
                    texts.append(next_seg['text'])
                    current_end = next_seg['end']
                    j += 1
                    continue

                # Малая overlap - склеиваем
                if abs(pause) <= 2.0:
                    texts.append(next_seg['text'])
                    current_end = next_seg['end']
                    j += 1
                    continue
                else:
                    # Слишком большая overlap
                    j += 1
                    continue

            # Обработка обычной паузы
            else:
                # Для НЕ-Журналиста
                if current_speaker != "Журналист":
                    if pause <= 2.0:
                        texts.append(next_seg['text'])
                        print(f"    ↳ {next_seg.get('start_hms', '')} ⏸️ {pause:.1f}s → ✅ merge")
                        current_end = next_seg['end']
                        j += 1
                        continue
                    elif pause <= 5.0 and any(similarity(next_seg['text'], t) for t in texts[-2:]):
                        # Пауза 2-5s, но есть similarity с предыдущими
                        texts.append(next_seg['text'])
                        print(f"    ↳ {next_seg.get('start_hms', '')} ⏸️ {pause:.1f}s → ✅ merge (similarity)")
                        current_end = next_seg['end']
                        j += 1
                        continue
                    else:
                        print(f"    ↳ {current_speaker} пауза {pause:.1f}s > 5.0s → ❌ STOP")
                        merge_continue = False
                        break

                # Для Журналиста НЕ склеиваем при паузе > 3s
                if current_speaker == "Журналист":
                    if pause <= 3.0 and pause >= -12.0:
                        texts.append(next_seg['text'])
                        print(f"    ↳ {next_seg.get('start_hms', '')} ⏸️ {pause:.1f}s → ✅ merge")
                        current_end = next_seg['end']
                        j += 1
                        continue
                    else:
                        print(f"    ↳ Журналист пауза {pause:.1f}s > 3.0s → ❌ STOP")
                        merge_continue = False
                        break

        # Склеиваем тексты
        final_text = ' '.join(texts)
        final_text = clean_loops(final_text)
        final_text = clean_hallucinations_from_text(final_text, current_speaker)

        if final_text:
            merged.append({
                "speaker": current_speaker,
                "time": current.get('start_hms', seconds_to_hms(start_time)),
                "start": start_time,
                "end": current_end,
                "text": final_text,
                "confidence": current.get('confidence', ''),
                "raw_speaker_id": current.get('raw_speaker_id', '')
            })

            if len(texts) > 1:
                print(f"  ✅ Склеено {len(texts)} сегментов → {len(final_text.split())} слов")

        # 🔧 v16.3.1: ПРАВИЛЬНОЕ ПРОДВИЖЕНИЕ
        # Если j не изменилось (только i+1), значит одиночный сегмент
        # Если j изменилось, значит был merge
        i = j

    return merged
