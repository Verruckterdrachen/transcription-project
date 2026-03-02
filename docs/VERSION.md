# Version: v17.20
# Last updated: 2026-03-02
# Status: STABLE ✅

## 🎯 Текущее состояние

**Base:** v17.0 BASELINE
**Test audio:** Исаев (27.05) — NW_Uckpa0001_01, NW_Uckpa0001_02, NW_Uckpa0003_01
**Последний фикс:** v17.20 — [?]-метки спорных сегментов + footer-реестр (txt_export.py)

| Баг | Описание | Статус |
|-----|----------|--------|
| BAG_D_v3 | Таймкод внутри предложения после auto_merge (SKIP из-за хвоста ≤ 45s) | ✅ FIXED v17.18 |
| BAG_D_v2 | insert_intermediate_timestamps: ts вставлялся после предложения (w_idx конца) | ✅ FIXED v17.17 |
| BAG_B | clean_loops FP: удаление при рефразировании («Искры») | ✅ FIXED v17.13 |
| #32 | GAP_FILLED: corruption/дубли (GUARD A инверсия, B overlap, C промпт-bleeding) | ✅ FIXED v17.12 |
| BAG_F | timestamp_fixer: инверсия timestamp после split (scale guard) | ✅ FIXED v17.11 |
| #15r | clean_loops: удаление фразы при висячем предлоге (gap overlap) | ✅ FIXED v17.10 |
| #27 | clean_loops: ложное удаление слов с low-meaningful N-граммами | ✅ FIXED v17.9 |
| #26 | «Спикер» вместо speaker_surname в TXT | ✅ FIXED v17.8 |
| #25 | False positive «Товарищ так и сказал, нет, вы...» | ✅ FIXED v17.6 |
| #21 | False positive «Вы наваливаетесь...» (цитата) | ✅ FIXED v17.4 |
| #24 | False positive «давайте мы так...» (пересказ) | ✅ FIXED v17.4 |
| BAG_E | speaker micro-fragment: короткая реплика журналиста → Исаев | 🔴 OPEN |


## 📋 Быстрый старт

1. Читай **KNOWN-ISSUES.md** — текущие баги
2. Читай **WORKFLOW.md** — процесс работы
3. Читай **VALIDATION.md** — 8 обязательных проверок
4. Читай **BUG_REGISTRY.md** — перед открытием нового бага

## 📜 История версий

→ см. **CHANGELOG.md**
