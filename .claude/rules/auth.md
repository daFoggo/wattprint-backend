---
paths:
  - "app/modules/auth/**"
  - "app/core/security.py"
  - "keycloak/**"
---

# Auth (Keycloak): rules an agent must not miss

Source of truth: docs/keycloak-auth.md. This card is the short version; open the doc when a case is not here.

- FastAPI is a resource server: verify RS256 via JWKS (`iss`, `aud`, `exp`, `sub`, `typ=Bearer`, `azp` in `KEYCLOAK_CLIENT_IDS`). JWKS down 503, bad token 401, inactive 403, email under another id 409.
- Every endpoint needs a token except health, provinces and the demo sign-in pair `/demo/homes`, `/demo/session` (`tests/test_api.py` checks this); data stays within the caller's home.
- Password policy, brute force and token rotation live only in the realm (`keycloak/realm/`); the theme reads them from Keycloak. A realm change applies only on re-import, which issues new `sub`s (stale `tb_users` rows answer 409): ask first.
- Never set `KEYCLOAKIFY_SPA_DEV_SERVER_PORT` outside local theme development.
