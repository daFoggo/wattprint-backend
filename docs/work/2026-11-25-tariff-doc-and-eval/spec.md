# Tariff decision on the bill, and a wider Wappi eval

Lane M. Record: debt.md rows 2 and 4.

Requirements
1. `GET /billing/current` returns `tariff_doc`: the short code ("QĐ 2892/QĐ-BCT") of the tariff version in force today, or null.
2. The code is stored in `tb_tariff_version.doc_code` (new column, backfilled for the two seeded versions); `source_doc` stays the maintainers' note.
3. The dashboard's bill summary caption names it.
4. `scripts/eval_wappi.py` has 10 more questions: alerts judged by the saved watch row, why-questions judged by the tool called, vague questions judged by "no figure without a tool". Measures as a non-viewer member. Leaves no watch behind.
Also: `tests/db/test_core.py` expected 22 device types; the catalog has 23 since the rice cooker.

Areas of concern: the eval deletes watches of the home created during a question, so two evals on one home at once would delete each other's rows; the migration backfills by plan and date only.

## Addendum 2026-11-26: 2027 tariff version (lane L: money, migration)
5. `tb_tariff_version` gets a version from 2027-01-01 at VAT 10% with the QĐ 2892 prices carried forward; the 2026-11-01 version ends 2026-12-31. Why: Resolution 204/2025/QH15 Art. 2 ends the 8% cut on 2026-12-31 and VAT Law Art. 9(3) sets 10% after; no extension known on 2026-11-26 (docs/legal-basis.md). Without it, bills from January would use 8%.
Areas of concern: a cycle that straddles 2026-12-31/2027-01-01 (tariff_straddle path); if the cut is extended the version must be moved by a new revision; prices for 2027 are an assumption (QĐ 2892 has no end date).
