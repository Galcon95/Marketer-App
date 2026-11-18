# Page Inbox Agent (human in the loop)

The Page inbox agent answers readers on the author's own Facebook Page and viewers under the videos of their own
YouTube channel, and the author approves each reply in Telegram. It watches the Page and the channel, drafts a reply
from the author's books, and sends the proposal to the author's Telegram chat. Then it waits. Nothing is posted until
the author answers **"make it so"**.

```
Facebook Page   ──► new comment / visitor post? ─┐
YouTube channel ──► new comment under a video?  ─┴► draft a reply from the books ──► Telegram: proposal
                                                                                        │
        Page / channel: reply posted ◄── "make it so" ◄────────────────────────────── author
                                              "skip"            → nothing is posted
                                              any other text    → feedback: the agent rewrites, asks again
```

Code: [`page_inbox.py`](../server/app/agents/page_inbox.py) (the graph),
[`page_inbox_worker.py`](../server/app/agents/page_inbox_worker.py) (Telegram loop and schedule),
[`telegram.py`](../server/app/social/telegram.py) (Bot API client),
[`facebook.py`](../server/app/social/facebook.py) (`open_items`, `reply_to_comment`, `comment_on_post`),
[`youtube.py`](../server/app/social/youtube.py) (`open_items`, `reply_to_comment`).
The drafting is done by the [Discussion Relevance Agent](AGENT.md) in its own Page or own channel mode.

---

## 1. Setup

1. **Facebook Page** (optional): `FACEBOOK_PAGE_ID` and `FACEBOOK_PAGE_TOKEN` in `server/.env` (see `.env.example`).
   **YouTube channel** (optional): connect it in the app under **Integrations → YouTube channel**, signed in as the
   owner of the books below. There is no `.env` setting for it; the inbox uses that owner's connected channel. With
   neither, the inbox has nothing to read.
2. **Telegram bot:** in Telegram open **@BotFather**. Use the verified account (blue checkmark) whose username is
   exactly `BotFather`; look-alikes exist. Send `/newbot` and choose a name and a username ending in `bot`. Put the
   token in `server/.env` as `TELEGRAM_BOT_TOKEN`. Then open your bot, press **Start** and send it a message.
   `https://api.telegram.org/bot<token>/getUpdates` shows your chat id (`message.chat.id`). Put it in
   `TELEGRAM_CHAT_ID`.
3. **Books:** `FACEBOOK_INBOX_BOOKS=src_...,src_...` lists the processed books of one client to answer from (for
   Facebook and YouTube alike).
4. **Schedule:** in the app, **Phase 4 · Agent Workspace** (signed in as the owner of the inbox books): *Manual only*
   (only `/next` or **Run now**), or *On a schedule*: at times of day (e.g. 09:00 and 18:00) or every few hours, on
   chosen days, in your time zone. Saved per user in `private.automation_settings`
   ([`automation.py`](../server/app/agents/automation.py)). A run missed while the server was off is made up once when
   it starts. Until you save one, `FACEBOOK_INBOX_INTERVAL` (minutes, default 30; `0` = manual) is the default. One
   look at the channel costs 1-3 of the 10,000 daily YouTube API units, a reply 50.
5. Start the server. The log shows `Page inbox worker started`; if something is missing, it shows which setting.

## 2. Using it

| In Telegram | What happens |
|---|---|
| `/next` | Runs a **cycle** now: the agent looks at the Page and the channel and proposes the oldest open item (or says "Nothing new"). |
| **✅ Make it so** button, or the text `make it so` | The reply is posted as the Page or the channel; you get the link. The next open item follows. |
| **Skip** button, or `skip` | Nothing is posted; the item is not proposed again. |
| Any other text, e.g. "shorter, mention volume 2" | Feedback: the reply is rewritten from the same book passages and proposed again (up to 5 rounds, then finish it in the app). |
| `/status` | The schedule, the next and the last run, the running cycle, and whether a proposal is waiting. |
| `/pause`, `/resume` | Stop the schedule for now, and start it again (the schedule is kept; after `/resume` the next run counts from then). `/next` works while paused. |
| `/help` | All commands with what they do, and how to answer a proposal. The same commands appear in Telegram's menu when you type `/` (set when the server starts). |

**Cycles** ([`cycle.py`](../server/app/agents/cycle.py)): each start (the schedule, **Run now**, `/next`) is a cycle.
It proposes the open items one at a time, the next one right after your answer, and ends with a summary in Telegram
("Cycle done: 2 posted, 1 skipped."). While a proposal waits, a new start only checks it. Cycles are logged in
`private.automation_cycles` and listed under **Recent cycles** in the Agent Workspace (scheduled looks that found
nothing are not logged). A cycle still running when the server stops is shown as *interrupted*. A comment under a
recent post and a book post will join the cycle as its phases 2 and 3.

**Run now** in the Agent Workspace works like `/next` (it starts within half a minute). A proposal waits until you
answer it; there is no expiry. The schedule only messages you when something new is there. Each proposal is also saved as a discussion analysis,
so it can be read and edited in the app (Community). A YouTube proposal starts with ▶️ and names the video.

**What counts as open:** a visitor's comment the Page has not answered in its thread, and a visitor's post on the
Page that the Page has not commented on. Facebook keeps replies one level deep. So a visitor's follow-up written after
the Page's reply counts as open again, and the answer goes into the same thread. On YouTube the same holds for a
viewer's comment the channel has not answered in its thread; YouTube keeps every reply under the thread's top comment.
Facebook and YouTube items are proposed together, oldest first. When one of them cannot be read (e.g. the YouTube
sign-in expired), you are told once and the other is still proposed.

## 3. How it works

### The graph (LangGraph `StateGraph` with a checkpointer)

```
START ─► choose_book ─► analyze ─► propose ─► wait ⏸ ─(make it so)─► publish ─► END
                                      ▲         │
                                      │         ├─(skip)───────────► skip ────► END
                                      └─ revise ◄┘(feedback)
```

| Node | What it does |
|---|---|
| `choose_book` | One vector search per configured book for the reader's text; the book with the best match wins. No model call. |
| `analyze` | The Discussion Relevance Agent in own Page mode researches the book and drafts a reply as the author. The result is saved. An earlier analysis that was not posted is reused, so a restart costs no second run. |
| `propose` | Sends the comment, the volume, the agent's verdict and the reply to Telegram, with the buttons. Removes the buttons of the previous proposal. |
| `wait` | `interrupt()`: the run stops and the checkpointer keeps its state until the author answers. `resume()` continues it with `Command(resume=...)`. |
| `revise` | One structured model call ([`page_inbox_revise.md`](../server/prompts/page_inbox_revise.md)) rewrites the reply to follow the feedback, citing the same passages. Saved as the author's edit. |
| `publish` | Runs the output guard again, then posts as the Page: into the comment's thread, or under the visitor post. Stores `replied_id/url/at`. |
| `skip` | Posts nothing. |

### The worker

A background thread, started by `server.py` on startup when everything is configured. It long-polls Telegram (25 s),
hands each update to the graph and, every interval, proposes the next open item if none is waiting. Only one
proposal waits at a time; after a final decision, the next one is proposed right away.

## 4. Safety: why the human stays in control

- **Nothing is posted without "make it so".** Every write to Facebook or YouTube happens in `publish`, which only
  runs after the author's decision.
- **A decision is applied exactly once.** `resume()` runs under a lock and accepts an answer only to the run's
  current proposal while the run waits. A second press, an answer to an older proposal, or a press after a restart
  is refused with "already decided". An analysis that has a `replied_id` is never posted again.
- **Only the author's chat counts.** Telegram updates from any other chat or sender are dropped and logged without
  their content. The bot token never appears in logs or error messages.
- **Readers' text is data.** Comments reach the models only as quoted `<post>` blocks under the untrusted-text
  rule, with the Discussion agent's injection scan. A reply that looks like it contains instructions to an AI gets no
  **Make it so** button and is refused in `publish` even if the author types it. Telegram messages are sent as plain
  text, so quoted text cannot become formatting or links.

## 5. Technical decisions

| Decision | Why |
|---|---|
| LangGraph `interrupt()` + checkpointer | The standard LangGraph way to pause a graph for a human and continue it later in the same state. |
| `MemorySaver` (in memory) | No new dependency. The cost: a restart loses the waiting proposal, and the item is simply proposed again. `langgraph-checkpoint-postgres` would keep it across restarts. |
| Telegram long polling, plain `httpx` | Works on a local machine without a public URL (webhooks need one). Same style as the Facebook client; no new library. |
| Reuse the Discussion agent | The research, grounding, humanizer and guards are already tested and evaluated; the inbox only adds the loop around them. |
| Book chosen by vector search | Cheap (no model call), and good enough to pick between two volumes. The agent still researches only the chosen book. |
| Visitor posts from the feed | The `visitor_posts` edge needs permissions the Page token does not have; the feed's `from` field tells visitor posts apart. |

## 6. Limitations

- **One server process.** Telegram allows one long poll per bot. A second process gets "Conflict" and its worker
  keeps retrying.
- **Restarts forget.** Waiting proposals and skipped items are kept in memory, so after a restart they are proposed
  again.
- **One book per reply.** The best-matching volume is used, not both together.
- **The worker blocks while drafting.** A draft takes 30–60 s; button presses in that time are handled afterwards.
- **Comments on the latest 10 posts and the latest 50 YouTube comment threads only.**
- **YouTube sign-in in "Testing".** While the Google app is in testing, the YouTube connection ends after 7 days; the
  inbox then says so in Telegram, and you connect the channel again in the app.

## 7. Tests

`tests/test_telegram.py` (35), `tests/test_page_inbox.py` (35, the real graph with fakes around it, YouTube items
included), `tests/test_page_inbox_worker.py` (38) and the inbox cases in `tests/test_facebook.py` and
`tests/test_youtube.py`. Telegram, Facebook, YouTube and the model are faked; `conftest.py` blanks the Telegram settings, so no test reaches the real bot.
