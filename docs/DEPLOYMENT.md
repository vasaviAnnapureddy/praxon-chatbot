# Deployment — click by click

Follow this top to bottom. Every step says what you should see if it worked.
Total time, first try: about 90 minutes.

Order matters: Neon first (the app needs a database string), then Resend, then
GitHub, then Render, then the keep-alive ping, then backups.

---

## 0. Before you start

Have these open in browser tabs:

- https://neon.tech
- https://resend.com
- https://github.com
- https://render.com
- https://cron-job.org
- https://aistudio.google.com/apikey (for the Gemini key)

Have a password manager open. You will create six secrets. Every one of them
goes into the password manager the moment it is created — not "later".

---

## 1. Neon (the database)

**1.1 Create the project**

1. Sign in at neon.tech (GitHub sign-in is fine).
2. **Create project**.
   - Name: `praxon-chatbot`
   - Postgres version: leave the default — **write it down**, you need it for
     the backup workflow.
   - Region: **AWS ap-southeast-1 (Singapore)**. Closest free region to India,
     and the same region Render will run in, which keeps the round trip short.
3. Create.

You should see: a project dashboard with a `production` branch and a `neondb` database.

**1.2 Turn on pgvector**

1. Left sidebar → **SQL Editor**.
2. Run:
   ```sql
   CREATE EXTENSION IF NOT EXISTS vector;
   ```

You should see: `CREATE EXTENSION` and no error. (The ingest script also does
this, but doing it here proves your project supports it before you go further.)

**1.3 Create the dev branch**

1. Left sidebar → **Branches** → **Create branch**.
2. Name it `dev`, parent `production`.

You should see: two branches. `production` is the live site's data. `dev` is where
your laptop points while you test, so your experiments never touch real leads.

**1.4 Copy both connection strings**

1. **Connection Details** (top of the project page).
2. Branch: `production`. Select **Pooled connection**. Copy the string.
3. Switch branch to `dev`. Copy that one too.

Both look like:
```
postgresql://neondb_owner:XXXX@ep-something-pooler.ap-southeast-1.aws.neon.tech/neondb?sslmode=require
```

The word **`-pooler`** must be in there. That is the pooled connection, and it is
what lets a small app survive more than a handful of visitors.

Save both in your password manager as "Neon production" and "Neon dev".

---

## 2. Gemini API key

1. https://aistudio.google.com/apikey → **Create API key**.
2. Copy it. Save it in the password manager.

You should see: a key starting with `AIza`.

---

## 3. Resend (email alerts)

1. Sign up at resend.com with the email address you want the alerts to arrive at.
2. **API Keys** → **Create API Key** → permission **Sending access** → create.
3. Copy the key (`re_...`). Save it. It is shown once.

**What to expect on the free tier:** until you verify a domain, Resend only
delivers to the address you signed up with, and only from
`onboarding@resend.dev`. That is fine — for the demo the alerts come to you.
When Praxon has a domain, verify it in Resend and change two environment
variables. No code changes.

---

## 4. GitHub

**4.1 Push the code**

From `E:\praxon-chatbot`:

```bash
git init
```
```bash
git add .
```
```bash
git commit -m "Praxon website assistant: full build"
```

Then create an **empty private repository** on github.com called
`praxon-chatbot` (no README, no .gitignore — the repo must be empty), and:

```bash
git remote add origin https://github.com/YOUR-USERNAME/praxon-chatbot.git
```
```bash
git branch -M main
```
```bash
git push -u origin main
```

You should see: your files on GitHub, and **no `.env` file anywhere**. Check
that now. If `backend/.env` is there, stop, delete the repository, and check
`.gitignore`.

**4.2 Make the repository private**

Settings → bottom of the page → **Danger Zone** → **Change visibility** →
**Make private**.

This is not optional once backups are switched on. The nightly backup is stored
as a workflow artifact, and artifacts follow the repository's read access. The
dump holds visitors' names, emails and phone numbers.

**4.3 Add the two secrets**

In **praxon-chatbot** → **Settings** → **Secrets and variables** → **Actions**
→ **New repository secret**. Two, that is all:

| Name | Value |
|---|---|
| `NEON_DATABASE_URL` | the pooled connection string for the branch you want backed up |
| `BACKUP_PASSPHRASE` | a long phrase you invent. **Save it in the password manager. It is the only thing that can decrypt your backups.** |

No access token and no second repository: the backup never pushes anything, so
nothing can trigger a Render redeploy at 1 am.

Then open `.github/workflows/backup.yml` and check `PG_VERSION` matches the
Postgres version you wrote down in step 1.1.

---

## 5. Prepare the database (from your laptop)

Point `backend/.env` at the **production** branch temporarily:

```bash
python backend/scripts/ingest.py
```

You should see: chunk counts per file, an embedding count, a total, then the
retrieval smoke tests — including the Telugu and Hindi ones — all saying OK.

Then add the login tables and copy your owner login across (safe to repeat):

```bash
python backend/scripts/upgrade_db.py --owner-email your@gmail.com
```

If this is a brand-new database with no owner yet, create one first:

```bash
python backend/scripts/create_admin.py
```

Now switch `backend/.env` back to the **dev** string, and re-run
`python backend/scripts/ingest.py` and `create_admin.py` once for dev as well.
Two databases, two admin rows.

---

## 5b. "Continue with Google" (team + client login)

Optional — password login works without it. About 10 minutes, once.

1. Go to **https://console.cloud.google.com** and sign in with your Google account.
2. Top bar → pick the **same project** your Gemini key was created in (or make one).
3. Left menu → **APIs & Services** → **OAuth consent screen** (newer consoles call
   it **Google Auth Platform** → **Branding** / **Audience**).
   - App name: `Praxon Technologies`. Support email: yours.
   - Audience / User type: **External**.
   - While the app is in **Testing**, only emails you add under **Test users** can
     sign in with Google. Add your own email and any team/client emails you test with.
4. Left menu → **Credentials** (or **Clients**) → **Create credentials** →
   **OAuth client ID** → Application type **Web application**.
5. **Authorized JavaScript origins** — add exactly:
   - `http://localhost:8000` (your laptop — use `localhost`, not `127.0.0.1`)
   - later, your live address, e.g. `https://praxon-chatbot.onrender.com`
   Leave "Authorized redirect URIs" empty — this sign-in doesn't use them.
6. **Create** → copy the **Client ID** (ends in `.apps.googleusercontent.com`).
7. Paste it into `backend/.env` as `GOOGLE_CLIENT_ID=...`, and on Render as the
   same variable. Restart the server.

You should see: a "Continue with Google" button on `/login`. It only lets in
emails that already exist in the Team or Clients tab — anyone else gets "no access".

---

## 6. Render (running the app)

1. render.com → sign in with GitHub.
2. **New** → **Web Service**.
3. Connect the `praxon-chatbot` repository. Authorise Render if asked.
4. Settings:
   - **Name**: `praxon-chatbot`
   - **Region**: **Singapore**
   - **Branch**: `main`
   - **Language / Runtime**: **Docker**
   - **Dockerfile path**: `./Dockerfile`
   - **Instance type**: **Free**
5. Scroll to **Environment Variables** → **Add** each of these:

| Key | Value |
|---|---|
| `APP_ENV` | `production` |
| `DEBUG` | `false` |
| `DATABASE_URL` | the Neon **production** pooled string |
| `LLM_PROVIDER` | `gemini` |
| `GEMINI_API_KEY` | your Gemini key |
| `GEMINI_MODEL` | `gemini-3.5-flash-lite` |
| `GEMINI_EMBED_MODEL` | `gemini-embedding-001` |
| `EMBED_DIM` | `768` |
| `RESEND_API_KEY` | your Resend key |
| `ALERT_FROM_EMAIL` | `onboarding@resend.dev` |
| `ALERT_TO_EMAIL` | your own email |
| `ALERTS_ENABLED` | `true` |
| `JWT_SECRET` | run `python -c "import secrets; print(secrets.token_urlsafe(48))"` and paste the output |
| `ADMIN_SESSION_HOURS` | `12` |
| `GOOGLE_CLIENT_ID` | the same Client ID as on your laptop (see section 5b) |
| `DAILY_LLM_CALL_CAP` | `500` |
| `ALLOWED_EMBED_ORIGINS` | `*` |
| `CLIENT_DIR` | `../client` |
| `FRONTEND_DIST` | `../frontend/dist` |

6. **Advanced** → **Health Check Path**: `/health`
7. **Auto-Deploy**: **Yes** (every push to main redeploys).
8. **Create Web Service**.

First build takes 5 to 10 minutes (it installs Node, builds React, installs
Python). Watch the log. You should see, near the end:

```
serving React build from /app/frontend/dist
Praxon Technologies assistant starting
Uvicorn running on http://0.0.0.0:10000
```

Your URL is `https://praxon-chatbot.onrender.com` (or whatever name you chose).

**Test it now:**
- `https://your-app.onrender.com/health` → `{"status":"ok",...}`
- `https://your-app.onrender.com/` → the Praxon site, bubble bottom right
- Open the bubble, ask "what services do you offer?" → words stream in

---

## 7. cron-job.org (stop Render sleeping)

Render's free plan sleeps a service after 15 minutes with no traffic, and waking
takes about a minute. A visitor will not wait a minute.

1. cron-job.org → create a free account.
2. **Create cronjob**.
   - Title: `praxon keep-alive`
   - URL: `https://your-app.onrender.com/health`
   - Schedule: **Every 10 minutes**
   - Save.
3. Open the job → **Test run**.

You should see: HTTP 200 and a response time under a second.

**Why `/health` and nothing else:** that endpoint never touches the database. If
the ping hit any endpoint that ran a query, it would wake Neon 4,320 times a
month and burn the 100 free compute hours by mid-month. This is the single most
important detail in the whole deployment.

---

## 8. Run the backup once, by hand

1. GitHub → **Actions** tab → **Nightly database backup** → **Run workflow**.
2. Watch it. Roughly 60 seconds.

You should see: a green tick, an **Artifacts** section on the run page holding
`praxon-backup-YYYY-MM-DD`, and a summary table giving the number of tables, the
number of rows, both file sizes, and a line confirming the encrypted file was
decrypted again and matched the original exactly.

If it fails on the pg_dump step with a version error, your `PG_VERSION` does not
match Neon. Fix it in `backup.yml`, push, run again.

**Then practise the restore.** Do not skip this — an untested backup is not a
backup. See `docs/RESTORE.md`.

---

## 9. Test it the way a visitor would

**On your phone, on mobile data, not your WiFi:**

1. Open the live URL.
2. Tap the bubble. It should open immediately.
3. Ask "how much does a website cost?" — first words within about a second.
4. Ask "do you sign an NDA?"
5. Answer the assistant's question when it asks about your timeline.
6. Give it a name and an email.

**Then check:**
- The alert email arrives in your inbox.
- `https://your-app.onrender.com/admin` → sign in → the lead is there, with the
  timeline label and the full conversation.
- **Export CSV** downloads.

**Also test in an incognito window**, so you know it works for someone who has
never visited before and has no localStorage.

---

## 10. Installing the widget on somebody else's site

This is the pitch. One line, anywhere before `</body>`:

```html
<script src="https://your-app.onrender.com/widget.js" defer></script>
```

That is the entire installation. It works on WordPress, Wix, Shopify, Webflow or
a hand-written HTML file.

---

## What breaks, and what to do

| Symptom | Cause | Fix |
|---|---|---|
| First visit takes ~60 seconds | Render slept | check the cron job is running and pointed at `/health` |
| First message slow, rest fast | Neon was paused | expected; the bubble fires `/api/warmup` to hide it |
| "Cannot reach the server" on the site | build failed | Render → Logs, read the last 30 lines |
| Chat replies "I don't have that in my notes" for everything | content not ingested into **production** | point `.env` at production, run `ingest.py` |
| No alert email | Resend still unverified, or wrong `ALERT_TO_EMAIL` | dashboard → **Test email** button tells you exactly what Resend said |
| Admin login fails | admin was only created on **dev** | run `create_admin.py` against main |
| Everything dies around the 20th of the month | keep-alive is hitting a database endpoint | it must hit `/health` and nothing else |

---

## What Praxon would pay for later

| Thing | Cost | Why |
|---|---|---|
| Render Starter | ~$7/month | no sleeping, no cold starts |
| Domain (praxontech.in) | ~₹900/year | `chat.praxontech.in` instead of onrender.com |
| Resend verified domain | free | alerts from `hello@praxontech.in`, delivered to anyone |
| Neon paid | from $19/month | only if data outgrows 0.5 GB — that is tens of thousands of chats |
| Gemini paid tier | pay per use | only if traffic outgrows the free quota |

Nothing above is needed for the demo, and none of it is needed on day one for a
real client either.
