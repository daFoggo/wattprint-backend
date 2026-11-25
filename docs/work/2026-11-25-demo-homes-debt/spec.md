# Spec: debt of the dataset demo homes (lane M)

Request (user): pay the open debt; look at the UI yourself.
R1 Plegma's timestamps are UTC (verified: its outdoor temperature vs ERA5, r 0.945 at +0 h, falling with each
   later offset). `plegma_to_refit` converts them to Athens wall clock (Time) and Unix reads that as UTC; the model of
   home 101 is retrained and the home reseeded.
R2 `refit.shift_for(db_hi, shift, first_wall, last_wall)`: past the recording's end it plays again from its start,
   shifting by its length rounded up to whole weeks (weekday kept); `refit.loop_shifts` lists the passes; the weather
   import writes every pass up to 400 days ahead.
R3 The demo homes' "Other" device is named "Khác" (toml + the rows already in the database).
R4 Screen readers hear a forecast day's ₫ and P10–P90 range (`device-forecast.tsx`, messages `day`, `dayNoRange`).
R5 The holdout's call to `tail_as_of` is tested.

Areas of concern
- A loop wraps in the middle of a replay step: rows of one 15-minute step can belong to two passes; only the step
  containing the wrap is affected.
- The weather of looped passes repeats the recording's own weather, not the weather of that real date.
- `Other` rename is a DB update outside migrations (demo data only).
Files: backend scripts/refit.py, replay_refit.py, import_refit_weather.py, plegma_to_refit.py, demo_homes.toml, tests;
web device-forecast.tsx, messages/*/billing.json, docs/debt.md.
