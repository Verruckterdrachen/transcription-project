"""
export/txt_export.py - Экспорт в TXT формат

🆕 v17.20: [?]-метки спорных сегментов + footer-реестр для ручной проверки
🔧 v16.26: FIX дублей timestamp - проверка наличия inner timestamps
"""

import json
import re
from pathlib import Path
from core.utils import seconds_to_hms

# ─────────────────────────────────────────────────────────────────────────────
# [?]-МЕТКИ: пороги для определения спорных сегментов
# ─────────────────────────────────────────────────────────────────────────────
SUSPICIOUS_CONFIDENCE   = -0.20   # confidence ниже → спорный
SUSPICIOUS_MAX_WORDS    = 5       # триггер 1: короткий сегмент (≤ N слов)
SUSPICIOUS_MIN_SENTENCES = 3      # триггер 2: merged-диалог (≥ N предложений)


def _count_sentences(text):
    """Считает количество предложений по знакам конца предложения."""
    parts = re.split(r'[.!?]+', text)
    return len([p for p in parts if p.strip()])

def is_suspicious_segment(seg):
    """
    🆕 v17.20: Определяет спорный сегмент для ручной проверки.

    Два независимых триггера (достаточно одного при conf < порога):

    Триггер 1 — micro-fragment:
        confidence < SUSPICIOUS_CONFIDENCE AND n_words ≤ SUSPICIOUS_MAX_WORDS
        → ловит: "держи.", "Шутки, водички..."

    Триггер 2 — merged-диалог:
        confidence < SUSPICIOUS_CONFIDENCE AND n_sentences ≥ SUSPICIOUS_MIN_SENTENCES
        → ловит: merged блок из 5 коротких реплик разных спикеров

    Returns:
        (bool, str) — (спорный?, причина-метка)
    """
    confidence  = seg.get('confidence', 0)
    text        = seg.get('text', '')
    n_words     = len(text.split())
    n_sentences = _count_sentences(text)

    if confidence >= SUSPICIOUS_CONFIDENCE:
        return False, ""

    # Триггер 1: короткий сегмент (micro-fragment / hallucination)
    if n_words <= SUSPICIOUS_MAX_WORDS:
        return True, f"conf:{confidence:.2f} | {n_words}сл [micro]"

    # Триггер 2: merged-диалог (много коротких предложений = смешанные спикеры)
    if n_sentences >= SUSPICIOUS_MIN_SENTENCES:
        avg_words = n_words / n_sentences
        return True, f"conf:{confidence:.2f} | {n_sentences}пред/{avg_words:.1f}сл/пред [merged]"

    return False, ""


def insert_inner_timestamps(text, start_sec, end_sec, next_segment_exists):
    """
    🔧 v17.25: Удалён захардкоженный русский debug ("то есть это был такой пункт")
    🆕 v16.28.3: ДЕТАЛЬНЫЙ DEBUG для поиска потери текста
    🔧 v16.26: FIX дублей timestamp - проверка наличия inner timestamps

    Для реплик длительностью > 30 секунд добавляет timestamp каждые ~25 секунд.
    """
    has_inner_timestamps = bool(re.search(r'\d{2}:\d{2}:\d{2}', text))
    if has_inner_timestamps:
        return text

    duration = end_sec - start_sec
    if duration <= 30:
        return text

    sentences = re.split(r'([.!?])\s*', text)

    if len(sentences) <= 2:
        return text

    sentence_list = []
    for i in range(0, len(sentences)-1, 2):
        if i+1 < len(sentences):
            sentence_list.append(sentences[i] + sentences[i+1])
        else:
            sentence_list.append(sentences[i])
    if len(sentences) % 2 != 0:
        sentence_list.append(sentences[-1])

    total_chars = sum(len(s) for s in sentence_list)
    if total_chars == 0:
        return text

    sentence_times = []
    current_time = start_sec
    for sentence in sentence_list:
        char_ratio = len(sentence) / total_chars
        sentence_duration = duration * char_ratio
        sentence_times.append({
            "text": sentence,
            "start": current_time,
            "end": current_time + sentence_duration
        })
        current_time += sentence_duration

    result = []
    last_timestamp_at = start_sec
    inserted_count = 0

    for i, sent_info in enumerate(sentence_times):
        sent_start = sent_info["start"]
        sent_text  = sent_info["text"]

        time_since_last = sent_start - last_timestamp_at
        time_to_end     = end_sec - sent_start

        should_insert = (
            i > 0 and
            time_since_last >= 25 and
            (time_to_end >= 30 or not next_segment_exists)
        )

        if should_insert:
            timestamp_str = seconds_to_hms(sent_start)
            result.append(f" {timestamp_str} {sent_text}")
            last_timestamp_at = sent_start
            inserted_count += 1
        else:
            result.append(f" {sent_text}" if i > 0 else sent_text)

    return ''.join(result)


def export_to_txt(txt_path, segments, speaker_surname):
    """
    🆕 v17.20: Добавлены [?]-метки спорных сегментов + footer-реестр
    Экспорт одного JSON в TXT
    """
    suspicious_list = []

    with open(txt_path, 'w', encoding='utf-8') as f:
        for i, seg in enumerate(segments):
            time    = seg.get('time', '00:00:00')
            speaker = seg.get('speaker', 'Неизвестно')
            text    = seg.get('text', '')
            start   = seg.get('start', 0)
            end     = seg.get('end', 0)

            next_segment_exists = (i + 1) < len(segments)
            text_with_timestamps = insert_inner_timestamps(
                text, start, end, next_segment_exists
            )

            # 🆕 v17.20: [?]-метка
            susp, reason = is_suspicious_segment(seg)
            if susp:
                suspicious_list.append({
                    "time": time, "speaker": speaker,
                    "text": text, "reason": reason
                })
            else:
                prefix = ""

            f.write(f"{time} {speaker}: {text_with_timestamps}\n")

        # 🆕 v17.20: Footer-реестр спорных реплик
        if suspicious_list:
            f.write("\n" + "=" * 70 + "\n")
            f.write(f"⚠️  СПОРНЫЕ РЕПЛИКИ ДЛЯ ПРОВЕРКИ: {len(suspicious_list)}\n")
            f.write("=" * 70 + "\n")
            for s in suspicious_list:
                f.write(
                    f"[?] {s['time']} — {s['speaker']} — "
                    f"\"{s['text'][:80]}\" — {s['reason']}\n"
                )
            f.write("=" * 70 + "\n")

    return txt_path


def jsons_to_txt(json_files, txt_path, speaker_surname):
    """
    🆕 v17.20: [?]-метки + footer-реестр; FIX: confidence теперь переносится в all_segments
    🔧 v16.26: FIX дублей timestamp - проверка наличия inner timestamps
    """
    print(f"\n📄 {len(json_files)} JSON → {txt_path.name}")

    all_segments   = []
    suspicious_list = []

    for json_file in json_files:
        try:
            with open(json_file, 'r', encoding='utf-8') as f:
                data = json.load(f)

            merged_segs        = data.get('segments_merged', [])
            filename_original  = data.get('file', json_file.stem)

            all_segments.append({
                "type":     "file",
                "filename": filename_original
            })

            for seg in merged_segs:
                all_segments.append({
                    "type":       "speaker",
                    "time":       seg.get('time', '00:00:00'),
                    "speaker":    seg.get('speaker', ''),
                    "text":       seg.get('text', ''),
                    "start":      seg.get('start', 0),
                    "end":        seg.get('end', 0),
                    "confidence": seg.get('confidence', 0),   # 🆕 v17.20: FIX — поле было потеряно
                })

        except Exception as e:
            print(f"  ⚠️ {json_file.name}: {e}")
            continue

    # Записываем TXT
    current_file = ""
    with open(txt_path, 'w', encoding='utf-8') as f:
        first_file = True

        for idx, seg in enumerate(all_segments):
            if seg["type"] == "file":
                if not first_file:
                    f.write("\n" + "=" * 70 + "\n\n")
                filename_clean = Path(seg["filename"]).stem
                f.write(f"{filename_clean}\n\n")
                current_file = filename_clean
                first_file   = False

            else:
                next_segment_exists = (
                    idx + 1 < len(all_segments) and
                    all_segments[idx + 1]["type"] in ("speaker", "file")
                )

                text_with_timestamps = insert_inner_timestamps(
                    seg["text"], seg["start"], seg["end"], next_segment_exists
                )

                # 🆕 v17.20: [?]-метка
                susp, reason = is_suspicious_segment(seg)
                if susp:
                    suspicious_list.append({
                        "file":    current_file,
                        "time":    seg["time"],
                        "speaker": seg["speaker"],
                        "text":    seg["text"],
                        "reason":  reason
                    })
                else:
                    prefix = ""

                f.write(f"{seg['time']} {seg['speaker']}: {text_with_timestamps}\n")

        # 🆕 v17.20: Глобальный footer-реестр
        if suspicious_list:
            f.write("\n" + "=" * 70 + "\n")
            f.write(f"⚠️  СПОРНЫЕ РЕПЛИКИ ДЛЯ ПРОВЕРКИ: {len(suspicious_list)}\n")
            f.write("=" * 70 + "\n")
            for s in suspicious_list:
                f.write(
                    f"[?] {s['file']} | {s['time']} — {s['speaker']} — "
                    f"\"{s['text'][:80]}\" — {s['reason']}\n"
                )
            f.write("=" * 70 + "\n")

    print(f" ✅ TXT: {txt_path.name} (v17.20 — [?]-метки: {len(suspicious_list)})")
    return txt_path
