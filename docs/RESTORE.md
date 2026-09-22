# Restoring the database from a backup

**Practise this once, on the dev branch, before you need it.** An untested
backup is not a backup — it is a file you hope is a backup.

Do the drill now, while nothing is wrong. It takes fifteen minutes.

---

## What you need

1. A backup file from the `praxon-backups` repository, e.g.
   `daily/praxon-2026-09-18.sql.gz.gpg`
2. The `BACKUP_PASSPHRASE` from your password manager
3. `gpg` and `psql` on your laptop

**Windows:** install [Gpg4win](https://gpg4win.org) for `gpg`, and
[PostgreSQL](https://www.postgresql.org/download/windows/) for `psql` (during
install you only need "Command Line Tools"). Then reopen your terminal.

Check both work:

```bash
gpg --version
```
```bash
psql --version
```

---

## Layer 1 first: is Neon's instant restore enough?

If the mistake happened **within the last 6 hours** (you deleted the wrong lead,
a bad ingest wiped content), do not touch the backup files. Neon can rewind:

1. Neon console → your project → **Branches** → `production`
2. **Restore** → pick a point in time before the mistake
3. Confirm

That is a few seconds and loses nothing after the restore point. Use it.

Only when the damage is older than 6 hours do you need the steps below.

---

## The drill (do this on `dev`, not `production`)

### 1. Download a backup

Go to your `praxon-backups` repository → `daily/` → click the most recent
`.gpg` file → **Download raw file**. Put it somewhere sensible, e.g.
`E:\praxon-restore\`.

### 2. Decrypt it

```bash
gpg --batch --decrypt --output praxon.sql.gz praxon-2026-09-18.sql.gz.gpg
```

It will ask for the passphrase. Paste `BACKUP_PASSPHRASE`.

You should see: a `praxon.sql.gz` file appear.

If it says **"decryption failed: Bad session key"**, the passphrase is wrong.
There is no recovery from a lost passphrase — that is why it lives in the
password manager.

### 3. Unzip it

```bash
gzip -d praxon.sql.gz
```

You should see: `praxon.sql`. Open it in a text editor and check the top — it
should start with PostgreSQL dump headers, and searching for `CREATE TABLE
public.leads` should find a hit.

### 4. Make a clean branch to restore INTO

Never restore over a live database. Make a fresh target:

1. Neon console → **Branches** → **Create branch**
2. Name: `restore-test`
3. Parent: `production`, **Create from: current state** — then immediately empty it:

   SQL Editor, with `restore-test` selected:
   ```sql
   DROP SCHEMA public CASCADE;
   CREATE SCHEMA public;
   CREATE EXTENSION IF NOT EXISTS vector;
   ```

You should see: no tables left on `restore-test`.

### 5. Restore

Copy the **pooled connection string for `restore-test`** from Neon, then:

```bash
psql "postgresql://user:pass@ep-xxx-pooler.ap-southeast-1.aws.neon.tech/neondb?sslmode=require" -f praxon.sql
```

You should see: a long stream of `CREATE TABLE`, `COPY`, `ALTER TABLE` lines.

Warnings that are **fine to ignore**:
- `role "neondb_owner" does not exist` — role names differ between branches
- `extension "vector" already exists` — you created it in step 4

Errors that are **not fine**: anything saying `syntax error` or
`relation ... does not exist` on a COPY. That means a corrupt dump — try the
previous night's file.

### 6. Verify the data is actually there

SQL Editor on `restore-test`:

```sql
SELECT
  (SELECT COUNT(*) FROM leads)         AS leads,
  (SELECT COUNT(*) FROM conversations) AS conversations,
  (SELECT COUNT(*) FROM messages)      AS messages,
  (SELECT COUNT(*) FROM documents)     AS documents,
  (SELECT COUNT(*) FROM admins)        AS admins;
```

You should see: counts that match roughly what the dashboard showed on the day
of that backup.

Then check the newest lead looks like a real lead:

```sql
SELECT id, name, email, timeline_label, created_at
FROM leads ORDER BY created_at DESC LIMIT 5;
```

### 7. Point the app at it, for real

In `backend/.env`, set `DATABASE_URL` to the `restore-test` string, then:

```bash
uvicorn app.main:app --reload --app-dir backend
```

Open `http://localhost:8000/admin`, sign in, and look at the leads. If they are
there and the conversations open, **your backup works**. That is the whole point
of the drill.

### 8. Clean up

Neon console → **Branches** → `restore-test` → **Delete**. Put `DATABASE_URL`
back to your dev string.

---

## The real emergency: restoring `production`

Same steps, one difference — do **not** restore over `production` directly.

1. Restore into a new branch, exactly as above. Call it `production-restored`.
2. Verify the data (steps 6 and 7).
3. **Only then** change Render's `DATABASE_URL` environment variable to point at
   `production-restored` and redeploy.
4. Keep the broken `production` branch for a few days. Do not delete evidence while
   you are still working out what happened.

This way the live site switches to known-good data in one environment variable
change, and you still have the damaged database to investigate.

---

## Restoring only the knowledge base

If the only problem is the content (a bad ingest, deleted chunks), you do not
need a backup at all. The content lives in `client/content/*.md` in Git:

```bash
python backend/scripts/ingest.py --force
```

`--force` re-embeds everything from the markdown files. Conversations and leads
are untouched.

---

## Backup health checklist — once a month, two minutes

- [ ] `praxon-backups` has a file from **last night**
- [ ] The repository is still **Private**
- [ ] The file is over 1 KB (the workflow fails on smaller, but check anyway)
- [ ] `BACKUP_PASSPHRASE` is still in the password manager
- [ ] `BACKUP_REPO_TOKEN` has not expired (they expire; set a calendar reminder)
- [ ] Every six months: run the whole drill again
