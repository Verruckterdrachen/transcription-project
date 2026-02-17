#!/usr/bin/env python3
"""
core/transcription.py - Транскрибация аудио с Whisper

🆕 v16.5: Smart GAP Attribution - умная атрибуция GAP_FILLED по семантическому сходству
🆕 v16.3.2: Gap speaker detection - определение спикера по окружению
🆕 v16.2: Исправлен синтаксис itertracks() в force_transcribe_diar_gaps
"""

import whisper
from core.utils import seconds_to_hms, gap_detector, extract_gap_audio, text_similarity
from core.diarization import align_segment_to_diarization
from corrections.hallucinations import is_hallucination


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


def force_transcribe_diar_gaps(model, wav_path, gaps, existing_segments, speaker_surname=None):
    """
    🆕 v16.8: GAP Overlap Protection - обрезка при пересечении с соседними
    🆕 v16.5: Smart GAP Attribution - умная атрибуция по семантическому сходству
    🆕 v16.3.2: Gap speaker detection добавлен
    🔧 v16.2: Force-transcribe gaps с исправленным itertracks

    Повторно транскрибирует пропущенные участки (gaps) используя
    данные диаризации. Использует более мягкие параметры Whisper.
    
    🆕 v16.8 ИЗМЕНЕНИЯ:
    - GAP overlap detection с предыдущими GAP и существующими сегментами
    - Автоматическая обрезка границ при overlap
    - Пропуск слишком коротких GAP после обрезки (<1s)
    
    🆕 v16.5 ИЗМЕНЕНИЯ:
    - После транскрибации проверяется семантическое сходство с next_segment
    - Если сходство >70% → GAP_FILLED атрибутируется следующему спикеру
    - Защита от ошибочной атрибуции запинок/переформулировок

    Args:
        model: Загруженная модель Whisper
        wav_path: Path к WAV файлу
        gaps: Список gaps из gap_detector
        existing_segments: Существующие сегменты (для проверки overlap)
        speaker_surname: 🆕 v16.3.2 - Фамилия эксперта для определения спикера

    Returns:
        list: Новые сегменты из gaps
    """
    print(f"\n🔄 Force-transcribe gaps...")

    added_segments = []

    for gap in gaps:
        gap_start = gap['gap_start']
        gap_end = gap['gap_end']
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
            # 🔧 v16.0: Понижен порог no_speech_threshold до 0.2
            result = model.transcribe(
                str(gap_audio_path),
                language="ru",
                temperature=0.0,
                beam_size=5,
                no_speech_threshold=0.2,  # Было 0.3
                compression_ratio_threshold=1.2
            )

            if result and 'segments' in result:
                for seg in result['segments']:
                    text = seg['text'].strip()

                    # Пропускаем галлюцинации
                    if is_hallucination(text):
                        continue

                    # Adjust timing
                    seg_start = gap_start + float(seg['start'])
                    seg_end = gap_start + float(seg['end'])

                    # ═══════════════════════════════════════════════════════
                    # 🆕 v16.8: GAP OVERLAP PROTECTION
                    # ═══════════════════════════════════════════════════════
                    
                    original_start = seg_start
                    original_end = seg_end
                    
                    # 1. Проверяем overlap с предыдущим GAP сегментом
                    if added_segments:
                        last_gap = added_segments[-1]
                        if seg_start < last_gap["end"] + 0.5:
                            seg_start = last_gap["end"]
                            print(f"     ⚠️ GAP overlap с предыдущим GAP, adjusted start: {seg_start:.2f}s")
                    
                    # 2. Проверяем overlap со следующим существующим сегментом
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
                    # 🆕 v16.5: УМНАЯ АТРИБУЦИЯ GAP_FILLED
                    # ═══════════════════════════════════════════════════════
                    
                    final_speaker = detected_speaker
                    
                    # Находим следующий сегмент после gap
                    next_segment = None
                    for existing_seg in sorted(existing_segments, key=lambda x: x['start']):
                        if existing_seg['start'] >= gap_end:
                            next_segment = existing_seg
                            break
                    
                    # Если есть следующий сегмент и его спикер отличается
                    if next_segment:
                        next_speaker = next_segment.get('speaker')
                        next_text = next_segment.get('text', '')
                        
                        if next_speaker and next_speaker != detected_speaker:
                            # Проверяем семантическое сходство
                            similarity = text_similarity(text, next_text)
                            
                            print(f"    🔍 Сходство с next [{next_speaker}]: {similarity:.1%}")
                            
                            # Если сходство >70% → переопределяем спикера
                            if similarity > 0.70:
                                final_speaker = next_speaker
                                print(f"    🔄 GAP_FILLED → {next_speaker} (сходство {similarity:.1%})")
                            else:
                                print(f"    ✅ GAP_FILLED → {detected_speaker} (по умолчанию)")

                    new_segment = {
                        'start': seg_start,
                        'end': seg_end,
                        'start_hms': seconds_to_hms(seg_start),
                        'end_hms': seconds_to_hms(seg_end),
                        'text': text,
                        'speaker': final_speaker,  # 🆕 v16.5: Используем final_speaker
                        'raw_speaker_id': 'GAP_FILLED',
                        'confidence': seg.get('avg_logprob', -1.0),
                        'from_gap': True
                    }

                    added_segments.append(new_segment)
                    print(f"    ✅ [{seconds_to_hms(seg_start)}] {text[:50]}...")

        except Exception as e:
            print(f"  ❌ Gap транскрибация не удалась: {e}")

        finally:
            # Удаляем временный файл
            if gap_audio_path.exists():
                gap_audio_path.unlink()

    if added_segments:
        print(f"  ✅ Добавлено из gaps: {len(added_segments)} сегментов")
    else:
        print(f"  ⚠️ Gaps не дали новых сегментов")

    return added_segments
