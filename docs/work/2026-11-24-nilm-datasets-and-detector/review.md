# Review: NILM datasets and detector (R1, opus, full, backend + web)
Bases: backend 21fe144 · web 7bb2aad. Verdict: fix 1, 2, 3, 4.

1. Must: new homes got Loughborough weather (`import_refit_weather.SITE`). Fix: per-home `site` in demo_homes.toml.
2. Must: 365 days of history were a copied week (recording ends before now). Fix: per-home `history_days` so the
   whole-year shift puts the recording over now (Plegma 120, ENERTALK 30); homes reseeded from scratch.
3. Must: `Kimchi` (type fridge) on the timeline and its tip in English. Fix: timeline list + `TYPE_KEYS.fridge`.
4. Should: `wattprint-web/docs/demo-video.md` pointed at the deleted heater home. Fix: rewritten for House 5 / Plegma 1.
5. Minor: ENERTALK day-boundary duplicate rows. Fix: join days then average by Time (test first).
6. Minor: stale watermark row `refit/CLEAN_House5.csv#5-heat`. Fix: deleted.
Rulings: the heater code (HEATER, `5-heat` keys) stays — spec asked only to delete the home's data — cost: dead code until the
heater scenario is retired. Plegma rate stays 10 s (trainer resamples; replay fine) — cost: none.
Not checked by reviewer: Plegma clock (see below, answered after the fix pass).
