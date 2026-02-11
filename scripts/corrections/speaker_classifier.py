#!/usr/bin/env python3
"""
corrections/speaker_classifier.py - Весовая классификация спикеров v15 для v16.13

🔥 v16.13: КРИТИЧЕСКИЙ FIX RAW_SPEAKER_ID SYNC В CLASSIFICATION
- При изменении speaker ТАКЖЕ обновляется raw_speaker_id
- Создан обратный маппинг speaker_roles для синхронизации
- Исправлен баг: TXT выводил старый speaker из-за несинхронизации
- Аналогичный фикс v16.12, но для этапа классификации

🆕 v16.9: FIX CONTINUATION PHRASE ATTRIBUTION
- Исправлена логика проверки continuation phrases после длинных монологов
- Теперь проверяется монолог ПРЕДЫДУЩЕГО спикера, а не текущего
- "В частности", "То есть" корректно атрибутируются предыдущему спикеру
"""

# Version: v16.13
# Last updated: 2026-02-11
# 🔥 v16.13: КРИТИЧЕСКИЙ FIX - синхронизация raw_speaker_id при classification

import re
from core.config import SPEAKER_CLASSIFICATION_CONFIDENCE_THRESHOLD, SPEAKER_CLASSIFICATION_MIN_WORDS

# ═══════════════════════════════════════════════════════════════════════════
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ═══════════════════════════════════════════════════════════════════════════

def is_journalist_addressing_speaker(text, word_count):
    """
    Проверяет, является ли текст обращением Журналиста к Спикеру

    Args:
        text: Текст для проверки
        word_count: Количество слов в тексте

    Returns:
        bool: True если это обращение Журналиста
    """
    text_lower = text.lower()

    journalist_addressing_patterns = [
        r'\b(?:хорошо|отлично|понятно|ясно|спасибо|благодарю)\b',
        r'\b(?:давайте|можете|расскажите|опишите|объясните)\b',
        r'\b(?:ничего\s+страшного|все\s+(?:нормально|хорошо|в\s+порядке))\b',
        r'\b(?:не\s+страшно|не\s+беда|ладно|нормально)\b',
        r'\b(?:прекрасно|замечательно|великолепно)\b',
    ]

    has_journalist_addressing = any(
        re.search(p, text_lower) for p in journalist_addressing_patterns
    )

    speaker_monologue_antipatterns = [
        r'\bя\s+(?:думаю|считаю|полагаю|уверен|знаю)\b',
        r'\b(?:дело\s+в\s+том|суть\s+в\s+том|проблема\s+в\s+том)\b',
        r'\b(?:во-первых|во-вторых|в-третьих)\b',
        r'\b(?:поэтому|следовательно|таким\s+образом)\b',
    ]

    has_speaker_monologue = any(
        re.search(p, text_lower) for p in speaker_monologue_antipatterns
    )

    return (word_count < 15 and 
            has_journalist_addressing and 
            not has_speaker_monologue)

def has_speaker_monologue_markers(text):
    """
    Проверяет наличие маркеров монолога Спикера

    Args:
        text: Текст для проверки

    Returns:
        bool: True если есть маркеры монолога Спикера
    """
    text_lower = text.lower()

    speaker_monologue_patterns = [
        r'\bя\s+(?:думаю|считаю|полагаю|уверен|убежден|убеждён|знаю|понимаю|вижу|представляю|предполагаю)\b',
        r'\b(?:у\s+меня|мне|меня|мной|мною|моё|моя|мои|мое|моего|моей|моих|моим|моими)\b',
        r'\b(?:дело\s+в\s+том|суть\s+в\s+том|проблема\s+в\s+том|вопрос\s+в\s+том|смысл\s+в\s+том)\b',
        r'\b(?:во-первых|во-вторых|в-третьих|в-четвертых|в-четвёртых|в-пятых)\b',
        r'\b(?:поэтому|следовательно|таким\s+образом|в\s+связи\s+с\s+этим|отсюда|из\s+этого\s+следует)\b',
        r'\b(?:на\s+мой\s+взгляд|по\s+моему\s+мнению|как\s+мне\s+кажется|я\s+бы\s+сказал|я\s+бы\s+отметил)\b',
        r'\bя\s+(?:могу|должен|хочу|буду|стал|начал|пытаюсь|стараюсь)\b',
    ]

    return any(re.search(p, text_lower) for p in speaker_monologue_patterns)

def get_monologue_duration_at_index(segments, end_index, speaker):
    """
    🔧 v16.9: Вычисляет длительность монолога спикера, заканчивающегося на end_index
    
    Args:
        segments: Список всех сегментов
        end_index: Индекс последнего сегмента монолога
        speaker: Спикер для проверки
    
    Returns:
        Длительность монолога в секундах (0 если нет монолога)
    """
    if end_index < 0 or end_index >= len(segments):
        return 0
    
    if segments[end_index].get('speaker') != speaker:
        return 0
    
    # Находим начало монолога
    monologue_start_idx = end_index
    for i in range(end_index, -1, -1):
        if segments[i].get('speaker') != speaker:
            monologue_start_idx = i + 1
            break
        if i == 0:
            monologue_start_idx = 0
    
    # Вычисляем длительность
    duration = (segments[end_index].get('end', 0) - 
               segments[monologue_start_idx].get('start', 0))
    return duration

def is_continuation_phrase(text):
    """
    🆕 v16.8: Проверяет, является ли фраза продолжением монолога
    
    Фразы типа "То есть", "В частности", "Кроме того" обычно продолжают
    предыдущую мысль, а не начинают новую тему журналиста.
    
    Args:
        text: Текст для проверки
    
    Returns:
        True если это фраза-продолжение
    """
    text_lower = text.lower().strip()
    
    continuation_patterns = [
        r'^то\s+есть\b',
        r'^в\s+частности\b',
        r'^кроме\s+того\b',
        r'^помимо\s+этого\b',
        r'^также\b',
        r'^более\s+того\b',
        r'^к\s+тому\s+же\b',
        r'^вдобавок\b',
        r'^при\s+этом\b',
        r'^однако\b',
        r'^но\b',
        r'^а\s+(?:также|еще|ещё)\b',
    ]
    
    return any(re.match(p, text_lower) for p in continuation_patterns)

# ═══════════════════════════════════════════════════════════════════════════
# ВЕСОВАЯ КЛАССИФИКАЦИЯ v15 + v16.13 FIX
# ═══════════════════════════════════════════════════════════════════════════

def apply_speaker_classification_v15(segments, speaker_surname, speaker_roles, debug=False):
    """
    v16.13: Весовая классификация спикеров с СИНХРОНИЗАЦИЕЙ raw_speaker_id
    
    🔥 v16.13 КРИТИЧЕСКИЙ FIX:
    - При изменении speaker ТАКЖЕ обновляется raw_speaker_id
    - Создан обратный маппинг speaker_roles (Исаев → SPEAKER_01)
    - Исправлен баг: TXT выводил старый speaker из-за несинхронизации
    - Синхронизация во всех 3 местах изменения speaker
    
    🔧 v16.9 ФИКС:
    - Continuation phrases теперь проверяются относительно ПРЕДЫДУЩЕГО спикера
    - "В частности" после длинного монолога Исаева → атрибутируется Исаеву
    - Исправлена логика get_monologue_duration_at_index()

    Args:
        segments: Список сегментов после merge_replicas()
        speaker_surname: Фамилия основного спикера
        speaker_roles: Dict SPEAKER_XX → роль (для обратной конвертации)
        debug: Если True, выводит детальную информацию

    Returns:
        (segments, stats) - модифицированные сегменты и статистика
    """
    
    # 🆕 v16.13: Создаём обратный маппинг speaker → raw_speaker_id
    reverse_roles = {}
    for raw_id, role in speaker_roles.items():
        reverse_roles[role] = raw_id
    
    if debug:
        print(f"\n🔄 v16.13: Обратный маппинг создан:")
        for role, raw_id in reverse_roles.items():
            print(f"   {role} → {raw_id}")

    # Паттерны для определения Журналиста
    JOURNALIST_PATTERNS = {
        'addressing': [
            (r'\b(расскажите|объясните|поясните|уточните|скажите)\b', 3),
            (r'\b(вы\s+(?:можете|знаете|помните|считаете|думаете))\b', 2),
            (r'\b(как\s+вы\s+(?:считаете|думаете|оцениваете))\b', 3),
            (r'\bпредставьтесь\b', 5),
            (r'\b(давайте|переходим|начнем|продолжим)\b', 2),
        ],
        'questions': [
            (r'\?$', 1),
            (r'^(как|почему|зачем|когда|где|кто|что)\s', 2),
            (r'\b(не\s+так|верно|правильно)\s*\?', 2),
        ],
        'commands': [
            (r'\b(смотрим|слушаем|отвечаем)\s+(?:на|в)', 2),
            (r'\bмы\s+(?:сейчас|теперь)\s+(?:отвечаем|говорим|обсуждаем)\b', 2),
        ],
    }

    # Паттерны для определения Спикера
    SPEAKER_PATTERNS = {
        'monologue': [
            (r'\b(у\s+меня|мне|я\s+(?:считаю|думаю|полагаю|помню))\b', 2),
            (r'\b(на\s+мой\s+взгляд|по\s+моему\s+мнению)\b', 3),
            (r'\b(моё|моя|мой|мои)\s+(?:мнение|опыт|исследование|работа)\b', 3),
        ],
        'facts': [
            (r'\b\d{4}\s*год', 1),
            (r'\b(?:операция|сражение|битва|фронт|армия)\b', 1),
        ],
    }

    # Защиты от ложных срабатываний
    PROTECTIONS = {
        'journalist_not_speaker': [
            (r'\bмы\s+(?:сейчас|теперь|тут|здесь)\s', -3),
            (r'\bвы\s+(?:представьтесь|расскажите|объясните)\b', -5),
        ],
    }

    def calculate_speaker_score(text, current_speaker):
        """Рассчитывает веса для определения правильного спикера"""
        text_lower = text.lower()
        journalist_score = 0
        speaker_score = 0
        details = []

        # Проверяем паттерны Журналиста
        for category, patterns in JOURNALIST_PATTERNS.items():
            for pattern, weight in patterns:
                if re.search(pattern, text_lower, re.I):
                    journalist_score += weight
                    details.append(f"J:{category}:+{weight}")

        # Проверяем паттерны Спикера
        for category, patterns in SPEAKER_PATTERNS.items():
            for pattern, weight in patterns:
                if re.search(pattern, text_lower, re.I):
                    speaker_score += weight
                    details.append(f"S:{category}:+{weight}")

        # Применяем защиты
        for pattern, weight in PROTECTIONS['journalist_not_speaker']:
            if re.search(pattern, text_lower, re.I):
                speaker_score += weight
                details.append(f"PROTECT:S:{weight}")

        return journalist_score, speaker_score, details

    # Статистика
    stats = {
        'total_checked': 0,
        'changed_to_journalist': 0,
        'changed_to_speaker': 0,
        'skipped_protections': 0,
        'skipped_monologue_context': 0,
        'continuation_phrases_fixed': 0,
        'raw_speaker_id_synced': 0,  # 🆕 v16.13
        'details': []
    }

    if debug:
        print("\n" + "="*80)
        print("🎯 v16.13: ВЕСОВАЯ КЛАССИФИКАЦИЯ + RAW_SPEAKER_ID SYNC")
        print("="*80)

    for i, seg in enumerate(segments):
        text = seg.get('text', '').strip()
        current_speaker = seg.get('speaker', '')
        time = seg.get('time', '00:00:00')
        word_count = len(text.split())

        # Пропускаем короткие сегменты и команды оператора
        if word_count < SPEAKER_CLASSIFICATION_MIN_WORDS or current_speaker == 'Оператор':
            continue

        stats['total_checked'] += 1

        # 🔧 v16.9: FIXED CONTINUATION PHRASE LOGIC
        # Проверяем, начинается ли текущий сегмент с continuation phrase
        if i > 0 and is_continuation_phrase(text):
            prev_seg = segments[i - 1]
            prev_speaker = prev_seg.get('speaker')
            
            # Проверяем длительность предыдущего монолога
            prev_monologue_duration = get_monologue_duration_at_index(segments, i - 1, prev_speaker)
            
            # Если предыдущий монолог длинный (>30s) или очень длинный (>60s)
            if prev_monologue_duration > 30:
                # Это продолжение ПРЕДЫДУЩЕГО спикера!
                if current_speaker != prev_speaker:
                    if debug:
                        print(f"\n  🔧 [{time}] CONTINUATION PHRASE FIX")
                        print(f"     {current_speaker} → {prev_speaker} (после монолога {prev_monologue_duration:.1f}s)")
                        print(f"     Текст: {text[:80]}...")
                    
                    seg['speaker'] = prev_speaker
                    # 🆕 v16.13: ОБНОВЛЯЕМ raw_speaker_id через обратный маппинг
                    seg['raw_speaker_id'] = reverse_roles.get(prev_speaker, seg.get('raw_speaker_id'))
                    
                    stats['continuation_phrases_fixed'] += 1
                    stats['raw_speaker_id_synced'] += 1  # 🆕 v16.13
                    stats['changed_to_speaker'] += 1 if prev_speaker != 'Журналист' else 0
                    stats['changed_to_journalist'] += 1 if prev_speaker == 'Журналист' else 0
                    continue
                else:
                    # Уже правильный спикер, просто защищаем
                    if debug:
                        print(f"\n  🛡️ [{time}] CONTINUATION PHRASE (уже верно)")
                        print(f"     Спикер: {current_speaker} (после монолога {prev_monologue_duration:.1f}s)")
                    stats['skipped_monologue_context'] += 1
                    continue

        j_score, s_score, details = calculate_speaker_score(text, current_speaker)

        # Определяем порог для изменения
        CONFIDENCE_THRESHOLD = SPEAKER_CLASSIFICATION_CONFIDENCE_THRESHOLD

        # Журналист → Спикер
        if current_speaker == 'Журналист' and s_score > j_score + CONFIDENCE_THRESHOLD:
            if debug:
                print(f"\n  🔄 [{time}] Журналист → {speaker_surname}")
                print(f"     Веса: J={j_score}, S={s_score}")
                print(f"     Паттерны: {', '.join(details)}")
                print(f"     Текст: {text[:80]}...")

            seg['speaker'] = speaker_surname
            # 🆕 v16.13: ОБНОВЛЯЕМ raw_speaker_id через обратный маппинг
            seg['raw_speaker_id'] = reverse_roles.get(speaker_surname, seg.get('raw_speaker_id'))
            
            stats['changed_to_speaker'] += 1
            stats['raw_speaker_id_synced'] += 1  # 🆕 v16.13
            stats['details'].append({
                'time': time,
                'from': 'Журналист',
                'to': speaker_surname,
                'j_score': j_score,
                's_score': s_score,
                'text': text[:100]
            })

        # Спикер → Журналист
        elif current_speaker == speaker_surname and j_score > s_score + CONFIDENCE_THRESHOLD:
            if debug:
                print(f"\n  🔄 [{time}] {speaker_surname} → Журналист")
                print(f"     Веса: J={j_score}, S={s_score}")
                print(f"     Паттерны: {', '.join(details)}")
                print(f"     Текст: {text[:80]}...")

            seg['speaker'] = 'Журналист'
            # 🆕 v16.13: ОБНОВЛЯЕМ raw_speaker_id через обратный маппинг
            seg['raw_speaker_id'] = reverse_roles.get('Журналист', seg.get('raw_speaker_id'))
            
            stats['changed_to_journalist'] += 1
            stats['raw_speaker_id_synced'] += 1  # 🆕 v16.13
            stats['details'].append({
                'time': time,
                'from': speaker_surname,
                'to': 'Журналист',
                'j_score': j_score,
                's_score': s_score,
                'text': text[:100]
            })

    if debug:
        print("="*80)
        print(f"✅ v16.13: Классификация завершена")
        print(f"   Всего проверено: {stats['total_checked']}")
        print(f"   Исправлено: {stats['changed_to_journalist'] + stats['changed_to_speaker']}")
        print(f"   • Журналист → Спикер: {stats['changed_to_speaker']}")
        print(f"   • Спикер → Журналист: {stats['changed_to_journalist']}")
        print(f"   • 🔧 Continuation phrases исправлено: {stats['continuation_phrases_fixed']}")
        print(f"   • 🆕 raw_speaker_id синхронизировано: {stats['raw_speaker_id_synced']}")
        print(f"   • Пропущено (защиты): {stats['skipped_monologue_context'] + stats['skipped_protections']}")
        print("="*80)
        print()

    return segments, stats
