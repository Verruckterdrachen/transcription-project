#!/usr/bin/env python3
"""
core/transcription.py - Транскрибация аудио с Whisper

🔥 v17.7: FIX БАГ #25 - GAP pyannote overlap attribution
🔥 v17.2: FIX БАГ #15 - GAP текст overlap с next segment
🆕 v16.5: Smart GAP Attribution - умная атрибуция GAP_FILLED по семантическому сходству
🆕 v16.3.2: Gap speaker detection - определение спикера по окружению
🆕 v16.2: Исправлен синтаксис itertracks() в force_transcribe_diar_gaps
🆕 v17.25: language параметр проброшен в force_transcribe_diar_gaps (DE support)
"""

import whisper
from core.utils import seconds_to_hms, gap_detector, extract_gap_audio, text_similarity
from core.diarization import align_segment_to_diarization
from corrections.hallucinations import is_hallucination, mark_low_confidence_words
from corrections.boundary_fixer import is_journalist_phrase  # 🆕 v17.7: FIX БАГ #25


def transcribe_audio(model, wav_path, language="ru", temperature=0.0, beam_size=5, vad_threshold=0.7):
    """
    Транскрибирует аудио файл с помощью Whisper

    Args:
        model: Загруженная модель Whisper
        wav_path: Path к WAV файлу
        language: Язык транскрибации
        temperature: Temperature для Whisper
        beam_size: Beam size для Whisper
        vad_threshold: Порог VAD (Voice Activity Detection)

    Returns:
        dict: Результат транскрибации с segments
    """
    print(f"  🎙️ Whisper транскрибация {wav_path.name}...")

    result = model.transcribe(
        str(wav_path),
        language=language,
        temperature=temperature,
        beam_size=beam_size,
        word_timestamps=True
    )

    if result and 'segments' in result:
        print(f"  ✅ Whisper: {len(result['segments'])} сегментов")
        return result

    print("  ❌ Whisper: транскрибация не удалась")
    return None

def detect_speaker_for_gap(existing_segments, gap_start, gap_end, speaker_surname):
    """
    🆕 v16.3.2: Определяет спикера для gap сегмента по окружению

    Логика:
    1. Смотрим на предыдущий сегмент (до gap)
    2. Смотрим на следующий сегмент (после gap)
    3. Если окружен одним спикером → gap принадлежит ему
    4. Если окружен разными → анализируем длину gap

    Args:
        existing_segments: Все существующие сегменты
        gap_start: Начало gap (секунды)
        gap_end: Конец gap (секунды)
        speaker_surname: Фамилия эксперта

    Returns:
        speaker: 'Журналист', speaker_surname, или 'Неизвестно'
    """
    # Находим предыдущий сегмент (до gap)
    prev_speaker = None
    for seg in sorted(existing_segments, key=lambda x: x['end'], reverse=True):
        if seg['end'] <= gap_start:
            prev_speaker = seg.get('speaker')
            break

    # Находим следующий сегмент (после gap)
    next_speaker = None
    for seg in sorted(existing_segments, key=lambda x: x['start']):
        if seg['start'] >= gap_end:
            next_speaker = seg.get('speaker')
            break

    # Если окружен одним спикером
    if prev_speaker and next_speaker and prev_speaker == next_speaker:
        return prev_speaker

    # Если только предыдущий известен
    if prev_speaker == 'Журналист':
        # Журналист обычно задает вопрос, потом эксперт отвечает
        # Если gap длинный (>15s) → скорее всего эксперт
        gap_duration = gap_end - gap_start

        if gap_duration > 15:
            return speaker_surname
        else:
            return 'Журналист'

    # Если есть информация об эксперте рядом
    if prev_speaker == speaker_surname or next_speaker == speaker_surname:
        return speaker_surname

    # Не можем определить
    return 'Неизвестно'

def _remove_gap_overlap_with_next(gap_text, next_text, max_check_words=5):
    """
    🔥 v17.2: FIX БАГ #15 - Удаление trailing overlap из GAP текста
    
    После force-transcribe GAP может захватить начало next segment из-за обрезки.
    Whisper транскрибирует с запасом, но GAP обрезается до adjusted_end.
    Результат: хвост GAP дублирует начало next (или содержит фрагменты слов).
    
    Примеры:
    - GAP: "...достаточно шум" + NEXT: "достаточно шаткую..." → remove "достаточно шум"
    - GAP: "...вправь до" + NEXT: "еще фактором..." → remove "до" (фрагмент)
    
    Args:
        gap_text: Текст из заполненного GAP
        next_text: Текст из следующего existing segment
        max_check_words: Максимум слов для проверки overlap (default=5)
    
    Returns:
        gap_text с удалённым trailing overlap
    """
    if not gap_text or not next_text:
        return gap_text
    
    gap_words = gap_text.strip().split()
    next_words = next_text.strip().split()
    
    if not gap_words or not next_words:
        return gap_text
    
    # Normalize для сравнения (lowercase, без пунктуации)
    def normalize(word):
        return word.lower().strip('.,!?;:«»"()-–')
    
    next_head = [normalize(w) for w in next_words[:max_check_words]]
    
    # 1. Проверяем точное совпадение слов в конце GAP с началом NEXT
    for n in range(min(max_check_words, len(gap_words)), 0, -1):
        gap_tail = [normalize(w) for w in gap_words[-n:]]
        
        if gap_tail == next_head[:n]:
            # Полное совпадение n слов - удаляем их
            result = ' '.join(gap_words[:-n]).strip()
            print(f"     🔧 Removed {n} overlapping words from GAP: {' '.join(gap_words[-n:])}")
            return result
    
    # 2. Проверяем последнее слово GAP - возможно это фрагмент
    last_word = normalize(gap_words[-1])
    
    # Если последнее слово очень короткое (≤3 символа) - вероятно обрезанный фрагмент
    if len(last_word) <= 3:
        first_next = next_head[0] if next_head else ""
        
        # Если это НЕ начало слова из next - скорее всего галлюцинация/фрагмент
        if first_next and not first_next.startswith(last_word):
            result = ' '.join(gap_words[:-1]).strip()
            print(f"     🔧 Removed fragment from GAP end: '{gap_words[-1]}' (likely cut-off or hallucination)")
            return result
    
    return gap_text

def _remove_gap_overlap_with_prev(gap_text, prev_text, max_check_words=6):
    """
    🔥 v17.12: FIX BAG_C / #18 — расширенное matching:
    1. Точное совпадение head(GAP) == tail(PREV) — как раньше
    2. Fuzzy: если ≥ n-1 слов из n совпадают точно (1 ASR-ошибка допустима)
    3. Substring: если весь gap_text целиком содержится в prev_text (BAG_C_4)
    Если после удаления стало пусто — GAP был целиком дублем.
    """
    if not gap_text or not prev_text:
        return gap_text

    gap_words  = gap_text.strip().split()
    prev_words = prev_text.strip().split()
    if not gap_words or not prev_words:
        return gap_text

    def norm(w):
        return w.lower().strip('.,!?;:«»"()-–—')

    gap_n  = [norm(w) for w in gap_words]
    prev_n = [norm(w) for w in prev_words]

    # ── 1. Точное совпадение head(GAP) == tail(PREV) ──────────────────────
    for n in range(min(max_check_words, len(gap_words), len(prev_words)), 0, -1):
        tail_prev = prev_n[-n:]
        head_gap  = gap_n[:n]
        if head_gap == tail_prev:
            print(f"     🔧 [v17.12] Removed {n} leading overlap words vs prev "
                  f"(exact): {' '.join(gap_words[:n])}")
            return " ".join(gap_words[n:]).strip()

    # ── 2. Допуск одной ASR-ошибки: n-1 из n слов совпадают точно ─────────
    for n in range(min(max_check_words, len(gap_words), len(prev_words)), 2, -1):
        tail_prev = prev_n[-n:]
        head_gap  = gap_n[:n]
        mismatches = sum(1 for a, b in zip(head_gap, tail_prev) if a != b)
        if mismatches == 1:
            print(f"     🔧 [v17.12] Removed {n} leading overlap words vs prev "
                  f"(1 ASR mismatch): {' '.join(gap_words[:n])}")
            return " ".join(gap_words[n:]).strip()

    # ── 3. Substring: весь gap начинается внутри prev (BAG_C_4) ───────────
    check_len = min(max_check_words, len(gap_n))
    head_gap  = gap_n[:check_len]
    for start in range(len(prev_n) - check_len + 1):
        if prev_n[start:start + check_len] == head_gap:
            print(f"     🔧 [v17.12] Removed {check_len} leading overlap words vs prev "
                  f"(substring match at pos {start}): {' '.join(gap_words[:check_len])}")
            return " ".join(gap_words[check_len:]).strip()

    return gap_text

def _looks_like_restart(gap_text, next_text, min_shared_ratio=0.50):
    """
    🔧 v17.5: порог 0.60 → 0.50, min_len 5 → 4

    Эвристика: если значимая лексика GAP сильно пересекается с next,
    то GAP вероятно содержит повтор/переформулировку → можно пропустить.

    Порог снижен с 0.60 до 0.50, потому что русские флексии уменьшают
    пересечение: "которые"/"который", "была"/"было" считаются разными словами.
    min_len снижен с 5 до 4 символов, чтобы охватить русские контентные слова
    ("было", "была", "надо", "даже", "этим").
    """
    if not gap_text or not next_text:
        return False

    def sig_words(t):
        ws = [w.lower().strip('.,!?;:«»"()-–—') for w in t.split()]
        ws = [w for w in ws if len(w) >= 4]  # было 5 → теперь 4
        return set(ws)

    g = sig_words(gap_text)
    n = sig_words(next_text)
    if not g:
        return False

    ratio = len(g & n) / len(g)
    if ratio >= min_shared_ratio:  # было 0.60 → теперь 0.50
        print(f"     🔁 Restart-like GAP: shared-with-next={ratio:.0%} → skipping")
        return True
    return False

def _find_dominant_speaker_in_pyannote(seg_start, seg_end, diarization, speaker_roles):
    """
    🆕 v17.7: FIX БАГ #25 - Находит доминирующего спикера в pyannote для GAP интервала
    
    Args:
        seg_start: Начало GAP сегмента (секунды)
        seg_end: Конец GAP сегмента (секунды)
        diarization: Объект pyannote.core.Annotation
        speaker_roles: Маппинг SPEAKER_XX → 'Спикер'/'Журналист'
    
    Returns:
        (speaker_name, overlap_duration) или (None, 0.0)
    """
    if not diarization or not speaker_roles:
        return None, 0.0
    
    overlaps = {}
    
    for turn, _, label in diarization.itertracks(yield_label=True):
        # Проверяем пересечение
        overlap_start = max(seg_start, turn.start)
        overlap_end = min(seg_end, turn.end)
        
        if overlap_start < overlap_end:
            overlap_duration = overlap_end - overlap_start
            
            if label not in overlaps:
                overlaps[label] = 0.0
            overlaps[label] += overlap_duration
    
    if not overlaps:
        return None, 0.0
    
    # Находим спикера с максимальным overlap
    dominant_label = max(overlaps, key=overlaps.get)
    dominant_duration = overlaps[dominant_label]
    
    # Конвертируем SPEAKER_XX → имя
    speaker_name = speaker_roles.get(dominant_label, dominant_label)
    
    return speaker_name, dominant_duration

def force_transcribe_diar_gaps(
    model, wav_path, gaps, existing_segments, speaker_surname=None,
    diarization=None, speaker_roles=None, language="ru"  # 🆕 v17.25: language для DE support
):
    """
    🔥 v17.12: FIX BAG_C/#18 - overlap removal вызывается ВСЕГДА (не только при adjusted boundary)
    🆕 v17.25: language параметр для поддержки немецкого (DE)
    🆕 v17.7: FIX БАГ #25 - GAP pyannote overlap attribution + text-based override
    🔧 v17.5: убрано ограничение (seg_end - seg_start) <= 7.0 в restart check
    🔥 v17.4: FIX БАГ #18/#20 - prev overlap removal + restart detection
    🔥 v17.4: FIX БАГ #19 - [нрзб] маркировка низкоуверенных слов
    🔥 v17.2: FIX БАГ #15 - Удаление overlap GAP текста с next segment
    🆕 v16.8: GAP Overlap Protection - обрезка при пересечении с соседними
    🆕 v16.5: Smart GAP Attribution - умная атрибуция GAP_FILLED по семантическому сходству
    🆕 v16.3.2: Gap speaker detection добавлен
    🔧 v16.2: Force-transcribe gaps с исправленным itertracks
    """
    print(f"\n🔄 Force-transcribe gaps...")

    added_segments = []

    for gap in gaps:
        gap_start    = gap['gap_start']
        gap_end      = gap['gap_end']
        gap_duration = gap['duration']

        print(f"  🚨 GAP {gap['gap_hms_start']}–{gap['gap_hms_end']} ({gap_duration}s)")

        # 🆕 v16.3.2: Определяем спикера ДО транскрибации
        detected_speaker = 'Неизвестно'
        if speaker_surname:
            detected_speaker = detect_speaker_for_gap(
                existing_segments,
                gap_start,
                gap_end,
                speaker_surname
            )

        # Извлекаем аудио gap с небольшим overlap
        gap_audio_path = extract_gap_audio(wav_path, gap_start, gap_end, overlap=1.0)

        try:
            result = model.transcribe(
                str(gap_audio_path),
                language=language,  # 🆕 v17.25: было "ru", теперь параметр
                temperature=0.0,
                beam_size=5,
                no_speech_threshold=0.2,
                compression_ratio_threshold=1.2,
                word_timestamps=True,  # 🆕 v17.4: FIX БАГ #19 — нужны word-level probability
            )

            if result and 'segments' in result:
                for seg in result['segments']:
                    text = seg['text'].strip()

                    # Пропускаем галлюцинации
                    if is_hallucination(text):
                        continue

                    # 🆕 v17.4: FIX БАГ #19 — [нрзб] для низкоуверенных слов
                    if seg.get('words'):
                        text = mark_low_confidence_words(text, seg['words'])

                    # Если после маркировки остался только [нрзб] целиком — пропускаем
                    if not text.strip() or text.strip() == '[нрзб]':
                        print(f"     ⚠️ GAP полностью неразборчив → skipping")
                        continue

                    # Adjust timing
                    seg_start = gap_start + float(seg['start'])
                    seg_end   = gap_start + float(seg['end'])

                    # ═══════════════════════════════════════════════════════
                    # 🆕 v16.8: GAP OVERLAP PROTECTION
                    # ═══════════════════════════════════════════════════════

                    original_start = seg_start
                    original_end   = seg_end

                    # 1. Проверяем overlap с предыдущим GAP сегментом
                    if added_segments:
                        last_gap = added_segments[-1]
                        if seg_start < last_gap["end"] + 0.5:
                            seg_start = last_gap["end"]
                            print(f"     ⚠️ GAP overlap с предыдущим GAP, adjusted start: {seg_start:.2f}s")

                    # 2. Находим следующий существующий сегмент
                    next_existing = None
                    for existing_seg in sorted(existing_segments, key=lambda x: x['start']):
                        if existing_seg['start'] >= gap_end:
                            next_existing = existing_seg
                            break

                    if next_existing and seg_end > next_existing["start"] - 0.5:
                        seg_end = next_existing["start"]
                        print(f"     ⚠️ GAP overlap с next existing, adjusted end: {seg_end:.2f}s")

                    # 3. Пропускаем слишком короткие GAP после обрезки
                    if seg_end - seg_start < 1.0:
                        print(f"     ⚠️ GAP too short after adjustment ({seg_end - seg_start:.2f}s), skipping")
                        continue

                    # 4. Показываем adjustment если был
                    if seg_start != original_start or seg_end != original_end:
                        print(f"     🔧 Adjusted: {original_start:.2f}-{original_end:.2f} → {seg_start:.2f}-{seg_end:.2f}")

                    # ═══════════════════════════════════════════════════════
                    # 🔥 v17.12: FIX BAG_C — NEXT overlap removal ВСЕГДА
                    # ═══════════════════════════════════════════════════════

                    if next_existing:
                        next_text = next_existing.get('text', '')
                        text = _remove_gap_overlap_with_next(text, next_text,
                                                             max_check_words=7)
                        if not text.strip():
                            print(f"     ⚠️ GAP text empty after next-overlap removal → skipping")
                            continue

                    # ═══════════════════════════════════════════════════════
                    # Находим предыдущий существующий сегмент
                    # ═══════════════════════════════════════════════════════

                    prev_existing = None
                    for existing_seg in sorted(existing_segments, key=lambda x: x['end'], reverse=True):
                        if existing_seg['end'] <= gap_start:
                            prev_existing = existing_seg
                            break

                    # ═══════════════════════════════════════════════════════
                    # 🔥 v17.12: FIX BAG_C/#18 — PREV overlap removal ВСЕГДА
                    # ═══════════════════════════════════════════════════════

                    if prev_existing:
                        prev_text = prev_existing.get('text', '')
                        text = _remove_gap_overlap_with_prev(text, prev_text)
                        if not text.strip():
                            print(f"     ⚠️ GAP полностью дублирует хвост prev → skipping")
                            continue

                    # ═══════════════════════════════════════════════════════
                    # 🔥 v17.12: FIX BAG_C — restart check ВСЕГДА
                    # ═══════════════════════════════════════════════════════

                    if next_existing:
                        next_text_restart = next_existing.get('text', '')
                        if _looks_like_restart(text, next_text_restart):
                            continue

                    # ═══════════════════════════════════════════════════════
                    # 🆕 v17.7: FIX БАГ #25 - GAP pyannote overlap attribution
                    # ═══════════════════════════════════════════════════════

                    pyannote_speaker, overlap_duration = _find_dominant_speaker_in_pyannote(
                        seg_start, seg_end, diarization, speaker_roles
                    )

                    if pyannote_speaker and overlap_duration > 1.0:
                        print(f"     🎙️ Pyannote overlap: {pyannote_speaker} ({overlap_duration:.1f}s)")
                        detected_speaker = pyannote_speaker

                    # ═══════════════════════════════════════════════════════
                    # 🆕 v17.7: TEXT-BASED OVERRIDE - детекция Журналиста
                    # ═══════════════════════════════════════════════════════

                    if is_journalist_phrase(text, context_words=0):
                        if detected_speaker != 'Журналист':
                            print(f"     🔄 TEXT OVERRIDE: {detected_speaker} → Журналист (паттерн обнаружен)")
                            detected_speaker = 'Журналист'

                    # ═══════════════════════════════════════════════════════
                    # 🆕 v16.5: УМНАЯ АТРИБУЦИЯ GAP_FILLED
                    # ═══════════════════════════════════════════════════════

                    final_speaker = detected_speaker

                    next_segment = None
                    for existing_seg in sorted(existing_segments, key=lambda x: x['start']):
                        if existing_seg['start'] >= gap_end:
                            next_segment = existing_seg
                            break

                    if next_segment:
                        next_speaker = next_segment.get('speaker')
                        next_text    = next_segment.get('text', '')

                        if next_speaker and next_speaker != detected_speaker:
                            similarity = text_similarity(text, next_text)

                            print(f"     🔍 Сходство с next [{next_speaker}]: {similarity:.1%}")

                            if similarity > 0.70:
                                final_speaker = next_speaker
                                print(f"     🔄 GAP_FILLED → {next_speaker} (сходство {similarity:.1%})")
                            else:
                                print(f"     ✅ GAP_FILLED → {detected_speaker} (по умолчанию)")

                    new_segment = {
                        'start':          seg_start,
                        'end':            seg_end,
                        'start_hms':      seconds_to_hms(seg_start),
                        'end_hms':        seconds_to_hms(seg_end),
                        'text':           text,
                        'speaker':        final_speaker,
                        'raw_speaker_id': 'GAP_FILLED',
                        'confidence':     seg.get('avg_logprob', -1.0),
                        'from_gap':       True
                    }

                    added_segments.append(new_segment)
                    print(f"     ✅ [{seconds_to_hms(seg_start)}] {text[:50]}...")

        except Exception as e:
            print(f"  ❌ Gap транскрибация не удалась: {e}")

        finally:
            if gap_audio_path.exists():
                gap_audio_path.unlink()

    if added_segments:
        print(f"  ✅ Добавлено из gaps: {len(added_segments)} сегментов")
    else:
        print(f"  ⚠️ Gaps не дали новых сегментов")

    return added_segments
