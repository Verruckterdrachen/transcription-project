# VALIDATION.md — Чеклист проверки качества
# Обновлено: 2026-02-20

## 🎯 ЦЕЛЬ
8 обязательных проверок ПЕРЕД тем, как сказать «готово» и коммитить.
Все 8 должны быть GREEN. Даже 1 RED = баг = исправляем.

⚙️ Пункты 1, 2, 3, 5, 7 — автоматизированы в `scripts/validate.py`.
   Запуск: `python scripts/validate.py` (автопоиск в test-results/latest/)
   Пункт 4 — grep вручную. Пункт 6 — Audacity. Пункт 8 — diff.

---

## ✅ 8 ОБЯЗАТЕЛЬНЫХ ПРОВЕРОК

### 1. ДЛИННЫЕ БЛОКИ (>30 сек)
**Что:** Нет ли сегментов длиннее 30 сек без промежуточного timestamp?

```python
for seg in segments:
    duration = seg['end'] - seg['start']
    if duration > 30:
        print(f"❌ Длинный блок: {seg['time']} ({duration:.1f}s)")
Значение	Статус
5–30 сек	✅ GREEN
30–60 сек	⚠️ Проверить контекст
>60 сек	❌ RED — нужен split
2. ДУБЛИ
Что: Нет ли повторяющихся фраз (одно предложение дважды)?

bash
grep -E "(.{20,})\. \1" "Спикер (ДД.ММ).txt"
python
# Паттерн для поиска дублей >20 символов
"(.{20,})\.\s*\1"
✅ GREEN = grep ничего не нашёл
❌ RED = найдены совпадения → баг в gap filling или merge

3. ЗАИКАНИЯ
Что: Все заикания (слово повторяется 2–3 раза) помечены как ...?

bash
grep -oE "\b(\w+) \1\b" "Спикер (ДД.ММ).txt"
Паттерны:

\b(\w+)\s+\1\b — «начинает начинает»

\b(\w+)\s+\1\s+\1\b — «я я я»

✅ GREEN = заикания оформлены с ...
❌ RED = голый повтор без ...

4. ENDING HALLUCINATIONS
Что: Нет ли типичных хвостов Whisper в конце файла?

bash
grep -i "продолжение следует\|спасибо за внимание\|подписывайтесь\|до новых встреч" "*.txt"
✅ GREEN = grep ничего не нашёл
❌ RED = найден хвост → удалить через clean_hallucinations()

5. СМЕЖНЫЕ РЕПЛИКИ
Что: Нет ли двух реплик одного спикера подряд (должны быть смержены)?

python
for i in range(len(segments) - 1):
    if segments[i]['speaker'] == segments[i+1]['speaker']:
        print(f"❌ {segments[i]['speaker']}: {segments[i]['time']} и {segments[i+1]['time']}")
✅ GREEN = нет смежных одного спикера
❌ RED = есть → баг в merge_replicas()

6. TIMESTAMP DRIFT
Что: Совпадают ли timestamp в TXT с реальным аудио?

⚠️ Только вручную — требует Audacity.

Методология:

Открыть аудио в Audacity

Выбрать 3–5 случайных timestamp из TXT

Перейти на них в аудио

Проверить: текст совпадает?

Сдвиг	Статус
0–1 сек	✅ GREEN
1–3 сек	⚠️ Допустимо
>3 сек	❌ RED — дрейф после gap filling
7. ГАПЫ (>3 сек)
Что: Все гапы >3 сек либо заполнены через force_transcribe, либо объяснены (тишина)?

python
for i in range(len(segments) - 1):
    gap = segments[i+1]['start'] - segments[i]['end']
    if gap > 3.0:
        print(f"🚨 GAP: {segments[i]['time']} → {segments[i+1]['time']} ({gap:.1f}s)")
✅ GREEN = гапы объяснены или заполнены
❌ RED = необъяснённый гап >3 сек

8. REGRESSION (сравнение с Golden Dataset)
Что: Результат не хуже, чем golden dataset baseline?

bash
diff "test-results/latest/Спикер (ДД.ММ).txt" "golden-dataset/спикер-дата/Спикер (ДД.ММ).txt"
Проверяем:

Количество реплик не уменьшилось

Спикеры на ключевых timestamp совпадают

Нет новых дублей или хвостов, которых не было в baseline

✅ GREEN = результат не хуже baseline
❌ RED = регрессия → откат или новый фикс

📋 БЫСТРЫЙ ЧЕКЛИСТ (копируй перед каждым коммитом)
text
VALIDATION CHECKLIST
━━━━━━━━━━━━━━━━━━━━━━━━━
[ ] 1. Длинные блоки    — нет >30 сек без timestamp
[ ] 2. Дубли            — grep: нет повторов
[ ] 3. Заикания         — все с "..."
[ ] 4. Ending halluc.   — нет хвостов Whisper
[ ] 5. Смежные реплики  — нет двух подряд одного спикера
[ ] 6. Timestamp drift  — 3–5 точек проверено в Audacity ✋
[ ] 7. Гапы             — все >3 сек объяснены
[ ] 8. Regression       — не хуже golden dataset
━━━━━━━━━━━━━━━━━━━━━━━━━
Все 8 GREEN? → Коммитить
Хоть 1 RED?  → Фиксить сначала
🔗 Связанные документы
docs/KNOWN-ISSUES.md — список активных багов

docs/DEBUGGING.md — методология RCA (5 Whys)

docs/WORKFLOW.md — полный процесс работы

golden-dataset/ — эталонные результаты

Последнее обновление: 2026-02-20