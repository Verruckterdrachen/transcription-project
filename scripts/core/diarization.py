#!/usr/bin/env python3
"""
core/diarization.py - Диаризация аудио (speaker diarization)

🔧 v17.8: FIX БАГ #26 - "Спикер" вместо speaker_surname в TXT
v16.0 - Оригинальная версия с правильным синтаксисом itertracks()
"""

from collections import defaultdict
from core.utils import seconds_to_hms

def compute_speaker_stats(diarization):
    """
    Вычисляет статистику времени говорения для каждого спикера

    Args:
        diarization: Результат pyannote diarization

    Returns:
        dict: {speaker_id: total_duration_seconds}
    """
    stats = defaultdict(float)

    # yield_label=True → возвращает (turn, track, speaker)
    for turn, _, speaker in diarization.itertracks(yield_label=True):
        stats[speaker] += turn.end - turn.start

    print(f"  📊 Stats: {dict(stats)}")
    return stats

def diarize_audio(pipeline, wav_path, min_speakers=2, max_speakers=3):
    """
    Выполняет speaker diarization с помощью pyannote

    Args:
        pipeline: Pyannote pipeline
        wav_path: Path к WAV файлу
        min_speakers: Минимальное количество спикеров
        max_speakers: Максимальное количество спикеров

    Returns:
        Diarization объект или None при ошибке
    """
    print(f"  🗣️ Диаризация {wav_path.name} (min={min_speakers}, max={max_speakers})...")

    try:
        diarization = pipeline(
            str(wav_path),
            min_speakers=min_speakers,
            max_speakers=max_speakers,
            segmentation_onset=0.7,
            segmentation_offset=0.5
        )
    except TypeError:
        print("  ⚠️ Версия pyannote не поддерживает segmentation параметры, используем стандартные")
        diarization = pipeline(
            str(wav_path),
            min_speakers=min_speakers,
            max_speakers=max_speakers
        )

    if diarization is None:
        return None

    # Вывод информации о спикерах
    speakers = set()
    for turn, _, speaker in diarization.itertracks(yield_label=True):
        speakers.add(speaker)
        duration = turn.end - turn.start
        print(f"  🔍 {speaker} [{seconds_to_hms(turn.start)}-{seconds_to_hms(turn.end)}] {duration:.1f}s")

    print(f"  👥 Спикеров: {len(speakers)}, {list(speakers)}")

    if len(speakers) < 2:
        print(f"  ⚠️ ВНИМАНИЕ: Обнаружен только {len(speakers)} спикер!")

    return diarization

def align_segment_to_diarization(start, end, diarization):
    """
    Определяет спикера для сегмента на основе overlap с диаризацией

    Args:
        start: Начало сегмента (секунды)
        end: Конец сегмента (секунды)
        diarization: Результат pyannote diarization

    Returns:
        (speaker_id, coverage_pct): ID спикера и процент покрытия
    """
    overlaps = defaultdict(float)
    total_coverage = 0.0
    seg_len = end - start

    for turn, _, speaker in diarization.itertracks(yield_label=True):
        overlap_start = max(start, turn.start)
        overlap_end = min(end, turn.end)

        if overlap_start < overlap_end:
            overlap_len = overlap_end - overlap_start
            overlaps[speaker] += overlap_len
            total_coverage += overlap_len

    if total_coverage > 0:
        max_speaker = max(overlaps, key=overlaps.get)
        coverage_pct = (overlaps[max_speaker] / seg_len) * 100
        return max_speaker, coverage_pct

    return None, 0

def identify_speaker_roles(stats, all_segments_raw, speaker_surname=None):
    """
    🔧 v17.8: FIX БАГ #26 - Использование speaker_surname вместо "Спикер"
    
    Определяет роли спикеров (speaker_surname/Спикер, Журналист, Оператор)

    Args:
        stats: Статистика времени говорения
        all_segments_raw: Все raw сегменты после транскрибации
        speaker_surname: Фамилия главного спикера (NEW v17.8)

    Returns:
        dict: {speaker_id: role_name}
    """
    print("\n🎭 Определение ролей спикеров...")
    
    # 🆕 v17.8: Используем speaker_surname если передан
    main_speaker_role = speaker_surname if speaker_surname else "Спикер"
    print(f"  📝 Главный спикер будет: '{main_speaker_role}'")

    # Паттерны для определения Оператора
    OPERATOR_PATTERNS = r'(?:' \
        r'камера\s+(?:идет|идёт|пошла)|' \
        r'поехали|пишем|начали|записываем|' \
        r'камера(?:\s|$)|' \
        r'запись' \
        r')'

    # Паттерны для определения Журналиста
    JOURNALIST_PATTERNS = r'(?:' \
        r'\d+\s+вопрос|первый\s+вопрос|второй\s+вопрос|третий\s+вопрос|' \
        r'представьтесь?\s+пожалуйста|' \
        r'как\s+вас\s+будут\s+расписывать|' \
        r'мы\s+сейчас\s+отвечаем\s+на\s+вопросы|' \
        r'у\s+нас\s+сериал|' \
        r'тема\s+нашего|' \
        r'представляетесь|' \
        r'расскажите?|опишите|объясните|' \
        r'что\s+вы\s+(?:думаете|считаете)|' \
        r'как\s+вы\s+(?:думаете|считаете)' \
        r')\b|\?$'

    import re

    # Анализируем каждого спикера
    speaker_analysis = {}

    for speaker_id, duration in stats.items():
        operator_score = 0
        journalist_score = 0
        total_segments = 0
        avg_segment_length = 0
        early_appearance = False

        speaker_segments = [s for s in all_segments_raw if s.get('raw_speaker_id') == speaker_id]

        if speaker_segments:
            total_segments = len(speaker_segments)
            avg_segment_length = duration / total_segments if total_segments > 0 else 0

            # Проверяем раннее появление (первые 30 секунд)
            if any(s['start'] < 30 for s in speaker_segments):
                early_appearance = True

            # Анализируем первые 10 сегментов
            for seg in speaker_segments[:10]:
                text = seg.get('text', '')

                if re.search(OPERATOR_PATTERNS, text, re.I):
                    operator_score += 3

                if re.search(JOURNALIST_PATTERNS, text, re.I):
                    journalist_score += 2

        speaker_analysis[speaker_id] = {
            'duration': duration,
            'total_segments': total_segments,
            'avg_segment_length': avg_segment_length,
            'operator_score': operator_score,
            'journalist_score': journalist_score,
            'early_appearance': early_appearance
        }

    # Сортируем спикеров по времени говорения
    sorted_speakers = sorted(stats.items(), key=lambda x: x[1], reverse=True)

    roles = {}

    # Случай 1: Ровно 2 спикера
    if len(sorted_speakers) == 2:
        roles[sorted_speakers[0][0]] = main_speaker_role  # 🔧 v17.8: было "Спикер"
        roles[sorted_speakers[1][0]] = "Журналист"
        print(f"  ✅ 2 спикера: {sorted_speakers[0][0]}={main_speaker_role}, {sorted_speakers[1][0]}=Журналист")
        return roles

    # Случай 2: 3+ спикера
    if len(sorted_speakers) >= 3:
        # Главный спикер - тот кто больше всех говорил
        main_speaker_id = sorted_speakers[0][0]
        roles[main_speaker_id] = main_speaker_role  # 🔧 v17.8: было "Спикер"

        # Ищем Оператора среди остальных
        operator_candidate = None
        max_operator_likelihood = 0

        for speaker_id, duration in sorted_speakers[1:]:
            analysis = speaker_analysis[speaker_id]
            operator_likelihood = 0

            # Короткие сегменты
            if analysis['avg_segment_length'] < 5:
                operator_likelihood += 3

            # Паттерны Оператора
            if analysis['operator_score'] > 0:
                operator_likelihood += analysis['operator_score']

            # Раннее появление
            if analysis['early_appearance']:
                operator_likelihood += 2

            # Малое время говорения
            if duration < 15:
                operator_likelihood += 2

            if operator_likelihood > max_operator_likelihood:
                max_operator_likelihood = operator_likelihood
                operator_candidate = speaker_id

        # Если нашли убедительного кандидата в Операторы
        if operator_candidate and max_operator_likelihood > 5:
            roles[operator_candidate] = "Оператор"
            print(f"  ✅ Оператор найден: {operator_candidate}")

        # Остальные - Журналисты
        for speaker_id, _ in sorted_speakers[1:]:
            if speaker_id not in roles:
                roles[speaker_id] = "Журналист"
    else:
        # Единственный спикер или что-то странное
        for speaker_id, _ in sorted_speakers[1:]:
            roles[speaker_id] = "Журналист"

    print(f"  📋 Итоговые роли: {roles}")
    return roles
