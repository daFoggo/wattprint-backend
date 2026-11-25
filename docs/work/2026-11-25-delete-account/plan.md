# Plan: delete my account

Spec: [spec.md](spec.md). Standards: `.claude/rules/auth.md`, `data.md`, `tests.md` (backend); `dashboard-data.md`,
`i18n.md`, `ui.md` (web).

1. energy `erase_home_readings` + `refresh_erased` (`energy/services/erase.py`, exported through `energy/api.py`).
   Proof: `test_sole_owner_erases...` (aggregates empty) and `test_compressed_readings_over_the_decompression_limit...`
   (120000 compressed rows; failed first with "tuple decompression limit exceeded").
2. auth `delete_account` (`auth/services/account.py`), errors `home_has_members` (409) and
   `account_delete_unavailable` (503), route `DELETE /users/me`. Proof: `tests/test_delete_account.py` (7 cases).
3. web: `deleteAccount` (server), `deleteAccountAction`, `DeleteAccount` row in the account menu, vi/en strings.
   Proof: `features/auth/__tests__/delete-account.test.ts` (4 cases).
4. Privacy and Terms pages rewritten from verified facts (no SLA days, DPO, SCC, GDPR or CCPA claims); contact is the
   individual controller. Retention figures come from `timescaledb_information.jobs` (400 days).

Risks: DELETE over compressed chunks decompresses rows (slow for years of data, rare); the aggregates refresh failing
after commit is logged (shortcut) and leaves orphan buckets until an admin backfill.
