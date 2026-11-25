# Review: Wappi polish

Base: wattprint-backend afdeb1e9dd2ead7df26ec2830a887032fb9a5717, wattprint-web ebf638ba5e3ed68b83b3f6ea9a66cb7e3ba9472a;
packaged since the delete-account R2 snapshots (7c5af7a / 7300b1c).

## R1 (sonnet, lane M): verdict "fix 1, 2"; Minors 3 to 5

1. Should fix: the eval stored the raw question, skipping the route's `redact`, so its "pasted phone number" case could
   pass while masking was broken and sent the real number to the model. Fixed: `ask()` runs `redact(question, "vi")`
   as the route does, and the check also fails if the number is still in what was sent. Smoke run 7/7.
2. Should fix: the debt rows still said the measurement and the feedback channel were missing. Fixed: rows 1, 2, 3 and 5
   and the summary line updated; the Paid entry lists both.
3. Minor, fixed (test first): a repeated thumbs-down (retry, double click) messaged again; `rate` now returns the note
   only when the message was not already down. Test: down, down, clear, down sends two notes.
4. Minor, fixed (test first): a malformed token raises `httpx.InvalidURL`, not an `HTTPError`, and its traceback could
   carry the token; `tell_maintainers` catches every exception and logs the type only. Test with `"bad token\n"`.
5. Minor, fixed: the eval no longer crashes when no answer began or a home has no devices.

Also corrected by me: the first full run was 78/84, not the 81/84 I first reported (each REFIT home failed the
biggest-device question 3 times: the checker compared English dataset names with Wappi's Vietnamese; verified by hand
against the service, fixed in the checker, rerun 84/84; written in docs/chatbot-eval.md).

Not checked by the reviewer: that the alerts page has the rating button. Checked here: `alerts/page.tsx` passes
`onFeedback={sendAlertFeedbackAction}` to `AlertList`, as do the overview and the device page.
