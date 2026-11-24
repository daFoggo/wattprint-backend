# Spec: demo guest accounts

## Backend: `POST /demo/homes/{key}/guest`
- Only the dashboard may call it: header `X-Demo-Secret` = the wattprint-web client secret (hmac compare), else 403.
  `X-Demo-Visitor` = the visitor's address for the per-visitor cap. Same caps as the old demo session
  (5/min per visitor, 20/min global; shortcut: per process). Unknown key → 404.
- Purges expired guests first (best effort, ≤ 50 per call): `tb_users` rows with the guest email domain created
  more than 24 h ago → Keycloak user deleted (admin API) → row deleted (cascades membership, chats).
- Refuses (503 `demo_full`) when 500 guests are active.
- Creates a Keycloak user through service account `wattprint-demo-admin` (realm-management `manage-users`):
  username/email `guest-<12 hex>@guest.wattprint.local`, first name "Khách", last name "demo", email verified,
  random password (never stored, never returned).
- Password grant on `wattprint-web` (its secret; Direct Access Grants re-enabled on that client only) → tokens.
- Provisions `tb_users` from the token claims, inserts a `viewer` row for the home, returns the tokens
  (`access_token`, `refresh_token`, `id_token`, `expires_in`, `refresh_expires_in`).
- Any failure after the Keycloak user exists deletes it again (no orphan accounts). Keycloak down → 503.

## Web
- `startDemoAction(key)`: validates the key, calls the endpoint with the secret and `x-real-ip`, stores the tokens
  with `signInWithTokens` (verifies the access token against JWKS first, as the OAuth callback does), redirects to
  the dashboard. Expected failures come back as a message in the dialog.
- Sign-in dialog: clicking a home card runs it. The pick cookie + callback hook of the previous change are removed.
- Signed-in accounts without a home keep the NoHome picker (`viewDemoHomeAction`); the sidebar demo row keeps
  switching homes for guests and viewers alike.

## Areas of concern
- Direct Access Grants on `wattprint-web`: anyone holding its secret can password-grant any user. The secret is
  server-only (web server + API env); Keycloak brute-force protection still applies.
- Keycloak required actions / user profile may refuse a password grant for a new user ("account not fully set up").
- Guests can chat with Wappi (LLM cost); the copilot's own limits apply.
- `refresh_expires_in` of a guest session outliving the 24 h purge: the next refresh fails → /auth/expired.
