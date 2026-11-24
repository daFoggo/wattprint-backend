# Spec (lane M): pay the demo Minors, restyle the sidebar demo row

1. `create_guest`: a refused token check or JWKS failure (`jwt.PyJWTError`) answers 503 `demo_unavailable` like a
   Keycloak outage, and the new account is still deleted (test).
2. `_Keycloak.delete`: a refusal other than 204/404 is logged (expired guests would otherwise fill the cap unseen).
3. web `session-demo.tsx`: read the demo homes only after the viewer check.
4. web sidebar demo row: the user said it looks the same as the account row below it. It becomes a bordered notice
   card (label "Nhà demo · chỉ xem" with an eye, the home name, "Đổi" on the right); in the icon rail just the eye.
   Design rules: docs/design-system.md (card inside a plate: `rounded-xl border bg-background`), tokens only.
