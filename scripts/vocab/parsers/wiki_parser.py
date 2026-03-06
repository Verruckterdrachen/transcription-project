#!/usr/bin/env python3
"""
scripts/vocab/parsers/wiki_parser.py
Парсер Wikipedia (ru + en) для словарей ВОВ/ВМВ.

Стратегия:
  1. Wikipedia REST API (action=parse&prop=text) → чистый HTML
  2. Обработка redirects: если API вернул redirect → запрос реальной страницы
  3. UNIVERSAL CONTENT WALKER: обходим ВСЕ текстовые элементы + <a> теги
  4. ru.wikipedia: 
     - links (<a href>) — самый точный источник терминов
     - паттерны militera_parser (rank_names, unit_names, quoted)
     - прямые термины из коротких элементов
  5. en.wikipedia: кириллица из скобок + useful_latin (техника/аббревиатуры)
  6. Нормализация: убираем [[...]], сноски[1], скобки кроме латиницы

FIX V5: обработка Wikipedia redirects (двухэтапный запрос)

Запуск:
  python scripts/vocab/parsers/wiki_parser.py \
      --url "https://ru.wikipedia.org/wiki/Наступательная_операция_на_реке_Миус" \
      --category 7 \
      --output-dir data/parsed
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from urllib.parse import urlparse, unquote

from bs4 import BeautifulSoup

sys.path.insert(0, str(Path(__file__).resolve().parents[3]))

from scripts.vocab.parsers.base_parser import BaseParser
from scripts.vocab.utils import (
    fetch_with_retry,
    get_default_rate_limiter,
    make_session,
    setup_logger,
)

logger = setup_logger("parser.wiki")

# ─────────────────────────────────────────────
# КОНСТАНТЫ
# ─────────────────────────────────────────────

WIKI_API = "https://{lang}.wikipedia.org/w/api.php"

WIKI_API_PARAMS = {
    "action": "parse",
    "prop": "text",
    "disablelimitreport": "1",
    "disableeditsection": "1",
    "disabletoc": "1",
    "redirects": "1",
    "format": "json",
}

MIN_TERM_LEN = 3
MAX_TERM_LEN = 80
MAX_TERM_WORDS = 6  # максимум слов в прямом термине

_RE_WIKI_LINK   = re.compile(r"\[\[.*?\]\]")
_RE_FOOTNOTE    = re.compile(r"\[\d+\]")
_RE_PARENS_RU   = re.compile(r"\([^A-Za-z()]*?\)")
_RE_PARENS_KEEP = re.compile(r"\([A-Za-z][^()]*?\)")
_RE_DIGITS_ONLY = re.compile(r"^\d[\d\s\-–—.,]*$")
_RE_SPACES      = re.compile(r"\s{2,}")
_RE_HTML_ENTITY = re.compile(r"&[a-zA-Z]+;|&#\d+;")
_RE_CYRILLIC    = re.compile(r"[А-ЯЁа-яё]{2,}")

# ─────────────────────────────────────────────
# ВСПОМОГАТЕЛЬНЫЕ ФУНКЦИИ
# ─────────────────────────────────────────────

def _get_lang(url: str) -> str:
    host = urlparse(url).netloc.lower()
    return host.split(".")[0]


def _get_page_title(url: str) -> str:
    path = urlparse(url).path
    title = path.split("/wiki/", 1)[-1]
    return unquote(title)


def _clean_term(raw: str) -> str | None:
    t = raw.strip()
    t = _RE_HTML_ENTITY.sub(" ", t)
    t = _RE_WIKI_LINK.sub("", t)
    t = _RE_FOOTNOTE.sub("", t)

    latin_brackets: list[str] = []

    def _stash_latin(m: re.Match) -> str:
        latin_brackets.append(m.group(0))
        return f"\x00LAT{len(latin_brackets) - 1}\x00"

    t = _RE_PARENS_KEEP.sub(_stash_latin, t)
    t = _RE_PARENS_RU.sub("", t)

    for i, bracket in enumerate(latin_brackets):
        t = t.replace(f"\x00LAT{i}\x00", bracket)

    t = t.replace("—", " ").replace("–", " ").replace("«", "").replace("»", "")
    t = _RE_SPACES.sub(" ", t).strip().strip(".,;:—–")

    if not t:
        return None
    if len(t) < MIN_TERM_LEN or len(t) > MAX_TERM_LEN:
        return None
    if _RE_DIGITS_ONLY.match(t):
        return None
    if not re.search(r"[А-ЯЁа-яёA-Za-z]", t):
        return None

    t = _normalize_caps(t)

    return t

def _normalize_caps(text: str) -> str:
    """
    Нормализует КАПСЛОК в именах.
    'ВОРОШИЛОВ КЛИМЕНТ' → 'Ворошилов Климент'

    Правила:
    - Слово целиком в верхнем регистре И только буквы И длина > 4 → capitalize()
    - Аббревиатуры ≤ 4 символов (ГДР, СССР, ЧССР, НКВД) — не трогаем
    - Смешанный регистр (СБД-2, Т-34) — не трогаем
    """
    words = text.split()
    result = []
    for w in words:
        if w.isupper() and w.isalpha() and len(w) > 4:
            result.append(w.capitalize())
        else:
            result.append(w)
    return " ".join(result)

def _dedupe_ordered(terms: list[str]) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for t in terms:
        key = t.lower()
        if key not in seen:
            seen.add(key)
            result.append(t)
    return result


def _is_cyrillic_term(term: str) -> bool:
    """Возвращает True если термин содержит кириллицу."""
    return bool(_RE_CYRILLIC.search(term))

_RE_HAS_DIGIT  = re.compile(r"\d")
_RE_ROMAN_NUM  = re.compile(r"\b(I{1,3}|IV|VI{0,3}|IX|X{1,3}XI{0,2}|XII)\b")
_RE_ALL_LATIN = re.compile(r"^[A-Za-z\d\s\-\.\/]+$")


_LATIN_STOPWORDS = {
    "timeline", "bibliography", "contents", "references", "notes",
    "see also", "further reading", "external links", "gallery",
    "sources", "footnotes", "appendix", "index", "overview",
}

_RE_YEARS_RANGE = re.compile(r"^[\d\s\-–andto]+$", re.IGNORECASE)


def _is_useful_latin(term: str) -> bool:
    """
    Латинский термин полезен ТОЛЬКО если это обозначение техники/аббревиатура:
      ✅ содержит цифры + буквы → Panzer-IV, Bf-109, Ju-87 (не просто год)
      ✅ содержит римские числа → Tiger I, Panzer III
      ✅ одно слово ≤ 20 chr, не служебное → StuG, Wehrmacht, Waffen-SS

    ❌ служебные слова → Timeline, Bibliography
    ❌ строки из цифр/годов → 1935 1940 and 1943, 1941-1945
    ❌ 2+ слова без цифр/римских → Georgy Zhukov
    """
    if not _RE_ALL_LATIN.match(term):
        return False

    if term.lower().strip() in _LATIN_STOPWORDS:
        return False

    if _RE_YEARS_RANGE.match(term):
        return False

    if _RE_HAS_DIGIT.search(term) and re.search(r"[A-Za-z]", term):
        return True

    if _RE_ROMAN_NUM.search(term):
        return True

    words = term.split()
    if len(words) == 1 and len(term) <= 20:
        return True

    return False

# ─────────────────────────────────────────────
# FIX V4: ИЗВЛЕЧЕНИЕ ИЗ <a> ТЕГОВ
# ─────────────────────────────────────────────

_RE_CYRILLIC_IN_PARENS = re.compile(
    r"\(\s*([А-ЯЁа-яё][А-ЯЁа-яё\s\-\.]{3,})\s*\)"
)

def _extract_from_links(soup: BeautifulSoup, lang: str) -> list[str]:
    """
    FIX V4: извлекает термины из <a> тегов основного контента.
    
    Wikipedia: каждая ссылка = намеренно выделенный термин.
    Это САМЫЙ ТОЧНЫЙ источник — ловит:
    - топонимы (Оппельн, Ратибор, Бреслау)
    - имена без званий (Шёрнер, Конев)
    - любые именованные сущности
    
    Берём:
    - text content ссылки (видимый текст)
    - атрибут title (полное имя: "Шёрнер, Фердинанд" → "Фердинанд Шёрнер")
    
    Пропускаем:
    - служебные ссылки (Special:, Help:, File:, Category:)
    - навигационные блоки (уже decompose)
    """
    terms: list[str] = []
    
    for a in soup.select("a[href]"):
        href = a.get("href", "")
        
        # Пропускаем не-wiki ссылки
        if not href.startswith("/wiki/"):
            continue
        
        # Пропускаем служебные страницы
        skip_prefixes = (
            "/wiki/Special:", "/wiki/Help:", "/wiki/File:",
            "/wiki/Wikipedia:", "/wiki/Категория:", "/wiki/Шаблон:",
            "/wiki/Обсуждение:", "/wiki/Участник:", "/wiki/Category:",
            "/wiki/Template:", "/wiki/Portal:",
        )
        if any(href.startswith(p) for p in skip_prefixes):
            continue
        
        # 1. Берём text content ссылки (видимый текст)
        link_text = a.get_text(" ", strip=True)
        if link_text:
            term = _clean_term(link_text)
            if term:
                if lang == "ru" and _is_cyrillic_term(term):
                    terms.append(term)
                elif lang == "en" and _is_useful_latin(term):
                    terms.append(term)
        
        # 2. Берём title атрибут (часто более полный: "Шёрнер, Фердинанд")
        title_attr = a.get("title", "").strip()
        if title_attr and title_attr != link_text:
            # "Фамилия, Имя" → "Имя Фамилия"
            if ", " in title_attr:
                parts = title_attr.split(", ", 1)
                if len(parts) == 2:
                    title_attr = f"{parts[1]} {parts[0]}"
            
            title_term = _clean_term(title_attr)
            if title_term:
                if lang == "ru" and _is_cyrillic_term(title_term):
                    terms.append(title_term)
                elif lang == "en" and _is_useful_latin(title_term):
                    terms.append(title_term)
    
    return terms

# ─────────────────────────────────────────────
# FIX V4: УНИВЕРСАЛЬНЫЙ CONTENT WALKER
# ─────────────────────────────────────────────

def _extract_from_elements(soup: BeautifulSoup, lang: str) -> list[str]:
    """
    FIX V4: УНИВЕРСАЛЬНЫЙ экстрактор — обходит ВСЕ текстовые элементы статьи.
    
    Стратегия:
    1. Удаляем навигацию/служебные блоки
    2. Для каждого текстового элемента (<p>, <li>, <td>, <th>, <h2>, <h3>):
       - ru: применяем паттерны (rank_names, unit_names, quoted) + прямые термины
       - en: кириллица из скобок + useful_latin
    3. Извлекаем ВСЕ вложенные элементы рекурсивно
    """
    from scripts.vocab.parsers.militera_parser import (
        _extract_rank_names,
        _extract_unit_names,
        _extract_quoted_terms,
    )
    
    terms: list[str] = []
    
    # Обходим ВСЕ текстовые контейнеры
    # FIX: используем "ul li" вместо "ul > li" — включает вложенные списки
    text_elements = soup.select(
        "p, "              # параграфы (основной текст статьи)
        "ul li, "          # списки (ВСЕ li, включая вложенные) ← FIX!
        "ol li, "          # нумерованные списки
        "td, th, "         # ячейки таблиц (включая infobox)
        "h2, h3, "         # заголовки секций
        ".infobox td, "    # явно infobox
        ".vevent td"       # карточки событий
    )
    
    for elem in text_elements:
        # Берём текст ВСЕГО элемента со всеми вложенными тегами
        raw_text = elem.get_text(" ", strip=True)
        
        if not raw_text or len(raw_text) < MIN_TERM_LEN:
            continue
        
        if lang == "ru":
            # Применяем паттерны из militera_parser (ловят имена, формирования)
            terms.extend(_extract_rank_names(raw_text))
            terms.extend(_extract_unit_names(raw_text))
            terms.extend(_extract_quoted_terms(raw_text))
            
            # Также пробуем извлечь как готовый термин (короткие элементы)
            # Отрезаем описания после " — ", " - ", " – "
            clean_text = raw_text
            for sep in (" — ", " - ", " – "):
                if sep in clean_text:
                    clean_text = clean_text.split(sep)[0]
                    break
            
            term = _clean_term(clean_text)
            if term and len(term.split()) <= MAX_TERM_WORDS:
                terms.append(term)
        
        elif lang == "en":
            # Кириллица из скобок (приоритет)
            for m in _RE_CYRILLIC_IN_PARENS.finditer(raw_text):
                term = _clean_term(m.group(1))
                if term and len(term) >= 4:
                    terms.append(term)
            
            # Useful latin (техника/аббревиатуры)
            clean_text = raw_text
            for sep in (" — ", " - ", " – "):
                if sep in clean_text:
                    clean_text = clean_text.split(sep)[0]
                    break
            
            term = _clean_term(clean_text)
            if term and _is_useful_latin(term):
                terms.append(term)
    
    return terms

def _extract_all_content(soup: BeautifulSoup, lang: str) -> list[str]:
    """
    Полная экстракция из статьи:
    1. Удаляем служебные блоки
    2. Извлекаем из <a> тегов (САМЫЙ ТОЧНЫЙ источник)
    3. Извлекаем из текстовых элементов (паттерны + прямые термины)
    4. Дедупликация
    """
    # Удаляем служебные блоки (навигация, сноски, метаданные)
    for noise in soup.select(
        "nav, .navbox, .reflist, .reference, "
        "script, style, .printfooter, .catlinks, "
        "#toc, .mw-jump-link, .mw-editsection"
    ):
        noise.decompose()
    
    # 1. Извлекаем из <a> тегов (топонимы, имена без званий)
    link_terms = _extract_from_links(soup, lang)
    
    # 2. Извлекаем из текстовых элементов (паттерны + прямые термины)
    element_terms = _extract_from_elements(soup, lang)
    
    # Объединяем + дедупликация
    all_terms = link_terms + element_terms
    return _dedupe_ordered(all_terms)

# ─────────────────────────────────────────────
# WIKI PARSER
# ─────────────────────────────────────────────

class WikiParser(BaseParser):
    """
    Парсер Wikipedia (ru + en).

    FIX V5: обработка Wikipedia redirects + универсальный content walker + извлечение из <a> тегов
    """

    def fetch(self) -> str:
        lang = _get_lang(self.url)
        title = _get_page_title(self.url)
        api_url = WIKI_API.format(lang=lang)
        params = {**WIKI_API_PARAMS, "page": title}

        self.logger.info(f"Wikipedia API → lang={lang}, title={title!r}")

        from scripts.vocab.utils import get_cached, save_cache
        cached = get_cached(self.url)
        if cached is not None:
            self.logger.info(f"fetch → cache hit ({len(cached):,} символов)")
            return cached

        self.rate_limiter.wait(self.domain)
        resp = self.session.get(api_url, params=params, timeout=self.timeout)
        resp.raise_for_status()
        data = resp.json()

        if "error" in data:
            raise ValueError(
                f"Wikipedia API error: {data['error'].get('info', data['error'])}"
            )
        if "parse" not in data:
            raise ValueError(f"Wikipedia API: неожиданный ответ для {title!r}")

        # FIX V5: обработка redirects
        # Если API вернул redirect, парсим реальный title и делаем второй запрос
        parse_data = data["parse"]
        html = parse_data["text"]["*"]
        
        # Проверяем на короткий HTML (признак redirect)
        if len(html) < 5000:
            # Ищем реальный title в redirects или в самом HTML
            redirected_title = None
            
            # Способ 1: проверяем redirects в JSON
            if "redirects" in parse_data:
                redirected_title = parse_data["redirects"][-1]["to"]
                self.logger.info(f"redirect обнаружен в JSON: {title!r} → {redirected_title!r}")
            
            # Способ 2: парсим HTML на наличие текста "(перенаправлено с"
            elif "перенаправлено с" in html.lower() or "redirected from" in html.lower():
                # Извлекаем реальный title из HTML
                soup = BeautifulSoup(html, "html.parser")
                # Ищем первую ссылку в контенте (обычно это цель redirect)
                first_link = soup.select_one("a[href^='/wiki/']")
                if first_link:
                    href = first_link.get("href", "")
                    redirected_title = href.split("/wiki/", 1)[-1]
                    self.logger.info(f"redirect обнаружен в HTML: {title!r} → {redirected_title!r}")
            
            # Если нашли redirect — делаем второй запрос
            if redirected_title:
                self.logger.info(f"fetch → перезапрос реальной страницы: {redirected_title!r}")
                params["page"] = redirected_title
                self.rate_limiter.wait(self.domain)
                resp = self.session.get(api_url, params=params, timeout=self.timeout)
                resp.raise_for_status()
                data = resp.json()
                
                if "parse" in data:
                    html = data["parse"]["text"]["*"]
                    self.logger.info(f"fetch OK (после redirect) — {len(html):,} символов")
                else:
                    self.logger.warning(f"⚠️ Не удалось получить реальную страницу после redirect")
            else:
                self.logger.warning(
                    f"⚠️ HTML слишком короткий ({len(html)} символов), "
                    f"но redirect не обнаружен — возможно stub-статья"
                )
        else:
            self.logger.info(f"fetch OK — {len(html):,} символов")

        save_cache(self.url, html)
        return html

    def extract_terms(self, html: str) -> list[str]:
        """
        FIX V4: универсальный экстрактор
        
        1. Извлекает из <a> тегов (топонимы, имена без званий)
        2. Обходит ВСЕ элементы (<p>, <li>, <td>, <th>, <h2>, <h3>)
        3. Применяет паттерны (rank_names, unit_names, quoted)
        4. Извлекает прямые термины (≤ 6 слов)
        
        ru.wikipedia:
          - <a> теги: Оппельн, Ратибор, Бреслау, Шёрнер
          - Паттерны: rank_names, unit_names, quoted
          - Прямые термины: города, топонимы, операции
          
        en.wikipedia:
          - <a> теги: useful_latin
          - Кириллица из скобок "(Георгий Жуков)"
          - Useful latin (техника/аббревиатуры)
        """
        soup = BeautifulSoup(html, "html.parser")
        lang = _get_lang(self.url)

        # FIX V4: универсальная экстракция (links + elements)
        all_terms = _extract_all_content(soup, lang)
        
        # Разделяем кириллицу и латиницу для en.wikipedia
        if lang == "en":
            cyrillic_terms = [t for t in all_terms if _is_cyrillic_term(t)]
            latin_terms = [t for t in all_terms if not _is_cyrillic_term(t)]
            
            self.logger.info(
                f"extract [en]: cyrillic={len(cyrillic_terms)}, "
                f"latin={len(latin_terms)}"
            )
            
            if latin_terms:
                self._save_latin(latin_terms)
            
            result = all_terms
        else:
            self.logger.info(f"extract [ru]: total={len(all_terms)}")
            result = all_terms

        self.logger.info(f"extract total (after dedup): {len(result)}")
        return result

    def _save_latin(self, terms: list[str]) -> None:
        """Сохраняет латинские термины в отдельный файл {domain}_en.txt."""
        out_dir = self.output_dir / self.category
        out_dir.mkdir(parents=True, exist_ok=True)
        safe_domain = self.domain.replace(".", "_").replace("/", "_")
        out_path = out_dir / f"{safe_domain}_en.txt"
        with open(out_path, "w", encoding="utf-8") as f:
            for term in terms:
                f.write(term.strip() + "\n")
        self.logger.info(f"save latin → {out_path} ({len(terms)} терминов)")


# ─────────────────────────────────────────────
# CLI
# ─────────────────────────────────────────────

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="WikiParser — парсинг одной Wikipedia-страницы"
    )
    parser.add_argument("--url", required=True)
    parser.add_argument("--category", required=True)
    parser.add_argument("--output-dir", default="data/parsed")
    parser.add_argument("--no-cache", action="store_true")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    parser = WikiParser(
        url=args.url,
        category=args.category,
        output_dir=args.output_dir,
        use_cache=not args.no_cache,
    )
    terms = parser.run()
    print(f"\n✅ Извлечено терминов: {len(terms)}")
    if terms:
        print("  Первые 30:")
        for t in terms[:30]:
            print(f"    {t}")


if __name__ == "__main__":
    main()
