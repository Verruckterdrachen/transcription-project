#!/usr/bin/env python3
"""
tests/test_regex_patterns.py - Unit tests для regex паттернов

v16.17: Regression tests для предотвращения багов типа v16.16

Запуск:
    pytest tests/test_regex_patterns.py -v
    pytest tests/test_regex_patterns.py::TestJournalistPhraseDetection -v
"""

import sys
sys.path.append('scripts')

import pytest
from corrections.boundary_fixer import (
    is_journalist_phrase,
    is_expert_phrase,
    is_continuation_phrase,
    is_question_announcement
)


class TestJournalistPhraseDetection:
    """v16.16: Тесты для определения журналистских фраз"""
    
    def test_positive_basic_markers(self):
        """Базовые журналистские маркеры ДОЛЖНЫ определяться"""
        assert is_journalist_phrase("вы можете объяснить") == True
        assert is_journalist_phrase("расскажите нам подробнее") == True
        assert is_journalist_phrase("объясните пожалуйста") == True
        assert is_journalist_phrase("давайте обсудим") == True
        assert is_journalist_phrase("давайте смотрим") == True
    
    def test_positive_question_patterns(self):
        """Вопросительные паттерны"""
        assert is_journalist_phrase("как вы считаете") == True
        assert is_journalist_phrase("почему вы выбрали") == True
        assert is_journalist_phrase("что вы думаете") == True
        assert is_journalist_phrase("когда вы начали") == True
    
    def test_false_positives_v16_16_word_boundary(self):
        """v16.16 BUG FIX: Слова содержащие 'вы' НЕ должны ловиться
        
        ROOT CAUSE: Regex r'вы\\s+' без word boundary \\b ловил 'вы ' внутри слов
        FIX: r'\\bвы\\s+' с word boundary
        """
        # Географические названия
        assert is_journalist_phrase("на восточном берегу Невы") == False
        assert is_journalist_phrase("из Невы в Ладожское озеро") == False
        
        # Слова с 'вы' внутри
        assert is_journalist_phrase("совы охотятся ночью") == False
        assert is_journalist_phrase("у кровы есть крыша") == False
        assert is_journalist_phrase("правы были все участники") == False
        assert is_journalist_phrase("называется так и так") == False
        assert is_journalist_phrase("травы лечебные") == False
        assert is_journalist_phrase("главы книги интересные") == False
    
    def test_edge_cases_positioning(self):
        """Пограничные случаи: позиция 'вы' в предложении"""
        # В конце предложения
        assert is_journalist_phrase("это были вы?") == True
        assert is_journalist_phrase("согласны ли вы?") == True
        
        # В начале предложения
        assert is_journalist_phrase("Вы уверены в этом?") == True
        assert is_journalist_phrase("Вы можете подтвердить?") == True
    
    def test_multiple_markers(self):
        """Несколько маркеров в одной фразе"""
        assert is_journalist_phrase("вы можете расскажите") == True
        assert is_journalist_phrase("давайте вы объясните") == True
    
    def test_empty_and_none(self):
        """Пустые входные данные"""
        assert is_journalist_phrase("") == False
        assert is_journalist_phrase("   ") == False
    
    def test_case_insensitivity(self):
        """Регистронезависимость"""
        assert is_journalist_phrase("ВЫ МОЖЕТЕ ОБЪЯСНИТЬ") == True
        assert is_journalist_phrase("Расскажите Подробнее") == True
        assert is_journalist_phrase("ДАВАЙТЕ ОБСУДИМ") == True


class TestExpertPhraseDetection:
    """Тесты для определения экспертных фраз"""
    
    def test_positive_opinion_markers(self):
        """Маркеры мнения эксперта"""
        assert is_expert_phrase("я считаю что это важно", "Исаев") == True
        assert is_expert_phrase("я думаю что здесь", "Исаев") == True
        assert is_expert_phrase("я полагаю что нужно", "Исаев") == True
    
    def test_positive_viewpoint_markers(self):
        """Маркеры точки зрения"""
        assert is_expert_phrase("на мой взгляд это правильно", "Исаев") == True
        assert is_expert_phrase("по моему мнению следует", "Исаев") == True
    
    def test_surname_detection_basic(self):
        """Фамилия эксперта в тексте"""
        assert is_expert_phrase("Исаев утверждает что", "Исаев") == True
        assert is_expert_phrase("как сказал Исаев ранее", "Исаев") == True
        assert is_expert_phrase("по словам Исаева", "Исаев") == True
    
    def test_surname_case_insensitive(self):
        """Фамилия независимо от регистра"""
        assert is_expert_phrase("исаев считает", "Исаев") == True
        assert is_expert_phrase("ИСАЕВ говорил", "Исаев") == True
    
    def test_wrong_surname(self):
        """Другая фамилия НЕ должна определяться"""
        assert is_expert_phrase("Петров считает", "Исаев") == False
        assert is_expert_phrase("как сказал Иванов", "Исаев") == False
    
    def test_no_surname_provided(self):
        """Если фамилия не указана"""
        # Должны работать только opinion markers
        assert is_expert_phrase("я считаю что", None) == True
        assert is_expert_phrase("на мой взгляд", None) == True
        # Но фамилия не должна ловиться
        assert is_expert_phrase("Исаев сказал", None) == False
    
    def test_empty_and_none(self):
        """Пустые входные данные"""
        assert is_expert_phrase("", "Исаев") == False
        assert is_expert_phrase("   ", "Исаев") == False


class TestContinuationPhraseDetection:
    """v16.10: Тесты для continuation phrases (продолжение мысли)"""
    
    def test_positive_basic_patterns(self):
        """Базовые continuation phrases"""
        assert is_continuation_phrase("То есть это важный момент") == True
        assert is_continuation_phrase("В частности стоит отметить") == True
        assert is_continuation_phrase("Кроме того необходимо") == True
        assert is_continuation_phrase("Также важно понимать") == True
    
    def test_positive_alternative_patterns(self):
        """Альтернативные паттерны"""
        assert is_continuation_phrase("Иными словами можно сказать") == True
        assert is_continuation_phrase("Другими словами это значит") == True
        assert is_continuation_phrase("Более того следует учесть") == True
        assert is_continuation_phrase("Помимо этого есть") == True
    
    def test_positive_logical_connectors(self):
        """Логические связки"""
        assert is_continuation_phrase("При этом стоит заметить") == True
        assert is_continuation_phrase("Однако есть нюансы") == True
        assert is_continuation_phrase("Тем не менее нужно") == True
        assert is_continuation_phrase("Впрочем это не единственное") == True
    
    def test_negative_not_continuation(self):
        """НЕ continuation phrases"""
        assert is_continuation_phrase("Это важный момент") == False
        assert is_continuation_phrase("Начнём с того что") == False
        assert is_continuation_phrase("Первое что нужно сказать") == False
    
    def test_beginning_of_sentence(self):
        """Continuation phrase должна быть В НАЧАЛЕ предложения"""
        # В начале - ДА
        assert is_continuation_phrase("То есть мы видим") == True
        # В середине/конце - НЕТ
        assert is_continuation_phrase("Мы видим то есть следующее") == False
    
    def test_case_insensitive(self):
        """Регистронезависимость"""
        assert is_continuation_phrase("ТО ЕСТЬ ЭТО ВАЖНО") == True
        assert is_continuation_phrase("В Частности Стоит") == True
    
    def test_empty_and_whitespace(self):
        """Пустые данные"""
        assert is_continuation_phrase("") == False
        assert is_continuation_phrase("   ") == False


class TestQuestionAnnouncementDetection:
    """v16.4: Тесты для определения анонсов вопросов"""
    
    def test_positive_announcements(self):
        """Анонсы вопросов ДОЛЖНЫ определяться"""
        assert is_question_announcement("Следующий вопрос про Ленинград") == True
        assert is_question_announcement("Ещё вопрос о блокаде") == True
        assert is_question_announcement("Другой вопрос о пятачке") == True
    
    def test_short_announcements_only(self):
        """Только КОРОТКИЕ анонсы (<20 слов)"""
        # Короткий - ДА
        assert is_question_announcement("Следующий вопрос про войну") == True
        
        # Длинный - НЕТ (это уже полный вопрос)
        long_question = "Следующий вопрос про войну и про то как именно происходили события в тот период времени"
        assert is_question_announcement(long_question) == False
    
    def test_not_announcements(self):
        """НЕ анонсы"""
        assert is_question_announcement("Как проходила война?") == False
        assert is_question_announcement("Расскажите про Ленинград") == False
    
    def test_empty_and_none(self):
        """Пустые данные"""
        assert is_question_announcement("") == False
        assert is_question_announcement("   ") == False


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# REGRESSION TESTS (защита от известных багов)
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

class TestRegressionBugs:
    """Коллекция regression tests для известных багов"""
    
    def test_v16_16_nevy_false_positive(self):
        """v16.16: 'Невы' определялась как журналистская фраза
        
        Симптом: 00:01:47 ошибочно переатрибутирован Журналисту
        Предложение: "То есть с небольшого пространства земли на восточном берегу Невы..."
        ROOT CAUSE: regex r'вы\\s+' без \\b
        FIX: добавлен word boundary
        """
        problematic_sentence = "То есть с небольшого пространства земли на восточном берегу Невы предполагалось нанести глубокий удар"
        
        # НЕ должна определяться как журналистская
        assert is_journalist_phrase(problematic_sentence) == False
        
        # ДОЛЖНА определяться как continuation
        assert is_continuation_phrase(problematic_sentence) == True
    
    def test_v16_10_continuation_in_monologue(self):
        """v16.10: Continuation phrase внутри монолога НЕ должна вызывать split
        
        Если continuation phrase внутри длинного монолога (>80 слов),
        она должна продолжать текущего спикера
        """
        # Это проверяется в integration tests, здесь только unit test для is_continuation
        assert is_continuation_phrase("То есть здесь важно понимать") == True
    
    # Добавляй сюда новые regression tests для каждого найденного бага!


# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
# PYTEST CONFIGURATION
# ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━

if __name__ == "__main__":
    # Запуск через: python tests/test_regex_patterns.py
    pytest.main([__file__, "-v", "--tb=short"])