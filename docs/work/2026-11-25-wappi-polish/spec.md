# Spec: Wappi polish (lane M)

Goal (user, 2026-11-25): Wappi's sources repeat and run long; the maintainers should hear about a bad answer; the
chatbot's speed and accuracy should be measured, not guessed; shared links to dashboard pages should preview.

R1 Citations: the model cites each source once (prompt). In the dashboard a source is marked once, at its first
   figure, as a bare number chip (`citedSegments`); the sources used are one legend line under the answer, linked
   (internal ones through the locale-aware `Link`); the Hairline "n sources" stack is gone; marks with no source behind
   them (streaming, wrong number) go with the space before them.
R2 `ai_message.usage` gets `first_ms` (until the first word shows) and `ms` (the whole answer).
R3 A thumbs-down on a Wappi answer posts the question and the answer to a Telegram chat, only when
   `FEEDBACK_TELEGRAM_TOKEN` and `FEEDBACK_TELEGRAM_CHAT` are both set; it runs after the response (background task);
   a Telegram failure never fails the rating and the bot token never reaches the logs. A thumbs-up or clearing sends
   nothing.
R4 Dashboard pages declare the Open Graph and Twitter image (`/og.png`, served by the landing at the same domain).
R5 The alert email links to the alerts page, where the alert is rated.
R6 `scripts/eval_wappi.py`: asks Wappi seven kinds of question on a demo home (bill, kWh today, kWh this cycle, biggest
   device, off-topic, prompt injection, a pasted phone number); the answers are judged against what the services
   compute, not against the model; reports correct answers, first-word and whole-answer time, tokens per answer.

Areas of concern
- The note holds the stored question (personal data already masked before it was stored) and the answer; it goes to a
  third party the user chose. Nothing else (no email, no home name) is added.
- Chip numbers mean nothing without the legend: the legend must show for every chip.
- The eval writes a conversation into the dev database and deletes it; it spends a little (about 0.0004 USD an answer).
- A checker that is wrong makes Wappi look wrong: the first run scored the biggest-device question against the
  dataset's English appliance names while Wappi answers in Vietnamese; the checker now accepts both (verified by hand
  against the service).
