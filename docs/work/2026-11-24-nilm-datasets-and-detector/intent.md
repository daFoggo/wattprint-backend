# Intent: NILM detector research, and datasets closer to Vietnam

Record: none (user request 2026-11-24, delegated: "cứ làm đến khi xong hẳn, kết quả tốt"; each artifact is approved by that delegation).
Source: `dataset/research_v3/REPORT.md` "Next" (detector first: fridge precision, short heaters) + the request below.

## Request (user's words)
- Continue the afternoon's NILM training work: improve and measure results with two scores (ON/OFF F1 and energy F1).
- Find a public dataset closer to Vietnam (hot, humid, air conditioners) than REFIT: Plegma and PRECON were looked at
  before. Check they really suit NILM; if not, research others. Licence gaps do not matter (non-commercial demo).
  Data must be transformed to behave like REFIT.

## Goal and outcome
1. Detector: macro ON/OFF F1 up on REFIT House 2 and 5 (now 0.600 / 0.608), with energy F1 and kWh error not worse.
2. A written verdict per candidate dataset (suits NILM or not, why, how to get it) and, for the one that suits, a
   converter to the REFIT-style CSV that `dataset/training/train_house.py` reads.

## Assumptions not yet confirmed
- Plegma's files cannot be fetched by this agent (Cloudflare challenge on pureportal.strath.ac.uk; not bypassed), so the
  converter is written from the documented schema and tested on a synthetic file until the user drops the archive in.
- PRECON is a Google Form request (no direct link): same.
- Shipping a better detector into the NILM worker is a separate change (bundle format, engine); this change ends at a
  measured recommendation plus research code.

## Touches
`dataset/research_v4/` (new, research code and report), `dataset/external/` (git-ignored downloads),
`dataset/scripts/` (converter), `docs/`. No app code, no migration.
