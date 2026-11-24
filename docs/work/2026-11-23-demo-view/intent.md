# Intent: demo homes viewed from the visitor's own account

Record: wattprint-web docs/debt.md (2026-11-23 Direct Access Grants; T03 shared owner; T03 R3 `_unlock`).
Approval: the user chose "own account + view" when asked (2026-11-23) and delegated the details ("hướng tốt nhất và
chuẩn nhất"). Covers wattprint-backend, wattprint-web and the running Keycloak; artifacts live here only.

- Problem: demo sign-in password-grants the real owner of a REFIT home through client `wattprint-web` (Direct Access
  Grants on) and unlocks it with service account `wattprint-demo-admin` (`manage-users`). Anyone holding the web
  client secret can password-grant any user; every visitor is the owner and can change the home for everyone; the
  session caps are per process.
- Outcome: visitors sign in (or sign up) with their own Keycloak account, then pick a demo home and get a read-only
  `viewer` membership. No password grant, no shared credentials, no admin service account.
- Touches: auth + home + insight + copilot modules (backend), sign-in and dashboard (web), realm (Keycloak).
- Constraints: one home per account stays; owners/members of a real home are not turned into viewers; demo visitors
  get no alert mail of the demo home; existing visitor sessions (as owners) are ended at cutover.
