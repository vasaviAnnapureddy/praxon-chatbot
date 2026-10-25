# Running this project on your own laptop

For a teammate who wants to open the code in VS Code and run the website locally.

**You do not need this just to SEE the website.** The live link works in any
browser, on any phone. Follow this only if you want to read or change the code.

Time: about 20 minutes the first time.

---

## 1. Install these three things (once)

| What | Where | How to check it worked |
|---|---|---|
| **Python 3.12** | python.org/downloads | Tick **"Add Python to PATH"** during install |
| **Node.js 20 or newer** | nodejs.org (the LTS button) | — |
| **Git** | git-scm.com | — |
| **VS Code** | code.visualstudio.com | — |

Then open a terminal and check all three answer with a version number:

```bash
python --version
```
```bash
node --version
```
```bash
git --version
```

If a command says "not recognized", that program is not installed properly.
Install it again and restart VS Code.

---

## 2. Get the code

**Opening a terminal in VS Code:** menu **Terminal** -> **New Terminal**. A panel
opens at the bottom. That is where every command below is typed. `Ctrl + C`
inside it stops whatever is running.

Pick the folder you want the project in (`E:\` for example), then:

```bash
git clone https://github.com/vasaviAnnapureddy/praxon-chatbot.git
```

Then in VS Code: **File** -> **Open Folder** -> pick the new `praxon-chatbot`
folder.

(If you were sent a ZIP instead of a GitHub link: unzip it, open the folder in
VS Code, and skip the `git clone` command.)

---

## 3. Install the Python parts

In the VS Code terminal, inside the project folder:

```bash
python -m venv .venv
```

That makes a private box of Python libraries for this project only, so it never
clashes with other projects on your laptop.

```bash
.\.venv\Scripts\python.exe -m pip install -r backend\requirements.txt -c backend\constraints.txt
```

Takes 2-3 minutes. `constraints.txt` pins the exact versions that are known to
work, so you get the same ones as everybody else.

---

## 4. Install the website parts

```bash
cd frontend
```
```bash
npm install
```
```bash
npm run build
```
```bash
cd ..
```

`npm run build` turns the React code into plain files the server can serve.
You should see `✓ built in ...s`.

---

## 5. The secrets file

The project needs a database, an AI key and an email key. These are **not** in
the code (on purpose — keys must never go to GitHub).

Copy the example file:

```bash
copy backend\.env.example backend\.env
```

Now open `backend\.env` in VS Code and fill in the values. **Ask Vasavi for
them, and ask on WhatsApp or in person — never over email or chat groups.**

The ones that actually matter to get it running:

| Setting | What it is |
|---|---|
| `DATABASE_URL` | The Neon database address |
| `GEMINI_API_KEY` | The Google AI key (makes the assistant reply) |
| `JWT_SECRET` | Any long random text; it signs the login passes |
| `RESEND_API_KEY` | Only needed for sending emails. Leave empty and emails just won't send. |

Leave `APP_ENV=local` and `DEBUG=true` as they are.

**Rather not share keys?** Each person can make their own free ones in about
15 minutes. See `docs/DEPLOYMENT.md`, sections 1 to 3. Then run this once to
load the company content into your own database:

```bash
.\.venv\Scripts\python.exe -X utf8 backend\scripts\ingest.py
```

---

## 6. Start it

```bash
.\.venv\Scripts\python.exe -m uvicorn app.main:app --reload --app-dir backend
```

You should see:

```
Praxon Technologies assistant starting
Uvicorn running on http://127.0.0.1:8000
```

Hold **Ctrl** and click the link, or open **http://localhost:8000** yourself.

- Website + chat assistant: http://localhost:8000
- Sign in: http://localhost:8000/login

**Keep this terminal open.** Closing it switches the website off.
To stop it: click in the terminal, press **Ctrl + C**.

### Important
`--reload` is not optional on Windows. Without it the database refuses to
connect (a Windows-specific problem with how Python handles background work).
The terminal prints a loud warning if you forget.

---

## 7. While you work

| You changed | What to do |
|---|---|
| Any `.py` file | Nothing. It restarts by itself. |
| `client\company.yaml` | Nothing. It is re-read automatically. |
| `backend\.env` | Stop (Ctrl+C) and start again. |
| Anything in `frontend\` | `cd frontend`, `npm run build`, `cd ..`, then **Ctrl+F5** in the browser |
| Any file in `client\content\` | Run `ingest.py` (see step 5), so the assistant learns the new text |

`COMMANDS.txt` in the main folder explains every command in plain English.

---

## 8. If something breaks

| Message | What it means |
|---|---|
| `'.venv\...' is not recognized` | You missed the `.\` at the start |
| `cannot find the path` | You are in the wrong folder. `cd` to the project folder first. |
| `No React build at ...` | You skipped `npm run build` in step 4 |
| A long red block with `!!!!!!` | You left out `--reload` |
| `Can't reach the server` in the browser | The terminal with the server is closed or crashed. Look at it. |

Copy the **last 5 lines** of any red error when asking for help.

---

## Where things live

```
backend/app/api/        the web addresses (/api/chat, /api/auth, ...)
backend/app/graph/      the assistant's thinking steps and its instructions
backend/app/rag/        searching the company content by meaning
backend/app/db/         the database tables
frontend/src/pages/     the screens (website, chat, sign in, dashboard, portal)
frontend/src/api.js     every call the browser makes to the server
client/company.yaml     company name, colours, prices, contacts  <- edit this
client/content/*.md     what the assistant knows                 <- and this
client/brand/           the logo files
docs/                   deployment, restore, demo script
```

Everything about the company lives in `client/`. To make this for a different
company, you swap that folder. No code changes.
