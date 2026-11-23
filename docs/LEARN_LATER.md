# Learn later

Things worth understanding properly, from building this. Not now, during the
build. Open a short teacher session with this list when there is time.

One line each. Tick them off.

## From the backup work (23 Nov 2026)

- [ ] Why `set -euo pipefail` is the first line of almost every shell script
- [ ] What a SHA-256 checksum proves, and what it does not
- [ ] Symmetric encryption (one passphrase) vs public-key encryption (two keys)
- [ ] Why deleting a file from Git does not make the repository smaller
- [ ] What a fine-grained token is, and why "least privilege" matters
- [ ] Why a scheduled job must be able to fail loudly

## From the chatbot

- [ ] What an embedding actually is, and why 768 numbers can carry meaning
- [ ] Cosine distance, and why it beats keyword matching for meaning
- [ ] Why RAG is used instead of fine-tuning for company facts
- [ ] What a system prompt is, and why visitor text can never override it
- [ ] Server-Sent Events: how the reply streams word by word
- [ ] Why `temperature` is set to 0.3 and not 0.7

## From the login work

- [ ] What PBKDF2 does, and why passwords are never stored as text
- [ ] What a JWT is, and why it is checked on every single request
- [ ] Why the same error message is shown for a wrong email and a wrong password
- [ ] What a honeypot field is, and why bots fill it in

## From deployment

- [ ] What Docker actually does, and why the image has two stages
- [ ] Why the server installs exact pinned versions, not the newest
- [ ] Why the frontend uses relative addresses like `/api/chat`
- [ ] What a reverse proxy is, and what `x-forwarded-proto` is for

## Coming in the retrieval eval

- [ ] Precision and recall, in plain words
- [ ] What "the right chunk was in the top 4" means as a measurement
- [ ] Why BM25 keyword search catches things vector search misses
- [ ] What a reranker does, and why it runs after retrieval, not instead of it
