# Security

How the Marketer App is protected, what it does not protect against, and how to report a problem. Details of each
measure are in [FEATURES.md](FEATURES.md) ("Security & guardrails"); this page is the overview.

## Reporting a vulnerability

Please do not open a public issue. Use GitHub's private report instead: the repository's **Security** tab →
**Report a vulnerability**. Say what you found, how to reproduce it and what an attacker could do with it. This is a
one-person project: expect an answer within a week.

## What is protected

| Asset | Where it lives |
|---|---|
| The users' books (unpublished manuscripts included), their chunks and summaries | Supabase Storage (private bucket), PostgreSQL |
| Generated texts, chats, discussion analyses, ad pictures | PostgreSQL, Storage |
| Access to a user's Facebook Page and YouTube channel (the app can post there) | PostgreSQL, encrypted |
| Personal API keys for the MCP servers | PostgreSQL, as hashes |
| The model budget (every model call costs money) | OpenRouter key on the server |
| The server's own secrets (Supabase secret key, database URL, OpenRouter, Meta, Google, Telegram) | Environment variables on the host |

## Who could attack, and what stops them

| Threat | Measures |
|---|---|
| **A visitor without an account** calls the API | Every endpoint and both MCP servers need a sign-in (Supabase access token, checked locally: signature, expiry, issuer, audience) or a personal API key. A test goes through all routes of the real app, so a new endpoint without the check fails (`test_routes_need_sign_in.py`). The API description (`/docs`) and the MCP servers are off in production. |
| **A signed-in user** reaches another user's data | Ownership is checked on every endpoint; another user's id answers 404 exactly like an unknown one (`test_ownership.py`). The database tables have row-level security without a policy and the secret-like ones are in a schema Supabase's REST API does not serve, so the browser's public key reads nothing. |
| **The public demo's guest** (a shared account anyone can use) | May not upload or delete books, create keys, use the MCP servers, connect or post to Facebook or YouTube, or run the agent; own budgets; starts limited per IP address; the demo resets when idle. A test forces a decision for every route (`test_guest.py`). |
| **Running up costs** (many or expensive model calls) | Requests per minute and cost budgets per day and month, per user, for the guest and for the whole app (`limits.toml`, fail closed). A cost spike alerts the admin in Telegram and switches the demo off; `/freeze` stops all model calls. |
| **Prompt injection by the user** (a brief or question that tries to change the instructions) | Input guard on every text field: cleaned, length-limited, likely injections refused (400). |
| **Prompt injection by other people's text** (a comment, a Reddit thread, a pasted post, a book) | Such text reaches the model only quoted as data, with tags it cannot close; it is scanned and flagged; the output guard checks every drafted reply for instruction phrases and foreign links; nothing is posted without the author's approval (a click, or a confirmation in Telegram). |
| **A malicious upload** | Only PDF: extension, size, file signature and checksum are checked in a temporary file before anything is stored; fixed object names (no path from the file name). |
| **Stolen credentials at rest** (a database leak) | API keys only as SHA-256 hashes, shown once. Page and channel tokens encrypted (Fernet, key only in the environment). No secret in the repository; CI scans every commit (gitleaks). |
| **Attacks in the browser** (injected script, clickjacking) | Content Security Policy, `frame-ancestors 'none'`, `nosniff`, referrer policy, HSTS on the client; strict headers and `no-store` on the API. Files are fetched with the access token and shown from `blob:` addresses, never as public links. CORS allows only the client's own origins. |
| **A forged OAuth return** (Facebook Login, Google sign-in) | The `state` is signed, short-lived and single-use, and names the user; the browser is sent back only to an allowed origin. |
| **Server-side requests to attacker-chosen addresses** | The only user-given address is a Substack name: checked against a strict pattern, fetched over https only, redirects followed by hand, size capped. |
| **Vulnerable or hijacked dependencies** | `pip-audit` and `npm audit` on every push and weekly; Dependabot; GitHub Actions pinned to commit hashes. |
| **Someone else in the Telegram chat** | The bot acts only on messages from the one configured private chat. |

## Knowing what happened

- **Audit log** (`server/app/core/audit.py`, table `private.audit_events`, `GET /audit` for the admin): API keys
  created, revoked and refused; a Page or channel connected or disconnected; every post, reply and comment published
  (by a click or by the agent); books uploaded and deleted; blocked inputs and outputs; refused admin or guest
  actions; the demo's starts, resets and refusals; the app switches. Ids and short facts only: never a secret, never
  a text someone wrote.
- **Logs**: one JSON line per event with the request id, which also appears in the usage log and the audit log.
- **Usage log**: every model call with its cost, per user.

## Known limits

- **The injection guard is a heuristic.** Measured against a red-team set (`eval/run_guard_eval.py`): 62% of the
  attacks caught and 6% false alarms on texts the rules were not tuned on. Free paraphrases mostly get through.
  That is why outside text is always quoted as data and the author approves every post.
- **Inline scripts are allowed** by the client's Content Security Policy (`'unsafe-inline'`): Next.js needs them
  with Cache Components. The policy limits where a script could send data; it does not stop an injected one from
  running.
- **A signed-out or deleted user's access token stays valid until it expires** (Supabase's token lifetime), because
  the server checks tokens locally.
- **API keys do not expire** and give access to both MCP servers; they can be revoked at any time. The MCP
  servers are switched off on the public server (`MCP_SERVERS`), so a key opens nothing there.
- **Rate limits are kept in memory**: they reset when the server restarts and would not be shared between several
  server instances. Budgets are not affected (they are sums over the saved usage log).
- **Books on the server's disk** (the option for files over 50 MB) are not backed up by Supabase.
- **No second factor** at sign-in (email and password only).

## Checking it yourself

```sh
cd server
uv run pytest -q                                   # incl. the route, ownership, guest, guard and header tests
uv run python ../eval/run_guard_eval.py --no-save  # the guard against the red-team set
cd ../client
npm audit                                          # the server's packages: pip-audit in CI (.github/workflows/ci.yml)
```
