#!/usr/bin/env python3
"""
Simulation: load_vocab.py — white-list filtering + frequency scoring

Тестируем:
1. White-list паттерны (Title Case, техника, фамилии, воинские части)
2. Частотный scoring (вес 1-5)
3. Дедупликация case-insensitive
4. Фильтрация мусора (предложения, глаголы)

Vocab input: 85,904 термина из clean_dicts.py
Expected output: ~70K-80K после white-list фильтра
"""

import re
from collections import Counter

# ═══════════════════════════════════════════════════════════════════
# LOAD_VOCAB.PY — WHITE-LIST ФИЛЬТРЫ
# ═══════════════════════════════════════════════════════════════════

# Стоп-слова для фильтрации (расширенный список)
STOPWORDS = {
    # Местоимения
    'я', 'ты', 'он', 'она', 'оно', 'мы', 'вы', 'они',
    'мой', 'твой', 'его', 'её', 'наш', 'ваш', 'их',
    'этот', 'тот', 'такой', 'весь', 'сам', 'самый',
    # Союзы
    'и', 'а', 'но', 'да', 'или', 'либо', 'то', 'если', 'что', 'как',
    'чтобы', 'когда', 'пока', 'хотя', 'словно', 'будто',
    # Предлоги
    'в', 'на', 'с', 'к', 'по', 'из', 'о', 'у', 'от', 'до', 'за', 'над',
    'под', 'при', 'про', 'через', 'без', 'для', 'ради', 'между',
    # Частицы
    'не', 'ни', 'бы', 'ли', 'же', 'ведь', 'вот', 'даже', 'лишь', 'только',
    # Наречия (частые)
    'очень', 'здесь', 'там', 'так', 'где', 'куда', 'откуда', 'когда',
    'всегда', 'никогда', 'часто', 'редко', 'можно', 'нужно', 'надо'
}

def is_proper_noun_pattern(term):
    """
    Имена собственные: Title Case, 2+ слова с заглавными
    
    Примеры:
    ✅ Георгий Жуков, Операция Багратион, 1-й Белорусский фронт
    ❌ был очень важен, начал наступление
    """
    words = term.split()
    
    # Минимум 1 слово с заглавной
    has_capital = any(w[0].isupper() for w in words if w and w[0].isalpha())
    if not has_capital:
        return False
    
    # Проверка Title Case (первое слово заглавное)
    if words[0][0].isupper():
        return True
    
    # Цифра в начале + Title Case (1-й Белорусский)
    if words[0][0].isdigit() and len(words) > 1 and words[1][0].isupper():
        return True
    
    return False

def is_military_rank_pattern(term):
    """
    Воинское звание + имя/фамилия
    
    Примеры:
    ✅ Маршал Жуков, генерал Говоров, командир Симоняк
    ❌ маршал был назначен
    """
    ranks = [
        'маршал', 'генерал', 'полковник', 'подполковник', 'майор',
        'капитан', 'лейтенант', 'сержант', 'ефрейтор', 'рядовой',
        'командир', 'командующий', 'начальник'
    ]
    
    words = term.lower().split()
    if len(words) < 2:
        return False
    
    # Первое слово — звание, второе — заглавное
    if words[0] in ranks and term.split()[1][0].isupper():
        return True
    
    return False

def is_military_unit_pattern(term):
    """
    Воинские части: номер + воинский термин
    
    Примеры:
    ✅ 86-я дивизия, 1-й фронт, 267-я бригада, 5-я армия
    ❌ 86-я была создана (есть глагол)
    """
    # Паттерн: цифры + дефис/тире + "я/й/е" + воинский термин
    pattern = r'^\d+-[яйе]\s+(дивизия|бригада|полк|батальон|рота|взвод|армия|корпус|фронт|флот|эскадра)'
    return bool(re.match(pattern, term, re.IGNORECASE))

def is_technical_term(term):
    """
    Техника с цифрами и дефисами
    
    Примеры:
    ✅ Т-34, Пе-2, Фокке-Вульф-190, Ил-2
    ❌ 190-я дивизия (это номер части)
    """
    # Паттерн: буквы + дефис + цифры ИЛИ Title-Title-цифры
    pattern = r'^[А-ЯЁ][а-яё]*-\d+$|^[A-Z][a-z]+-[A-Z][a-z]+-?\d*$'
    return bool(re.match(pattern, term))

def is_abbreviation(term):
    """
    Аббревиатуры: ≤4 символа, uppercase
    
    Примеры:
    ✅ СССР, РККА, ГДР, НКО
    ❌ БЫЛО (не аббревиатура)
    """
    if len(term) > 4:
        return False
    
    if term.isupper() and term.isalpha():
        # Исключаем стоп-слова uppercase
        if term.lower() in STOPWORDS:
            return False
        return True
    
    return False

def is_toponym_pattern(term):
    """
    Топонимы с характерными окончаниями
    
    Примеры:
    ✅ Приладожье, Волховский, Ленинград, Москва
    ❌ говорил (окончание -ил)
    """
    # Окончания топонимов
    endings = [
        'град', 'бург', 'полье', 'ладожье', 'поволжье',
        'ский', 'ская', 'ское',  # Волховский фронт
        'ино', 'ово', 'ево'       # деревни/сёла
    ]
    
    if not term[0].isupper():
        return False
    
    term_lower = term.lower()
    return any(term_lower.endswith(end) for end in endings)

def contains_verb_in_middle(term):
    """
    Фильтр глаголов в середине фразы
    
    Примеры:
    ❌ "был очень важен", "начал наступление", "мог догнать"
    ✅ "Операция Багратион", "1-й Белорусский фронт"
    """
    verb_patterns = [
        r'\b(был|были|была|было)\b',
        r'\b(начал|начала|начали|начало)\b',
        r'\b(стал|стала|стали|стало)\b',
        r'\b(мог|могла|могли|могло)\b',
        r'\b(имел|имела|имели|имело)\b'
    ]
    
    for pattern in verb_patterns:
        if re.search(pattern, term, re.IGNORECASE):
            return True
    
    return False

def is_sentence_fragment(term):
    """
    Фрагменты предложений (>5 слов или есть глаголы)
    
    Примеры:
    ❌ "Однако эта цифра была не очень впечатляющей"
    ✅ "Операция Багратион"
    """
    words = term.split()
    
    # Слишком длинный термин
    if len(words) > 5:
        return True
    
    # Есть глагол в середине
    if contains_verb_in_middle(term):
        return True
    
    return False

def load_vocab_whitelist(terms):
    """
    White-list фильтрация терминов
    
    Args:
        terms: список строк из combined_all.txt
    
    Returns:
        список отфильтрованных терминов
    """
    result = []
    stats = {
        'proper_noun': 0,
        'military_rank': 0,
        'military_unit': 0,
        'technical': 0,
        'abbreviation': 0,
        'toponym': 0,
        'rejected_sentence': 0,
        'rejected_verb': 0,
        'rejected_stopword': 0
    }
    
    for term in terms:
        term = term.strip()
        if not term:
            continue
        
        # Фильтр 1: стоп-слова (одно слово)
        if len(term.split()) == 1 and term.lower() in STOPWORDS:
            stats['rejected_stopword'] += 1
            continue
        
        # Фильтр 2: фрагменты предложений
        if is_sentence_fragment(term):
            stats['rejected_sentence'] += 1
            continue
        
        # Фильтр 3: глаголы в середине
        if contains_verb_in_middle(term):
            stats['rejected_verb'] += 1
            continue
        
        # White-list паттерны (порядок важен!)
        if is_military_unit_pattern(term):
            stats['military_unit'] += 1
            result.append(term)
        elif is_proper_noun_pattern(term):
            stats['proper_noun'] += 1
            result.append(term)
        elif is_military_rank_pattern(term):
            stats['military_rank'] += 1
            result.append(term)
        elif is_technical_term(term):
            stats['technical'] += 1
            result.append(term)
        elif is_abbreviation(term):
            stats['abbreviation'] += 1
            result.append(term)
        elif is_toponym_pattern(term):
            stats['toponym'] += 1
            result.append(term)
    
    return result, stats

def calculate_frequency_scores(terms, parsed_corpus_paths=None):
    """
    Подсчёт частоты терминов → вес 1-5
    
    Args:
        terms: список отфильтрованных терминов
        parsed_corpus_paths: пути к data/parsed/*/*.txt (опционально)
    
    Returns:
        dict {term: weight}
    """
    # Если есть корпус — подсчитываем частоту
    if parsed_corpus_paths:
        freq_counter = Counter()
        # TODO: читать файлы из data/parsed/ и считать вхождения
        # Пока — mock данные
        for term in terms:
            # Stub: случайная частота 1-100
            freq_counter[term.lower()] = len(term) % 100 + 1
    else:
        # Без корпуса — все термины вес 1
        freq_counter = {term.lower(): 1 for term in terms}
    
    # Маппинг частоты → вес 1-5
    scores = {}
    max_freq = max(freq_counter.values()) if freq_counter else 1
    
    for term in terms:
        freq = freq_counter.get(term.lower(), 1)
        
        # Логарифмическая шкала
        if freq >= max_freq * 0.5:
            weight = 5
        elif freq >= max_freq * 0.2:
            weight = 4
        elif freq >= max_freq * 0.05:
            weight = 3
        elif freq >= max_freq * 0.01:
            weight = 2
        else:
            weight = 1
        
        scores[term] = weight
    
    return scores

# ═══════════════════════════════════════════════════════════════════
# TEST CASES
# ═══════════════════════════════════════════════════════════════════

TEST_TERMS = [
    # ✅ KEEP — имена собственные
    "Георгий Жуков",
    "Операция Багратион",
    "1-й Белорусский фронт",
    "Симоняк",
    "Говоров",
    "Приладожье",
    "Волховский",
    "Шлиссельбург",
    
    # ✅ KEEP — техника
    "Фокке-Вульф-190",
    "Пе-2",
    "Ил-2",
    "Т-34",
    
    # ✅ KEEP — звания
    "Маршал Жуков",
    "генерал Говоров",
    "командир Симоняк",
    
    # ✅ KEEP — аббревиатуры
    "СССР",
    "РККА",
    "ГДР",
    
    # ✅ KEEP — топонимы
    "Ленинград",
    "Москва",
    "Ладога",
    
    # ✅ KEEP — воинские части
    "86-я дивизия",
    
    # ❌ REJECT — фрагменты предложений
    "был очень важен",
    "начал наступление",
    "мог догнать",
    "Однако эта цифра была не очень впечатляющей",
    
    # ❌ REJECT — стоп-слова
    "очень",
    "всегда",
    "только",
    
    # ❌ REJECT — глаголы в середине
    "Фокке-Вульф был опасен",
    "самолёты были равны",
    
    # Edge cases
    "плацдарм",  # ❌ военный термин (lowercase, не проходит фильтр)
    "Искра",  # ✅ операция (Title Case)
]

EXPECTED_KEEP = [
    "Георгий Жуков",
    "Операция Багратион",
    "1-й Белорусский фронт",
    "Симоняк",
    "Говоров",
    "Приладожье",
    "Волховский",
    "Шлиссельбург",
    "Фокке-Вульф-190",
    "Пе-2",
    "Ил-2",
    "Т-34",
    "Маршал Жуков",
    "генерал Говоров",
    "командир Симоняк",
    "СССР",
    "РККА",
    "ГДР",
    "Ленинград",
    "Москва",
    "Ладога",
    "86-я дивизия",
    "Искра",
]

EXPECTED_REJECT = [
    "был очень важен",
    "начал наступление",
    "мог догнать",
    "Однако эта цифра была не очень впечатляющей",
    "очень",
    "всегда",
    "только",
    "Фокке-Вульф был опасен",
    "самолёты были равны",
    "плацдарм",
]

# ═══════════════════════════════════════════════════════════════════
# RUN SIMULATION
# ═══════════════════════════════════════════════════════════════════

def run_simulation():
    """Запуск симуляции white-list фильтра"""
    print("=" * 70)
    print("SIMULATION: load_vocab.py — white-list filtering")
    print("=" * 70)
    
    # Тест 1: White-list фильтрация
    print("\n🔍 ТЕСТ 1: White-list фильтрация")
    filtered, stats = load_vocab_whitelist(TEST_TERMS)
    
    print(f"\n📊 Статистика:")
    print(f"   Входных терминов:       {len(TEST_TERMS)}")
    print(f"   После white-list:       {len(filtered)}")
    print(f"   Proper nouns:           {stats['proper_noun']}")
    print(f"   Military ranks:         {stats['military_rank']}")
    print(f"   Military units:         {stats['military_unit']}")
    print(f"   Technical terms:        {stats['technical']}")
    print(f"   Abbreviations:          {stats['abbreviation']}")
    print(f"   Toponyms:               {stats['toponym']}")
    print(f"   Rejected (sentences):   {stats['rejected_sentence']}")
    print(f"   Rejected (verbs):       {stats['rejected_verb']}")
    print(f"   Rejected (stopwords):   {stats['rejected_stopword']}")
    
    # Проверка KEEP
    keep_errors = []
    for term in EXPECTED_KEEP:
        if term not in filtered:
            keep_errors.append(f"❌ MISSING: '{term}' должен быть в результате")
    
    # Проверка REJECT
    reject_errors = []
    for term in EXPECTED_REJECT:
        if term in filtered:
            reject_errors.append(f"❌ FALSE POSITIVE: '{term}' не должен быть в результате")
    
    # Результат теста 1
    if not keep_errors and not reject_errors:
        print("\n✅ ТЕСТ 1: WHITE-LIST — GREEN")
    else:
        print("\n❌ ТЕСТ 1: WHITE-LIST — RED")
        for err in keep_errors + reject_errors:
            print(f"   {err}")
    
    # Тест 2: Frequency scoring
    print("\n🔍 ТЕСТ 2: Frequency scoring")
    scores = calculate_frequency_scores(filtered)
    
    print(f"\n📊 Примеры весов:")
    for term in list(scores.keys())[:10]:
        print(f"   {term}: {scores[term]}")
    
    # Проверка: все веса в диапазоне 1-5
    invalid_scores = [t for t, w in scores.items() if w < 1 or w > 5]
    if not invalid_scores:
        print("\n✅ ТЕСТ 2: FREQUENCY SCORING — GREEN")
    else:
        print("\n❌ ТЕСТ 2: FREQUENCY SCORING — RED")
        print(f"   Некорректные веса: {invalid_scores}")
    
    # Итоговая статистика
    print("\n" + "=" * 70)
    total_tests = 2
    passed_tests = (
        (len(keep_errors) == 0 and len(reject_errors) == 0) +
        (len(invalid_scores) == 0)
    )
    print(f"ИТОГО: {passed_tests}/{total_tests} GREEN")
    print("=" * 70)
    
    return passed_tests == total_tests

if __name__ == "__main__":
    success = run_simulation()
    exit(0 if success else 1)
