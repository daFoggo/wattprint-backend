# Intent: one click into a demo home with a guest account

Record: none. Approval: the user chose "guest account per visitor" (2026-11-24) and asked not to be asked further.

- Problem (user's words): the flow "pick a home → sign in / sign up → land in the home" is too long ("khó thế nhỉ");
  they prefer accounts made ready for people to use.
- Outcome: on the sign-in page a visitor clicks a demo home and is in its dashboard, read-only, with no form.
- Each click creates a private guest account (own Wappi chats), deleted after 24 h.
- Touches: wattprint-backend auth/demo, Keycloak realm (admin client, web client grants), wattprint-web sign-in.
- Constraints: read-only stays enforced by the backend `viewer` role; no shared owner account (paid debt);
  abuse capped (per visitor and global, active guests capped).
