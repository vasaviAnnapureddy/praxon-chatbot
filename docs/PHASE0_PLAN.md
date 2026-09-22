# Phase 0 — Project Plan (Praxon Website Assistant)

This is the map of the whole project. Read this once before touching any code.

---

## 1. What we are building, in one paragraph

A demo website for **Praxon Technologies Private Limited** (Hyderabad IT services
company) with a smart chat assistant built into it. The assistant answers visitor
questions from Praxon's own content, routes job seekers to the careers email,
refuses junk, and quietly collects lead details (requirement, budget, timeline,
name, contact) while chatting. A founder-only dashboard shows the leads and
conversations. Everything Praxon-specific lives in `client/`, so swapping in
their real content takes minutes and zero code changes.

---

## 2. The five boxes (system architecture)

```
   +--------------+  git push   +--------------+  auto-deploy  +-------------------+
   |  MY LAPTOP   | ----------> |   GITHUB     | ------------> |  RENDER (the app) |
   |  VS Code     |             |  code only   |               |  FastAPI + React  |
   |  Docker test |             |  private     |               |  Singapore, free  |
   +------+-------+             +------+-------+               +---------+---------+
          |                            |                                 |
          | ingest.py                  | nightly backup.yml              | SQL over TLS
          | (loads content)            | (encrypted dump)                |
          v                            v                                 v
   +--------------------------------------------------------------------------+
   |                     NEON  -  cloud Postgres + pgvector                     |
   |   production branch = live data  dev branch = my local testing             |
   |   tables: documents, conversations, messages, leads, unanswered, admins    |
   +--------------------------------------------------------------------------+
          ^                                     |
          |                                     | new lead with contact details
          |                                     v
   +------+--------+                    +--------------+        +--------------+
   | cron-job.org  |  GET /health       |   RESEND     | -----> | Founder's    |
   | every 10 min  |  (never hits DB)   |  email API   |        | inbox        |
   +---------------+                    +--------------+        +--------------+

   LLM calls (Gemini by default, Claude or OpenAI optional) go OUT from Render only.
   The browser NEVER sees an API key.
```

**Why the boxes are separate**

| Box | Holds | If it dies |
|---|---|---|
| GitHub | the code | laptop still has it |
| Neon | ALL the data | nothing else stores data, so nothing is lost elsewhere |
| Render | nothing | redeploy from GitHub in 3 minutes |
| Resend | nothing | swap for Brevo, one file changes |

That is the whole "never lose anything" design: **the host is disposable.**

---

## 3. Conversation flow (what happens when a visitor types)

```
visitor types  -->  POST /api/chat  (streaming)
                          |
                          v
              +---------------------------+
              | 1. input_guard            |  length, spam, injection, rate limit,
              |                           |  daily LLM cap
              +-----------+---------------+
                          | blocked --> canned safe reply (no LLM call)
                          v
              +---------------------------+
              | 2. save user message      |  DB first, so a Render restart
              +-----------+---------------+  can never lose it
                          v
              +---------------------------+
              | 3. route_intent           |  fast keyword rules first,
              |                           |  LLM only if rules are unsure
              +-----------+---------------+
                 careers --+-- spam/offtopic --+-- everything else
                    |            |             |
                    |            |             v
                    |            |    +------------------+
                    |            |    | 4. retrieve      | pgvector top-k chunks
                    |            |    +--------+---------+
                    |            |             v
                    |            |    +------------------+
                    |            |    | 5. compose       | system prompt + chunks
                    |            |    |    + pick ONE    | + history + maybe one
                    |            |    |    lead question | lead question
                    |            |    +--------+---------+
                    v            v             v
              +---------------------------------------+
              | 6. STREAM the answer word by word     | <- visitor sees words in ~1s
              +---------------+-----------------------+
                              v
              +---------------------------------------+
              | 7. output_guard + save assistant msg  |
              +---------------+-----------------------+
                              v
              +---------------------------------------+
              | 8. BACKGROUND: extract lead details,  | <- after the reply,
              |    set timeline label, email alert    |    never before
              +---------------------------------------+
```

**Golden rule of the flow:** the visitor's question is answered first, every time.
A lead question is only ever *appended* to an answer, never sent instead of one,
and never twice in one message.

---

## 4. The words you don't know yet, in plain English

| Word | What it actually is | Why it's here |
|---|---|---|
| **React** | a JavaScript library that redraws the screen when data changes | the chat window and the dashboard are live, changing screens |
| **Vite** | the tool that runs React while I develop, and squeezes it into small files for production | `npm run dev` for instant reload; `npm run build` for the real site |
| **Docker** | a box that holds the app + Python + Node so it runs the same on my laptop and on Render | removes "works on my machine" |
| **Postgres** | the standard SQL database - tables, rows, columns | leads and messages must survive forever |
| **pgvector** | a Postgres add-on that stores *meaning* as a list of numbers and finds similar ones | how "what do you charge?" finds the pricing page |
| **Embedding** | that list of numbers for a piece of text | Telugu and English text about pricing land near each other |
| **RAG** | Retrieval Augmented Generation: find real content first, then let the LLM write using ONLY that | stops the bot inventing clients and prices |
| **LangGraph** | a way to write the conversation as named steps with a shared memory box | I can point at exactly where guardrails or routing happen |
| **SSE** | Server-Sent Events - the server keeps the connection open and pushes words as they come | the typing effect, first word in ~1s |
| **FastAPI** | the Python web server framework | serves the API *and* the built React files - one Render service |

---

## 5. Folder structure, one line each

```
praxon-chatbot/
├── client/                  <- THE SWAP ZONE. New client = only this folder changes.
│   ├── company.yaml         Name, colours, logo, contacts, budget chips, quick questions.
│   └── content/
│       ├── about.md         Who Praxon is, founder background, honest trust answers.
│       ├── services.md      What they build (web, mobile, AI, cloud, maintenance).
│       ├── process.md       How a project runs, NDA, code ownership, support.
│       ├── pricing.md       Ranges only - never exact quotes.
│       ├── faqs.md          Common visitor questions, answered.
│       ├── careers.md       Open roles + careers email.
│       └── policies.md      Privacy, data handling, DPDP consent wording.
│
├── backend/
│   ├── app/
│   │   ├── main.py          Starts FastAPI, mounts the API and the built React files.
│   │   ├── config.py        Reads .env + company.yaml into one settings object.
│   │   ├── core/
│   │   │   ├── logging.py    Logs with emails/phones masked (privacy).
│   │   │   ├── rate_limit.py Per-visitor limits + the daily LLM call cap.
│   │   │   ├── security.py   Admin password hashing and login tokens.
│   │   │   └── timezone.py   Server stores UTC; founder always sees IST.
│   │   ├── llm/
│   │   │   ├── provider.py   One interface, three backends (Gemini/Claude/OpenAI).
│   │   │   └── embeddings.py Turns text into vectors (multilingual).
│   │   ├── rag/
│   │   │   ├── loader.py      Reads .md/.pdf from client/content and chunks it.
│   │   │   ├── vectorstore.py Writes/reads chunks in Neon pgvector.
│   │   │   └── retriever.py   Finds the best chunks for a question.
│   │   ├── graph/
│   │   │   ├── state.py      The shared memory box passed between steps.
│   │   │   ├── prompts.py    Every system prompt and rule, in one place.
│   │   │   ├── nodes.py      The steps: guard, route, retrieve, compose.
│   │   │   └── builder.py    Wires the steps together into the LangGraph.
│   │   ├── guardrails/
│   │   │   ├── input_guard.py  Blocks injection, spam, oversized messages.
│   │   │   └── output_guard.py Strips invented prices/claims before sending.
│   │   ├── leads/
│   │   │   ├── extractor.py  Background job: pulls lead fields out of the chat.
│   │   │   └── stages.py     Turns a timeline answer into a factual label.
│   │   ├── db/
│   │   │   ├── database.py   Neon connection (pooled, SSL).
│   │   │   ├── models.py     The tables.
│   │   │   └── crud.py       All the queries, in one place.
│   │   ├── notify/email_alert.py  Sends the lead email through Resend.
│   │   └── api/
│   │       ├── health.py     /health - NEVER touches the database (saves Neon hours).
│   │       ├── warmup.py     /api/warmup - wakes Neon when the bubble is clicked.
│   │       ├── chat.py       /api/chat - the streaming chat endpoint.
│   │       └── admin.py      Login, leads, conversations, stats, CSV export.
│   ├── scripts/
│   │   ├── ingest.py         One command: load client/content into Neon.
│   │   └── create_admin.py   One command: create the founder's login.
│   ├── tests/
│   │   ├── eval_questions.json  50+ test questions with expected behaviour.
│   │   └── run_eval.py          Runs them, flags failures, reports speed.
│   ├── requirements.txt     Python libraries (kept lean for 512 MB RAM).
│   └── .env.example         Every secret name, with fake values.
│
├── frontend/
│   ├── public/widget.js     The one file a client pastes into their site.
│   └── src/
│       ├── api.js           All calls to the backend, relative URLs only.
│       ├── pages/
│       │   ├── DemoSite.jsx       The Praxon landing page.
│       │   ├── ChatWindow.jsx     The chat UI (loads inside the iframe).
│       │   ├── AdminLogin.jsx     Founder login.
│       │   └── AdminDashboard.jsx Leads, conversations, stats, unanswered.
│       ├── components/      Small reusable pieces of those pages.
│       └── styles/app.css   All styling; colours come from company.yaml.
│
├── .github/workflows/backup.yml  Nightly encrypted DB backup to a private repo.
├── Dockerfile               Build React -> copy into Python image -> one service.
├── .gitignore               Keeps .env and node_modules out of Git.
└── README.md                Setup, swap, deploy, backup, restore.
```

---

## 6. The eleven build phases

| Phase | What gets built | Done when |
|---|---|---|
| 0 | This plan | you understand the five boxes |
| 1 | Git, backend skeleton, config, `/health` | `/health` returns ok locally |
| 2 | Neon branches, pgvector, tables | tables visible in Neon console |
| 3 | Ingest content, test retrieval (incl. Telugu/Hindi) | a Telugu question finds English pricing text |
| 4 | LangGraph flow, guardrails, streaming | words stream into the terminal |
| 5 | Lead capture, alerts, contact options | a lead row appears + email arrives |
| 6 | React chat window + widget.js | bubble opens on a test page |
| 7 | Admin dashboard | founder sees leads, exports CSV |
| 8 | Praxon demo website | landing page with the widget installed |
| 9 | Docker + speed tuning + full eval | first word under 1.5 s, eval passes |
| 10 | Render + Neon + Resend + cron + backups live | public https link works on the phone |
| 11 | README + 2-minute demo script | you can pitch it |

---

## 7. Decisions already locked (and the alternative we rejected)

| Decision | Why | Alternative rejected because |
|---|---|---|
| FastAPI serves API **and** React | Render free = 750 hours = ONE always-on service | two services would exceed the free hours |
| Neon, not Render Postgres | Render's free DB expires in 30 days | data loss |
| pgvector, not Chroma | Chroma writes files; Render wipes files | data loss on every restart |
| Resend, not Gmail SMTP | Render blocks SMTP ports on free | emails would silently never arrive |
| psycopg3 driver | handles Neon's `sslmode=require` URL as-is | asyncpg needs manual SSL surgery |
| Gemini Flash default | fastest + cheapest + multilingual embeddings in one key | Claude/OpenAI still switchable by one config line |
| iframe widget | host site CSS can't break us, our CSS can't break them | injecting React into their page = conflicts |
| Timeline label, no score | founder decides who is worth calling, not the bot | scoring hides good leads behind a number |

---

## 8. What I run on my laptop (Windows)

```
E:\praxon-chatbot>  python -m venv .venv
E:\praxon-chatbot>  .venv\Scripts\activate
E:\praxon-chatbot>  pip install -r backend\requirements.txt
E:\praxon-chatbot>  python backend\scripts\ingest.py
E:\praxon-chatbot>  uvicorn app.main:app --reload --app-dir backend
E:\praxon-chatbot>  cd frontend && npm install && npm run dev
```
