---
paths:
  - "app/modules/**"
  - "scripts/**"
---

# Data and modules: rules an agent must not miss

Source of truth: docs/database-design-guide.md 3, README Layout, docs/superpowers/plans/2026-11-19-real-dashboard-apis.md ("Lưu ý khi làm tiếp"), 2026-11-17-nilm-pipeline-multi-home.md 4.6.

- Another module is imported only through its `api.py` (`scripts/check_boundaries.py` checks it).
- Screens read continuous aggregates, never raw `tb_reading`; every write goes through `ingest_readings` (chunks of 50k-500k rows, the function flushes, the caller commits).
- Per-device numbers come only from NILM estimates (`tb_device_estimate`, `device_estimate_*`); the home total comes from the `main` channel. No API reads REFIT's raw device channels (only `scripts/eval_nilm.py`).
- NILM never changes or deletes `tb_reading`; rerun by moving the `'nilm'` checkpoint back. Data write and checkpoint advance share one transaction.
- Missing minutes count as 0 Wh, never filled; a bill under 95 % coverage is `partial`. Days are cut in Vietnam time over UTC `timestamptz`.
- Numbers (kWh, VND) are computed by SQL/services, never by the LLM. Cohort stats need `n_homes >= 10`.
- A deliberate scale limit gets a `shortcut:` comment with its trigger, plus an entry in the debt file.
