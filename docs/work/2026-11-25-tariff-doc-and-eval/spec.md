# Tariff decision on the bill, and a wider Wappi eval

Lane M. Record: debt.md rows 2 and 4.

Requirements
1. `GET /billing/current` returns `tariff_doc`: the short code ("QĐ 2892/QĐ-BCT") of the tariff version in force today, or null.
2. The code is stored in `tb_tariff_version.doc_code` (new column, backfilled for the two seeded versions); `source_doc` stays the maintainers' note.
3. The dashboard's bill summary caption names it.
4. `scripts/eval_wappi.py` has 10 more questions: alerts judged by the saved watch row, why-questions judged by the tool called, vague questions judged by "no figure without a tool". Measures as a non-viewer member. Leaves no watch behind.
Also: `tests/db/test_core.py` expected 22 device types; the catalog has 23 since the rice cooker.

Areas of concern: the eval deletes watches of the home created during a question, so two evals on one home at once would delete each other's rows; the migration backfills by plan and date only.
