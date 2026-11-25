# Review: demo homes debt (R1, sonnet, lane M) — verdict: fix 1
1. Should: the AC-sum test was dropped when the Plegma clock tests were rewritten. Restored (passes: the code was right).
2. Minor: a period rounded up leaves a hole (88-day recording, 91-day period: 3 days at 0 Wh). Fixed test first:
   the period is rounded down (`refit.loop_period`), so no hole; up to 6 days of a recording's start are skipped on replay.
3. Minor: Plegma's repeated summer-time hour keeps two rows per local time (declared `shortcut:`); `train_house.py` reads
   `Time` (resampled mean), not `Unix`, so a non-increasing Unix does not matter there.
Rulings (accepted in the spec): the step that contains the wrap mixes two passes; looped weather repeats the
recording's own weather; the "Other" rename in the database is demo data outside migrations.
