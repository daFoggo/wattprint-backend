# Review

Bases: backend snapshot 642f2933e176fd21a3aab314ff2fe025989318b6 (dirty: the other session's three untracked
migrations); web 3877bbe13be48e33b5354aeefde05f9313b8488e --since f58176a (after the voice/chat change).
Snapshots: R1 backend a2b21be, web 23b5b74; R2 backend e3b2793, web 358cb59.

## R1 (full, opus): fix 1, 2, 3
1. Must: viewers saw write controls. Fixed: `isDemoViewer()` (features/home/queries, reads the home only) leaves out
   alert seen/feedback (Overview, Alerts), the add sheet, and the device page's alert tile.
2. Should: no test through `answer()`. Fixed: `test_a_demo_viewer_s_chat_reaches_the_read_only_block` (a viewer's
   chat with the model calling `propose_plan`: no plan widget, the model told "read-only", 0 `tb_suggestion` rows).
3. Should: realm `admin-cli` unrequested. Fixed in the spec (item 9) with its reason; applied with kcadm.
4-7. Minors fixed: atomic `INSERT … ON CONFLICT` for a view (two tabs); rule card text; `fallback={null}` reason;
   `DemoViewer` reads the home only.

## R2 (scoped, sonnet): fix 1, 8
1. Watch cancel X for a viewer. Ruling: a viewer's `/insights/watches` is empty (watches are listed per setter,
   `list_watches(user_id, home_id)`) and it cannot create one, so `WatchList` never renders a cancel for it;
   proven by `test_a_viewer_lists_no_watch_of_the_demo_home`. Cost if wrong: a cancel button that answers 403.
8. Realm mobile redirect URIs out of this spec. Ruling: they are the expo change's requirement 3 (reviewed there,
   applied with kcadm) in the shared realm file; now named in this spec's Areas of concern. Cost if wrong: none at
   runtime (the running realm already has them).

## Verified
- Backend: full suite 515 passed, 3 failed only in the other session's in-progress expect/sensor work; `-m migrations`
  8 passed; ruff + boundaries clean.
- Running stack: migration applied; kcadm: Direct Access Grants off on `wattprint-web` and `admin-cli`,
  `wattprint-demo-admin` deleted, the four demo owners' sessions ended; password grant answers `unauthorized_client`.
  A throwaway Keycloak 26.2 imported the new realm file cleanly.
- Playwright (dev 11092, a fresh account): picker on NoHome → House 2 viewer, strip shown, switch to House 5, Wappi
  refused to save an alert ("nhà demo này không thể lưu cảnh báo"). Test account removed.
