# NILM datasets closer to Vietnam than REFIT

Checked 2026-11-24. "Suits NILM" means: a whole-home aggregate and per-appliance ground truth on the same clock, at 1 min
or finer. Hot-humid climate and air conditioners (ACs) are why REFIT (UK, 2013–15) is a weak proxy for Vietnamese homes.

| Dataset | Where, size | Rate | Ground truth | Appliances | Licence | Access (this agent) | Suits NILM |
|---|---|---|---|---|---|---|---|
| **Plegma** | Greece (Athens), 13 homes, Jul 2022–Sep 2023, 162–446 days each | 10 s | plug per appliance + aggregate, synced, `issues` flag (0.8 % of rows) | split ACs per room (up to 3), electric boiler, fridge, washer, dishwasher | CC BY 4.0 | files downloaded by the user (the host sits behind a Cloudflare challenge) | **Yes.** ACs and a boiler are the loads that dominate a Vietnamese bill. No kettle/microwave/toaster. |
| **ENERTALK** | Korea, 22 homes, 29–122 days, Sep 2016–Jan 2017 | 15 Hz | plug per appliance + aggregate | fridge, kimchi fridge, rice cooker, washer, TV, microwave, water purifier (no AC: autumn/winter) | CC0 (figshare) | direct download, 1.5–3.4 GB a home | **Yes.** The only open set with a **rice cooker**. Short recordings. |
| iAWE | Delhi, 1 home, 73 days, 2013 | 1 s aggregate, 6 s appliance | plug + circuit | 2 ACs, fridge, laptop, TV, … | CC BY 4.0 | Zenodo returned 403 to scripted requests; the `iawe.h5` file must be fetched in a browser | Yes, but one home: a test set for ACs, too small to train on. |
| Hyderabad AC set (Energy Informatics 2022) | India, 11 homes, 19 summer days, 2019 | 1 min | AC ON/OFF only (current of 3 phases + AC state) | AC | not read | not located | Partly: AC state detection only, no per-appliance energy. |
| MCEC-Thai | Bangkok, 1 home | 1 min | 10 **circuits** + aggregate (lights, sockets, pump, water heater, AC circuit) | circuits, not appliances | not read | Mendeley DOI 10.17632/nmnk58bgtb.1, not fetched | Partly: circuit level, one home. Closest climate. |
| PRECON | Lahore, 42 homes, 1 year | not stated on the page or paper pages read | mixed: some channels are one appliance, many are circuits or pairs (`Ref_WM_kW` fridge + washer, `AC_UPS_kW`) | AC by room, fridge, freezer, microwave, iron, no kettle | not stated; request through a Google Form | no direct link | **No for now.** Mixed channels, rate unknown, no aggregate-vs-appliance paper results. Re-check once the form's data arrives. |
| RECON-SL | Sri Lanka, 4 063 homes | 15 min | none (survey of owned appliances only) | – | CC BY 4.0 paper | – | **No** (no appliance ground truth); useful as ownership priors. |
| UK-DALE, REDD, ECO, … | UK, USA, Switzerland | 1–6 s | plugs | no ACs of the Vietnamese kind | various | not tried | Same climate gap as REFIT. |

Not found: any public Vietnamese household appliance-level dataset, and none for Malaysia, Indonesia or the Philippines.

## What was done with them

- `scripts/plegma_to_refit.py` and `enertalk_to_refit.py` (tested in `tests/`) write REFIT-style CSVs
  (`Time`, `Unix`, `Aggregate`, `Appliance1..k`, `Issues`) that `dataset/training/train_house.py` and the demo
  replay read unchanged. `Time` and `Unix` carry each country's wall clock (read as UTC, like REFIT's), so the
  models learn meal and AC hours the way the demo replays them.
- Plegma's split ACs (up to 3 per home) are added into one `AC` device: the app tells devices apart by type.
- Detector only, one home each, mean of 3 seeds, macro ON/OFF F1 (research_v3 `context` recipe):
  REFIT H2 0.600 · H5 0.608 · Plegma H1 0.693 · H3 0.425 (AC unused in the test part) · H4 0.501 (boiler off in the
  test part) · H11 0.621 · ENERTALK H0 0.698 (rice cooker 0.84, washer 0.72) · H5 0.633. Per-device tables: `dataset/research_v4/REPORT.md`.
- Homes added to the demo: Plegma House 1 and ENERTALK House 0 (see the report for their model scores).

Honest limits: scores are from one home's own last 20 % of time, so they say nothing about transfer to a new home or to
Vietnam. The REFIT cross-house test (a model on another home: energy F1 0.32 vs 0.50 on its own) is the evidence that a
model needs its own home's recording.
