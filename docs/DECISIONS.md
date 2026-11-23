# Decisions and running state

The short answer to "why is it built this way". Newest decisions at the top.
Update this file before changing code, not after.

---

## Agreed so far

| # | Decision | Date | Why |
|---|---|---|---|
| 12 | `praxon-chatbot` stays **public**; backups go to a **private** `praxon_assistant_backup` | 23 Nov 2026 | The code is a portfolio piece and should be readable. The data is not. |
| 11 | Backups verify themselves: tables, rows, truncation, and a decrypt-and-compare | 23 Nov 2026 | A backup nobody has opened is a guess |
| 10 | Nightly backup kept, not switched off | 23 Nov 2026 | Neon Free keeps only a 6-hour history window and has no scheduled backups |
| 9 | Logo files live in `client/brand/`, served at `/brand` | 21 Sep 2026 | Everything company-specific stays in `client/` |
| 8 | One sign-in page at `/login`; the role decides the destination | 21 Sep 2026 | Real companies have one door, not three |
| 7 | No sign-ups. Accounts are created by the owner or the team | 21 Sep 2026 | Clients and staff are known people, not strangers |
| 6 | Temporary passwords: system-made, 7-day expiry, must be changed on first sign-in | 21 Sep 2026 | Nobody should know another person's password |
| 5 | Team members see only the projects they are assigned to | 21 Sep 2026 | Least privilege |
| 4 | Every chatbot reply ends with exactly one question | 21 Sep 2026 | Keeps the conversation moving |
| 3 | A below-range budget gets honesty and a request for contact, never a promise | 21 Sep 2026 | Never commit the team to something they have not seen |
| 2 | The bot never scores or rates a lead | 19 Sep 2026 | The founder decides, not the model |
| 1 | Everything company-specific lives in `client/`; no code changes to re-skin | 18 Sep 2026 | That swap is the product |

---

## Differences from the original spec

| What the spec said | What was built | Why |
|---|---|---|
| Backups in a second repository | Changed to artifacts on 23 Nov, then changed back the same day | Artifacts are only safe on a private repository, and this one is public |
| `gemini-2.0-flash-lite` | `gemini-3.5-flash-lite` | The named model returns 404 for new Google accounts |
| Production Neon branch for the live site | The **dev** branch | Faster to demo; swap one variable when it goes real |

---

## Open, not done

- Retrieval quality has **no numbers**. There is a 63-case behaviour suite, but
  nothing measures whether the right chunk was retrieved. This is the single
  biggest gap for a reader judging the project.
- No restore rehearsal into a real Postgres. The nightly check proves the file
  opens and is whole, not that Postgres will accept it.
- `client/content/*.md` still holds `[FOUNDER TO CONFIRM]` placeholders, and the
  price ranges are examples, not Praxon's real prices.
- Render's free plan sleeps after 15 idle minutes, so the first visit can take
  about a minute. No keep-alive ping is set up.
