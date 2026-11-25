# Review: delete my account

Base: wattprint-backend afdeb1e9dd2ead7df26ec2830a887032fb9a5717, wattprint-web ebf638ba5e3ed68b83b3f6ea9a66cb7e3ba9472a
(the tree held earlier uncommitted work; its own review is in the markdown/fonts change, below).

## R1 (opus, lane L): verdict "fix 1, 2, 3, 4"

1. Must fix: after a retention drop (400 days) the hourly and daily totals outlive their raw rows, so a post-commit
   refresh over the raw range never cleaned them, and `allow_missing_raw` rebuilt other homes' buckets from partial data.
   Fixed: `erase_home_readings` deletes the six aggregates' stored rows by `series_id` in the same transaction; the
   refresh, `refresh_erased` and the post-commit shortcut are gone. Tests: `test_totals_outlive_their_raw_rows...`
   (totals with no raw under them; another home's 1m/1h/1d counts unchanged; device estimate totals too). Deleting from
   the compressed aggregate storage was checked by hand on the dev database (70 compressed chunks, 400,961 rows
   deleted, rolled back).
2. Must fix: the copy said guests delete themselves after 24 hours; only `create_guest` purges them. Fixed by
   saying so ("when the next trial guest arrives") in terms.home, collected.guest and retention.guest (vi, en).
3. Must fix: `rights.correct` promised profile editing that does not exist. Fixed: home and notification choices in
   settings; name or email by writing to the contact email.
4. Should fix (scope): `text.ts`, `copilot-message.tsx` and `text.test.ts` changed in this tree.
   Ruling: these are the fix pass of the earlier markdown change's own R1 (its finding 1, the copy button, and Minor 2,
   numbered lists), reviewed there, not part of this change. Cost if wrong: none, they are tested and small.
5. Minor, fixed: deletion.body names what is deleted precisely (alerts you set; the home's alerts only with the home;
   a failed sign-in-account delete asks to try again). 6. Minor, fixed: cookies mention the 10-minute sign-in cookie
   (`maxAge: 600`) and Keycloak's own cookies. 7. Minor, gone with 1 (no recompute in the request).

Also found by a new test, not by the reviewer: a member who used an invite made `DELETE /users/me` answer 500
(`fk_home_invite_used_by_users`, no ON DELETE rule), and a home with a meter could not be deleted. Fixed:
`used_by` is cleared, the meter unlinked; test `test_a_home_with_a_meter_and_a_member_who_used_an_invite...`.

Declined to judge by the reviewer, now covered by the same fix: `tb_meter.home_id` and `tb_home_invite.used_by`.
Left (no route writes it): `tb_ingest_batch` keeps its metadata (`SET NULL`) after a home is deleted.

## R2 (sonnet, scoped): verdict "fix 6"; findings 1, 2, 3, 5 addressed

6. Ruling: the reviewer says the dashboard writes shadcn's `sidebar_state` cookie, so the cookie list is incomplete —
   not applicable: the dashboard layout imports its own `@/components/layout/sidebar/sidebar`, which has no cookie or
   localStorage, and nothing imports `packages/ui/src/components/ui/sidebar.tsx` (grep over both apps and ui-patterns).
   Cost if wrong: one functional cookie missing from the list.
   Minor, left as is: `_purge` clears 50 guests per arrival, so a larger backlog takes several arrivals; the copy says
   "when a new guest arrives", which stays true.
