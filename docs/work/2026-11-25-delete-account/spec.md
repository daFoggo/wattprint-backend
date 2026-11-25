# Spec: delete my account (lane L: auth, personal data)

Approval: delegated by the user on 2026-11-25 ("tra lại dự án, nếu chưa có thì làm thêm"). Record: handoff item 5
(Terms and Privacy pages promise account deletion; the project had no route for it).

## Problem

The Privacy page promises that an account and its data are erased on request. Nothing does it: no route, and the
energy hypertables (`tb_reading`, `tb_device_estimate`) have no foreign keys by design, so deleting a home or a user row
leaves the household's readings behind, and the aggregates built from them.

## Requirements

R1 `DELETE /api/v1/users/me` answers 204 and erases the caller's account: profile, preferences, chats, watches, plans,
   alerts, notification log (all cascade from `tb_users` or the home), and the Keycloak account.
R2 A **sole owner** of a home (no other member) also erases the home and all its data: devices, series, models, weather,
   and every `tb_reading` / `tb_device_estimate` row of its series, plus the stored rows of the six continuous aggregates
   (deleted by `series_id` in the same transaction, since retention drops raw rows after 400 days but never the hourly
   and daily totals, and a refresh would find nothing to remove and would recompute other homes' buckets).
R3 An owner while **other members exist** gets 409 `home_has_members` and nothing is deleted (their data is not the
   owner's to erase; there is no member-management route yet to remove them).
R4 A member or viewer (a demo guest) is removed without touching the home.
R5 Without the Keycloak admin client secret, or when Keycloak refuses, the answer is 503 `account_delete_unavailable`.
   The secret is checked before anything is erased. Local data goes first, Keycloak last: a refused Keycloak delete
   leaves a signed-in account with nothing in it, and the same call can be repeated (the next sign-in re-provisions
   an empty profile), where the other order would leave personal data with no way to sign in and ask again.
R6 Only the caller's own account: no id in the path.

## Design

- `app/modules/auth/services/account.py` (imports `home.api` and `energy.api`, so like `demo` it is not re-exported
  by `services/__init__`), `delete_account(db, user, claims-free)`; the route in `routes/user.py` next to `/me`.
- `energy.api` exports `erase_home_readings(db, home_id)` (`energy/services/erase.py`): deletes the two hypertables and
  the six aggregates' storage tables (found in `timescaledb_information.continuous_aggregates`) by `series_id`, in the
  caller's transaction, with `SET LOCAL timescaledb.max_tuples_decompressed_per_dml_transaction = 0`.
- A home's meter hardware is unlinked (`tb_meter.home_id = NULL`); an invite the account used keeps its row with
  `used_by = NULL` (both foreign keys have no ON DELETE rule, and a 500 would follow).
- The Keycloak admin call reuses `demo._Keycloak` (service account, client credentials); extract it only if a third
  caller appears.

## Areas of concern

- DELETE on **compressed** chunks (`compress_after` 2 days): TimescaleDB must support it for this version; the
  integration test deletes rows older than the compression age.
- Retention facts the Privacy page will state: raw and per-minute data 400 days (`policy_retention`), hourly and daily
  aggregates have no drop policy, guests live 24 h.
- A guest's token stays valid until it expires (300 s) after the Keycloak delete; every route re-reads the user and
  `provision_user` would re-create an empty profile on a new request. Not a data risk (an empty viewer profile).
