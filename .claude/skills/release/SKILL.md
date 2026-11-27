---
name: release
description: Release the Marketer App to production (Render server, Vercel client) after the user said to deploy. Runs the checks, applies migrations, commits only the feature's files, pushes to origin and tells the user what to do on Render and what to test.
---

# Release the Marketer App

Only when the user said to deploy or push ("push it", "deploy", "test it live"). Never on your own initiative.

## 1. Check the working tree

- `git status --short`. Commit only the files of the feature you built. Leave the user's own unrelated changes
  (e.g. notes in `docs/`, `.github/dependabot.yml`) and anything untracked you did not create (`server/node_modules/`).
- No book PDFs, no `.env` files, no keys in the diff (`git diff --cached` before committing).

## 2. Run the checks (all must pass; report failures as they are)

```sh
cd server && uvx ruff check . && uv run pytest -q
cd ../client && npm run lint && npx tsc --noEmit
```

Client tests (`npm test`) only from `E:\` (upper-case drive letter) on Windows.

## 3. Database

- `cd server && uv run alembic current` and `uv run alembic heads`. If they differ, run `uv run alembic upgrade head`:
  the local server and Render share the Supabase database, so the migration is live for both at once.
- Migrations must be additive (a new column with a default), so Render's old code keeps working until it is deployed.

## 4. Commit and push

- One commit per feature; message: what changed for the author, then the details. End with the attribution lines
  the session asks for.
- `git push origin main`. Never push to another remote unless the user names it.

## 5. Tell the user

- **Render**: press Manual Deploy for the server (it does not deploy on push).
- **Vercel**: deploys the client from the push by itself, in a few minutes.
- **Telegram**: stop the local server, or keep `TELEGRAM_POLLING=false` there, so only Render answers the bot.
- **What to test** on the live app, step by step, for this release.
- Anything you could not verify (e.g. a real sign-in, a real model answer).
