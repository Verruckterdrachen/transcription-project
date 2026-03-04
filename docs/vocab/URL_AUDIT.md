# Vocab Module — Работа с url_audit.csv

## 📂 Расположение

`data/dictionaries/url_audit.csv`

---

## 📋 Структура CSV

```csv
category_id,category_name,url,status_code,content_type,parseable,priority,notes
1,СОВЕТСКИЕ КОМАНДИРЫ,https://ru.wikipedia.org/wiki/Список_Маршалов,200,text/html,requests+bs4,MED,
8 колонок:

Колонка	Описание	Значения
category_id	ID категории	1–13, 16
category_name	Название категории	см. список ниже
url	Полный URL	http/https, кириллица будет закодирована
status_code	HTTP-статус	200, 404, или пусто
content_type	MIME-тип	text/html, application/pdf
parseable	Какой парсер	requests+bs4, api, pymupdf, selenium, manual, dead
priority	Приоритет	HIGH, MED, LOW
notes	Комментарии	произвольный текст
📚 Категории (13 + 1 книги)
ID	Название	Домены	Парсер
1	СОВЕТСКИЕ КОМАНДИРЫ	wikipedia, militera, rkka, pamyat-naroda	wiki, militera, rkka, api
2	НЕМЕЦКИЕ КОМАНДИРЫ	wikipedia en	wiki
3	СОВЕТСКАЯ ТЕХНИКА	wikipedia ru/en	wiki
3Б	ФОРМА, ОБМУНДИРОВАНИЕ	wikipedia en, PDF	wiki, pdf
4	НЕМЕЦКАЯ ТЕХНИКА	wikipedia en	wiki
5	ОПЕРАЦИИ И СРАЖЕНИЯ	rkka, pamyat-naroda	rkka, api
6	ВОИНСКИЕ ФОРМИРОВАНИЯ	rkka, wikipedia	rkka, wiki
7	ТОПОНИМЫ	wikipedia ru	wiki
8	НАГРАДЫ И ЗВАНИЯ	wikipedia ru, rkka	wiki, rkka
9	СОЮЗНИКИ	wikipedia en	wiki
10	ТЫЛ, ПРОМЫШЛЕННОСТЬ	wikipedia ru	wiki
11	СПЕЦСЛУЖБЫ	wikipedia ru	wiki
12	ВМФ	wikipedia ru/en	wiki
13	ВОЕННАЯ МЕДИЦИНА	wikipedia ru	wiki
16	КНИГИ С УКАЗАТЕЛЯМИ	militera, iremember	militera, iremember
Маппинг категорий → имена словарей:

category_id	Файл словаря (data/final_dicts/)
1	base_ussr_commanders.txt
2	base_axis_commanders.txt
3	base_ussr_equipment.txt
3Б	base_ussr_uniforms.txt
4	base_axis_equipment.txt
5	base_operations.txt
6	base_formations.txt
7	base_toponyms.txt
8	base_awards.txt
9	base_allies.txt
10	base_rear_industry.txt
11	base_intel_nkvd.txt
12	base_navy.txt
13	base_medical.txt
16	base_books_index.txt
➕ Как добавить новый URL
1. Найти источник
Примеры:

Wikipedia статья про операцию: https://ru.wikipedia.org/wiki/Операция_Багратион

Militera книга с именным указателем: http://militera.lib.ru/memo/russian/konev/

РККА список: http://rkka.ru/oper.htm

2. Определить категорию
Операция → категория 5 (ОПЕРАЦИИ И СРАЖЕНИЯ)

Командир → категория 1 или 2

Техника → категория 3 или 4

3. Проверить доступность
bash
curl -I "https://ru.wikipedia.org/wiki/Операция_Багратион"
# HTTP/1.1 200 OK → добавляем
# HTTP/1.1 404 Not Found → не добавляем (или parseable=dead)
4. Определить тип парсера
Домен	parseable	Парсер
wikipedia.org	requests+bs4	wiki_parser.py
militera.lib.ru	requests+bs4	militera_parser.py
rkka.ru	requests+bs4	rkka_parser.py
iremember.ru	requests+bs4	iremember_parser.py
pamyat-naroda.ru	api	api_parser.py
*.pdf	pymupdf	pdf_parser.py
Сложный JS	selenium	(пока manual)
5. Добавить строку в CSV
text
5,ОПЕРАЦИИ И СРАЖЕНИЯ,https://ru.wikipedia.org/wiki/Операция_Багратион,200,text/html,requests+bs4,HIGH,
Правила:

URL без пробелов (кириллица ОК, git закодирует автоматически)

status_code можно оставить пустым (скрипт проверит)

priority: HIGH если уникальный контент, MED если дубль Wikipedia, LOW если низкая ценность

6. Коммит
bash
git add data/dictionaries/url_audit.csv
git commit -m "📚 vocab: добавлен URL Операция Багратион (категория 5)"
git push origin main
🔍 Фильтрация URL (для run_all_parsers.py)
Все живые URL
bash
python scripts/vocab/run_all_parsers.py --all
Условие: parseable NOT IN ('dead', 'manual')
Итого: 138 URL из 212

Только HIGH-priority
bash
python scripts/vocab/run_all_parsers.py --priority HIGH
Домены: militera, pamyat-naroda, podvignaroda, rkka, iremember
Итого: 58 URL

Только Wikipedia
bash
python scripts/vocab/run_all_parsers.py --parsers wiki
Домены: ru.wikipedia.org, en.wikipedia.org
Итого: ~60 URL (MED priority)

Только категория
bash
python scripts/vocab/run_all_parsers.py --categories 1,2
Категории: 1 (СОВЕТСКИЕ КОМАНДИРЫ), 2 (НЕМЕЦКИЕ КОМАНДИРЫ)

📊 Статистика (текущая)
Статус	Кол-во	%
200 OK, parseable	138	65%
404 dead	42	20%
manual (Telegram, templates)	18	8%
error (timeout, SSL)	14	7%
ВСЕГО	212	100%
По приоритетам:

Priority	Кол-во (живые)
HIGH	58
MED	61
LOW	19
По парсерам:

parseable	Кол-во
requests+bs4	118
api	12
pymupdf	2
selenium	6
dead	42
manual	18
🚨 Частые ошибки
1. Дубли URL
Симптом: один и тот же URL в разных категориях.

Решение: оставить в основной категории, удалить дубль.

2. Битые кириллические URL
Симптом: URL с %D0%... не парсится.

Решение: в CSV писать декодированный URL:

text
...,https://ru.wikipedia.org/wiki/Блокада_Ленинграда,...
Git автоматически закодирует при коммите.

3. Redirect на другой домен
Симптом: militera.lib.ru/h/book/ редиректит на militera.org.

Решение: обновить URL на финальный (проверить через curl -L -I).

Версия: v17.21
Последнее обновление: 2026-03-04