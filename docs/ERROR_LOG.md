# Error log

One line per real error. What broke, why, and the fix. Newest first.

Keep it honest. The point of this file is that the same mistake does not cost
two days twice.

| Date | What broke | Real cause | Fix |
|---|---|---|---|
| 23 Nov | Nightly backup failed in 5 seconds, every night | The 4 secrets it checks for were never created. The deployment skipped that step. | Reworked the job and wrote down the exact setup steps |
| 23 Nov | `count_rows.py` printed a warning on every run | The docstring contained `\.`, which Python reads as a bad escape | Made the docstring raw (`r"""`) |
| 23 Nov | `grep -oP` failed locally | `-P` depends on the system's language settings | Replaced with `sed`, which behaves the same everywhere |
| 23 Nov | A failed privacy check would have said "the repository is public" | The `curl` was inside a `$(...)` assignment, so any failure looked like the same error | Ran `curl` on its own line with its own message |
| 21 Sep | Could not sign in as the test client | Typed the username into the email box | None needed. The page says only "Wrong login details" on purpose, so it cannot say which part was wrong |
| 21 Sep | Sign-in emails did not reach other people | Resend's free plan only delivers to the account owner's address until a domain is verified | The screen now says so and offers a message to copy |
| 19 Sep | `/../../backend/.env` could be downloaded from the running site | The catch-all route served any path without checking it stayed inside the build folder | Added an `is_relative_to(DIST)` check |
| 19 Sep | Gemini returned 404 for a valid key | `gemini-2.0-flash-lite` is not available to new Google accounts | Switched to `gemini-3.5-flash-lite` |
| 19 Sep | The key checker rejected a valid key | It only accepted old `AIza` keys; Google now issues `AQ.` keys | Accept both |
| 19 Sep | Every chat turned into an "Enquiry" | The extractor saved a lead row even with no details | Delete the row when nothing was collected |
| 19 Sep | Names and emails were dropped after the third answer | The retry counter counted successes as failures | Reset the counter on success |
| 19 Sep | The price guard flagged the visitor's own budget | It treated every rupee figure as an invented price | Pass the visitor's own numbers through |
| 19 Sep | The bot kept using an old WhatsApp number | `company.yaml` was cached for the life of the process | Re-read it when the file's timestamp changes |
| 19 Sep | Scripts crashed on Windows with a psycopg error | Windows picks a loop psycopg cannot use | A `run()` helper, and the server must start with `--reload` |
