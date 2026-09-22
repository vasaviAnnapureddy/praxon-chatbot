# Praxon Website Assistant

A company website with a smart assistant built into it.

The assistant answers visitor questions from the company's own content, sends
job seekers to the careers email, refuses junk, and quietly collects enquiry
details while it chats. A founder-only dashboard shows every enquiry and every
conversation. Everything company-specific lives in one folder, so pointing this
at a different client takes minutes and zero code changes.

Built for a pitch to **Praxon Technologies Private Limited**, Hyderabad.

```
   Visitor  ──▶  Render (FastAPI + React)  ──▶  Neon Postgres + pgvector
                         │                            ▲
                         │                            │ nightly encrypted dump
                         ▼                            │
                   Gemini / Claude / OpenAI      GitHub (code + backups)
                         │
                         ▼
                    Resend ──▶ founder's inbox
```

---

## What it does

| | |
|---|---|
| **Answers from real content** | Retrieval over the company's own markdown. If nothing matches, it says so instead of inventing an answer, and files the question for the founder. |
| **Speaks the visitor's language** | English, Telugu, Hindi, and mixed (Tenglish/Hinglish). A Telugu question finds English content — the embeddings are multilingual. |
| **Collects enquiries without interrogating** | One question at a time, only after answering something, never twice, never again once skipped. |
| **Never judges a lead** | It records what was said and attaches a factual timeline label. No score, no rating, no "hot lead". The founder decides. |
| **Routes job seekers away from sales** | Careers questions get the careers email and the open roles, and skip the enquiry flow entirely. |
| **Resists attacks** | Prompt injection, spam, off-topic work requests and oversized messages are blocked before they cost an API call. |
| **Cannot run away with your quota** | Per-visitor rate limits plus a hard daily cap on model calls, stored in the database so a restart cannot reset it. |
| **Installs anywhere in one line** | `<script src=".../widget.js" defer></script>` — an isolated iframe, no React on the host page. |

---

## Quick start (Windows)

You need Python 3.11+, Node 20+, and a free [Neon](https://neon.tech) database.

```bash
python -m venv .venv
```
```bash
.venv\Scripts\activate
```
```bash
pip install -r backend\requirements.txt
```

Copy `backend\.env.example` to `backend\.env` and fill in two things to start:
your Neon **dev** branch connection string, and a
[Gemini API key](https://aistudio.google.com/apikey).

Load the content into the database:

```bash
python backend\scripts\ingest.py
```

You should see chunk counts, then retrieval tests — including Telugu and Hindi —
all passing. Then create your dashboard login:

```bash
python backend\scripts\create_admin.py
```

Run the backend:

```bash
uvicorn app.main:app --reload --app-dir backend
```

And in a second terminal, the frontend:

```bash
cd frontend && npm install && npm run dev
```

Open **http://localhost:5173**

- `/` — the demo website with the chat bubble
- `/chat` — the chat window on its own
- `/admin` — the founder's dashboard

---

## Where everything lives

```
client/            THE SWAP ZONE — change this, get a different company
  company.yaml     name, colours, contacts, budget chips, quick questions
  content/*.md     about, services, process, pricing, faqs, careers, policies

backend/app/
  api/             the endpoints (health, warmup, chat, admin)
  graph/           the conversation: state, prompts, nodes, builder
  rag/             load content, embed it, search it
  guardrails/      what never reaches the model, what never reaches the visitor
  leads/           background extraction, timeline labels
  db/              Neon connection, tables, every query
  llm/             one interface, three providers
  core/            logging (PII masked), rate limits, admin auth, IST

frontend/src/
  pages/           DemoSite, ChatWindow, AdminLogin, AdminDashboard
  components/      the pieces those pages are made of
  public/widget.js the one file a client installs

docs/
  PHASE0_PLAN.md   architecture, conversation flow, what every folder is for
  DEPLOYMENT.md    click-by-click: Neon, Resend, GitHub, Render, cron, backups
  RESTORE.md       the backup restore drill — do it once before you need it
  DEMO_SCRIPT.md   the two-minute pitch
```

---

## Swapping in a different client

This is the product, so it is worth knowing cold.

1. Edit `client/company.yaml` — name, colours, contacts, WhatsApp number,
   booking link, budget ranges, quick questions, the landing page text.
2. Rewrite the seven files in `client/content/` with their real content.
3. ```bash
   python backend\scripts\ingest.py
   ```
4. Reload the page.

Different company, different colours, different answers. No Python or React was
edited. That is the whole pitch, and it takes about ten minutes.

---

## The three storage rules

The reason nothing can be lost:

| What | Where | If it disappeared |
|---|---|---|
| **Code** | GitHub + your laptop | redeploy from GitHub |
| **Data** | Neon, nowhere else | restore from a nightly encrypted backup |
| **The app** | Render, stores nothing | rebuild in three minutes |

The host is disposable on purpose. Nothing important is ever written to
Render's disk, because Render erases that disk on every restart.

Three backup layers: Neon's 6-hour instant restore, a nightly encrypted dump to
a private repository (30 nights kept), and CSV export from the dashboard at any
time.

---

## Speed

Targets from the brief, and how they are met:

| Target | How |
|---|---|
| Bubble visible instantly | `widget.js` draws it before any network call |
| First words in 1–1.5 s | streamed token by token; the graph does all its thinking before generation starts |
| Quick replies near-instant | cached in memory, no model call at all |
| Database never adds a delay | the bubble warms Neon on hover, before the visitor types |
| Site never sleeps | a free ping every 10 minutes to `/health`, which never touches the database |

Measure it yourself against a running server:

```bash
python backend\tests\run_eval.py --url https://your-app.onrender.com
```

That runs 58 single questions plus 5 multi-turn threads, separates guardrail
failures from ordinary ones, and prints average, median and p95 time to first
word.

---

## Provider switching

`LLM_PROVIDER=gemini` in `backend/.env` switches to `claude` or `openai` with no
other change. Gemini is the default because one key covers both generation and
multilingual embeddings, and the Flash-class model is fast enough for the
first-word target.

Embeddings always use Gemini (or OpenAI as a fallback) regardless — Anthropic
has no embeddings API, and vectors from two different models are not comparable,
so the embedding model must not change after content has been ingested.

---

## Deploying

Full click-by-click walkthrough in **[docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)**:
Neon branches and pgvector, Resend, GitHub secrets, Render (Docker, Singapore,
free plan, health check path), the cron-job.org keep-alive, and the backup
workflow.

The short version: it is one Render web service, because Render's free tier
gives 750 instance hours a month and a month has at most 744 — one always-awake
service fits, two do not. FastAPI serves the API and the built React site from
the same process.

---

## What Praxon would pay for later

| | Cost | Why |
|---|---|---|
| Render Starter | ~$7/month | removes sleeping entirely |
| Domain | ~₹900/year | `praxontech.in` instead of `onrender.com` |
| Resend verified domain | free | alerts from their own address, to anyone |
| Neon paid | from $19/month | only past 0.5 GB — tens of thousands of chats |

None of it is needed for the demo, and none of it is needed on day one.

---

## Security and privacy

- API keys live on the server only. The browser never sees one.
- Emails and phone numbers are masked in logs.
- A consent line is shown before any contact detail is requested.
- Leads (and the conversation behind them) can be deleted from the dashboard.
- Admin login is rate limited; passwords are PBKDF2-SHA256 with 390,000 iterations.
- Backups are AES-256 encrypted in a private repository.
- Interactive API docs are switched off in production.

---

## Honest limits

Worth knowing before you promise anything in a meeting:

- On the free plan the first visitor after a quiet spell may wait a moment while
  Neon's compute wakes. The bubble's warm-up call hides most of it, not all.
- The daily model-call cap is a real cap. When it is reached the assistant stops
  generating and offers contact options instead — by design, but it does stop.
- Resend will only email you until a domain is verified.
- The content is placeholder text written to be realistic. It is clearly marked
  as such, and must be replaced with Praxon's real words before anything goes
  live for them.
