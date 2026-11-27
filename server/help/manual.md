<!--
The user manual of the Marketer App: shown on the Help page (/help, from GET /help/manual) and read by "Ask the app".
Write for authors, not developers: what to click, what happens, what to watch out for. Keep the headings stable:
links point to their anchors (/help#connect-your-youtube-channel). Update it whenever a screen changes (AGENTS.md).
-->

# Marketer App manual

The Marketer App helps you market your book. You upload the book once; the app then answers questions about it,
writes posts, ads and newsletters from it with sources, finds online discussions where your book can really help,
and drafts replies to your readers on your Facebook Page and YouTube channel. **Nothing is ever posted without your
approval.**

> Texts and pictures are written by AI. They can be wrong, even when they cite the book: read them before you use
> them.

## Getting started

### Sign in or create an account

1. Open the app. You see **Sign in to Marketer App**.
2. New here? Click **New here? Create an account**, enter your email and a password (at least 8 characters) and click
   **Create account**.
3. Open the link in the email the app sends you to confirm your account, then sign in with **Sign in**.

### Try the app as a guest

Click **Try as guest** on the sign-in page: no account needed. You get a demo with two classic books and can ask them
questions, write posts and ads and make pictures. See [The guest demo](#the-guest-demo) for what the guest can and
cannot do.

### Find your way around

- **The four tabs** at the top follow the order of the work: **Knowledge Hub** (your books), **Content Studio** (write
  from your books), **Community** (discussions and comments), **Agent Workspace** (the marketing agent).
- **The sidebar** has the same four entries under *Pipeline*, and under *Integrations*: **Facebook Page**, **YouTube
  channel** and **MCP servers**. The *Library* entries (Asset Library, Audiences, Settings) are not available yet.
- **System status** at the bottom of the sidebar shows whether the app's parts work: API, Vector DB (the book
  search), LLM (the language model) and Pictures. "Offline" means that part cannot be reached right now.
- **The top bar** has the usage button (costs so far, e.g. "$0.0153 · 12.3k tok"), **Keys**, **Export**, **Ask the
  app**, **Help** and **Log out**.
- **Light mode / Dark mode**: the round button in the corner switches the theme; the app remembers it.
- On a phone the sidebar is hidden: open it with the menu button in the top bar.

> Switching tabs clears what you typed but did not send on the tab you leave.

### Ask the app

Click **Ask the app** in the top bar and ask how to do something, e.g. "How do I make an ad picture?", in any
language. The answer comes from this manual, with links to the sections it used under **Read more**. It knows which
screen you have open, so "What is this page for?" works too. It only explains: it cannot change anything in the app.
The chat stays while you work and is not saved; **New chat** clears it. Each question is a small AI request and counts
in your usage. If an answer does not match what you see, this manual is right.

## Your books (Knowledge Hub)

### Upload a book

1. Open **Knowledge Hub** and click **Choose PDF** in **Upload a book**.
2. Pick the book as a **PDF** (other formats are not accepted yet). Up to 50 MB is stored in the cloud.
3. The app uploads it ("Uploading N%") and then processes it by itself: it reads the text, splits it into short
   passages and makes them searchable. You see the steps and their progress. When it shows **ready** and "N chunks",
   the book can be used.

- A file between 50 MB and 500 MB is too large for the cloud storage: the app asks whether to **Store on server**
  instead. Such a book is only available while the server keeps its files, and it is not backed up.
- Over 500 MB is refused. Large PDFs are mostly pictures (scans, illustrations), and the app only reads the text:
  make the PDF smaller with a PDF tool ("Reduce file size"), or split it and upload each part as its own book.
- A scanned book without a text layer cannot be read: use a PDF with real text.

### Your books and the Sources table

Each book in **Your books** shows its cover, title, size, the number of passages ("chunks") and, if it has one, the
start of its summary and its key themes.

- **Click the cover** to open the PDF in a new tab.
- **Summary** opens the summary; **Create summary** makes one (see [Summarize a book](#summarize-a-book)).
- **Chunks** shows the passages the app made from the book; click a passage's location to open the PDF at that page.
- **Change cover**: upload your own cover as PNG or JPEG, up to 10 MB. It is used in the app and in every new ad
  picture.
- **Work on this book** limits asking and writing to this book (see [Work on one book or all books](#work-on-one-book-or-all-books)).

The **Sources** table lists every file with its status. **Process** prepares a file that was not processed yet,
**Retry** runs a failed processing again and **Re-index** processes a ready book again from its PDF.

### Summarize a book

A summary reads the whole book: every chapter is summarized, then everything is combined into an overview with key
themes. It takes about 10 to 40 seconds.

1. Click **Create summary** on the book (or **Summary**, then **Create summary**).
2. The summary shows **What the book is about**, **Key themes** and **Chapters** with their pages.

The summary is worth making: the campaign kit uses it to fill in the brief, and the marketing agent takes the topics of
its book posts from the chapters. **Regenerate** makes a new summary and replaces the old one (this costs tokens again).

### Work on one book or all books

The **Working on** bar (in the Knowledge Hub, the Content Studio and Community) chooses the book you work on: **All
books** or one book. The choice stays when you change tabs. With one book chosen, **Ask your book** and the writing
tools use only that book. The discussion agent and the Reddit and Substack scans always need one book.

### Delete a book

Click the trash icon on the book or in the Sources table. Deleting removes the book with its passages and summary,
the texts and chats made only from it, and its discussion analyses. Texts and chats that also used other books are
kept. **This cannot be undone.**

## Ask your book

**Ask your book** (in the Knowledge Hub) is a chat with your books.

1. Type a question, e.g. "How will Garden City be financed?", and click **Ask**.
2. The answer is written only from the most relevant passages, with numbered citations [1], [2]. If the books do not
   cover the question, it says so.
3. Ask follow-up questions ("And who collects that money?"): the chat remembers the conversation.

Under each answer you see:

- **Cited sources**: the passages the answer used, with their location (click to open the PDF at that page).
- **All retrieved passages**: everything that was read for the answer.
- **Searched for**: how a follow-up was turned into a full question; **Filtered to**: the book, chapter or pages
  your question named.
- Cards for the **tools** the assistant used: it can list your books, check whether a post fits a platform ("Does this
  fit on X? …") and draft a post ("Write a LinkedIn post about …"; the draft is saved with your texts).

**New chat** starts a fresh conversation; the old one stays under **Past chats**, where you can open it again or
delete it (the trash icon deletes it at once).

## Write from your book (Content Studio)

### Write a single text

Open **Content Studio** → **Single asset** ("From your books").

1. Choose the **Asset type**:
   - *Sell*: **Blurb / product description**, **Ad copy**.
   - *Social media*: **Social post**, **Reply to a post**, **Question for my readers**, **Short video script**
     (Reels, TikTok, Shorts), **YouTube video page** (titles, description, tags).
   - *Email*: **Newsletter**, **Lead magnet**.
   - *Plan*: **Audience persona**.
   - Types marked "coming soon" (carousels, GIFs, short videos) cannot be chosen yet. The ⓘ button explains what each
     type is for.
2. Choose the **Platform** (for posts, replies, reader questions and video scripts) or the **Length** (Short,
   Standard, Long).
3. Choose the **Tone** (Neutral, Inspiring, Friendly, Professional, Punchy, Literary) and, if you like, a **Target
   audience**.
4. Set **How human?** (see [How human should it sound](#how-human-should-it-sound)).
5. Write the **Brief**: what the text should be about. For **Reply to a post**, paste **Their post** and, if you like,
   **Your angle**.
6. Click **Generate from sources** (or press Ctrl+Enter).

The text appears in **Grounded assets**, with citations to the book. The list shows only the chosen type and book;
**Show all types** shows everything.

### Check, edit and copy a text

Each text card shows its type, platform and tone, the word and character count (red when it is too long for the
platform), the citations, the tokens and the cost.

- **Copy for posting** copies the text without the [1] markers.
- **Edit** changes the text; **Save** marks it "edited".
- **Verify** checks each sentence against the book and shows which passage supports it, or "not found in sources".
- The trash icon deletes the text.
- A "human N" badge in a warning colour means some typical AI wording is left: edit it, or generate again with a
  higher "How human?".

### Publish a post on your Facebook Page

Facebook posts and reader questions written for Facebook can be published straight from their card, once your Page
is connected ([Connect your Facebook Page](#connect-your-facebook-page)).

1. Check the text (save or cancel an edit first).
2. Click **Publish to my Facebook Page** and confirm. The post is public at once.
3. The card then shows "Published on your Facebook Page" with a link. Each text can be published once.

### Make an ad picture

On an **Ad copy** card, **Ad pictures** makes a picture with your book's cover in a scene.

1. Click **Create image**.
2. Check the **Headline in the picture** (up to 80 characters; the ad's headlines are offered to pick), or tick **No
   text in the picture**.
3. If you like, describe the **Scene**, e.g. "on a café table, morning light".
4. Choose the **Format**: Square 1:1 (feed), Portrait 4:5 (feed on phones), Story 9:16 (stories and reels) or Wide
   16:9 (link ads).
5. Click **Create image**. It takes about 15 seconds and costs about $0.07, counted in your usage.

Click a picture to see it full size; download it with the download icon; post it on your Page with the send icon
(you write the caption first; each picture can be posted once).

### Make a campaign kit

**Content Studio** → **Campaign kit** writes a whole campaign in one go: 3 reader personas, 5 social posts and a
blurb. It is "zero-shot": the model sees only your brief, not the book's text.

1. Choose the **Book** (or **New book (not in the library)** and type its title).
2. Check **Author / pen name**, **Genre**, the **Themes to build on** and the **Hook / premise**. With a book summary,
   hook and themes are filled in for you.
3. If you like, add **For fans of** (similar authors) and choose an **Audience focus**.
4. Set **How human should it sound?** and click **Generate campaign (zero-shot)**. It takes about 20 to 40 seconds.

The campaign appears under **Campaigns** with its personas, posts and blurb, each with the usual card buttons.
**Delete** removes the whole campaign.

### Export your texts

**Export** in the top bar downloads your texts, newest first. Choose the book, the type and the format:

- **CSV**: one row per text, ready to post (without [1] markers), for Google Sheets, Excel or scheduling tools.
- **CSV for Excel**: the same with semicolons, for Excel with German settings.
- **Markdown**: easy to read and edit, with the sources under each text.

## Discussions and comments (Community)

### Find discussions on Reddit or Substack

1. Open **Community**, choose your book under **Working on**, and click **Scan Reddit** or **Scan Substack**.
2. Enter a **Topic**, e.g. "AI future, civilizations".
3. If you like, name up to 5 **Subreddits** or **Publications** (empty = search everywhere), choose the **Time**
   (past week, month or year) and how many results per search.
4. Click **Scan Reddit** / **Scan Substack**. It takes 5 to 20 seconds.

The results are ranked by how well your book could add to them: **High fit**, **Medium fit**, **Low fit** (low ones
are hidden at first). Each shows why it fits. **Analyse with agent** loads the discussion for the agent; **Open on
Reddit** opens it. "Snippet only" means the search had only a short excerpt: open the thread and paste the text.
Comments under Substack posts are not found, and nothing is saved by a scan.

**My Substack** (in Scan Substack): save your Substack address to see your latest posts there and to leave them out
of the scan.

### Let the agent analyse a discussion

1. Choose your book under **Working on** and click **Paste** (or come from a scan or a comment).
2. Paste **The discussion**: the post and the replies that matter (up to 8,000 characters).
3. If you like, add the **Link**, choose the **Platform**, write **Your angle**, choose the **Tone** and set **How
   human?**.
4. Click **Analyse discussion**. The agent searches the book several times; it takes up to a minute.

The agent decides one of three things:

- **Contribute**: the book can really help; it drafts a reply with sources.
- **Needs more context**: it says **What to add**; paste the discussion again with that and analyse once more.
- **Skip**: the book has nothing worth adding here. Replying anyway would look like an ad.

It also says whether to **Mention the book** or **Don't name the book**, and why. **How the agent worked** shows every
search and tool call it made.

### Use the suggested reply

- **Copy for posting** copies the reply without the [1] markers; you post it yourself on Reddit, LinkedIn and so on.
- **Edit** changes it; **Use the suggestion again** brings the agent's version back.
- **Copy source** copies a short note naming the book and the parts the reply drew on, for when someone asks.
- **Open discussion** opens the original.
- **Delete** removes the analysis.

> A red notice "possible prompt injection" means the discussion contains text that tries to give the AI
> instructions. The agent only read it as quoted text and did not follow it, but check the reply carefully. "Unusual
> text" is a weaker hint, e.g. hidden characters.

### Answer comments on your Facebook Page

Once your Page is connected, **Community** → **Facebook Page** lists the unanswered readers' comments on your latest
posts.

1. Pick a comment and click **Analyse with agent**. The agent answers it as you, the author, from your book.
2. Check and, if needed, edit the reply.
3. Click **Reply as Page** and confirm: the reply is posted under the comment, as your Page.

**Show answered comments** shows the others; **Refresh** reads the Page again. Here you can also **Write a new post**:
choose "Post about the book" or "Question for my readers", write what it should be about, click **Write from the
book**, check the draft and publish it from its card.

### Answer comments on your YouTube channel

Once your channel is connected, **Community** → **YouTube channel** lists the unanswered comments under your videos,
grouped by video. It works like the Facebook Page: **Analyse with agent**, check the reply, **Reply as channel**.

## Connect your accounts

### Connect your Facebook Page

1. You need a Facebook **Page** for your book (not your personal profile or a group), and full control of it.
2. While the app is in development on Facebook's side, only testers can connect: ask the app's owner to add you, and
   accept the invitation on developers.facebook.com/requests.
3. Open **Facebook Page** in the sidebar (under Integrations) and click **Connect with Facebook**.
4. Log in to Facebook, select your Page and keep all permissions switched on (list Pages, read posts and comments,
   publish posts, reply to comments). If one is off, reading or posting fails.
5. Back in the app, choose the Page if you manage several. It now shows as **connected**.

The access is stored encrypted on the server. **Disconnect** removes it; you can also remove the app in Facebook
under Settings → Business integrations. **How to connect your Page** shows these steps in the app.

### Connect your YouTube channel

1. Open **YouTube channel** in the sidebar (under Integrations) and click **Connect with Google**.
2. Pick the Google account that owns the channel (or its brand account) and allow the app to see and manage your
   YouTube comments.
3. Back in the app, the channel shows as **connected**, with its subscribers.

**Disconnect** removes the access. If the app finds no videos, check that you picked the account of the right
channel: a personal channel without videos is a common mix-up.

## The marketing agent (Agent Workspace)

The marketing agent works on its own: it looks at your Facebook Page and YouTube channel, drafts replies to new
comments from your books, and sends each proposal to you in **Telegram**. **Nothing is posted until you answer "Make
it so".** On this server the agent works for one account, the app's owner; other accounts see "not available".

### What the agent does in a cycle

One run of the agent is a cycle:

1. **Replies**: it proposes a reply to each new reader's comment on your Page and channel, one after the other.
2. **When there were no new comments**: on Facebook it can propose a question under a recent post without comments;
   on YouTube a comment under one of your videos about one of its topics and what your book says about it (or a
   question, or nothing, as you set).
3. **A new book post**: at the end it can propose a new Facebook post about the next topic of your book, with a call
   to action and your book's link, optionally with a picture.

Each proposal waits until you answer it; the next follows your answer, and the cycle ends with a summary in Telegram
("Cycle done: 2 posted, 1 skipped.").

### Set up the agent's schedule

In **Agent Workspace** → **Marketing agent schedule**:

1. Tick the **Books the agent uses** and, for each, **Where to get it** (e.g. its Amazon page). That link is the only
   link the agent's texts may contain; any other link the AI writes is removed.
2. Choose the **Mode**: **On a schedule** or **Manual only** (then it runs only when you ask).
3. For a schedule, choose **At times of day** (up to 6 times) or **Every few hours**, the **Days**, the **Time zone**
   and, if you like, **Quiet hours** (no runs at night; a run due then waits).
4. Under **When there are no new comments**, choose the Facebook question and what to write under YouTube videos.
5. Under **At the end of each cycle**, switch the book post on or off, and its picture (about $0.07 each).
6. Set **How human should the agent sound?** and the **daily limits** for Facebook and YouTube (replies to readers
   are not limited).
7. Click **Save schedule**.

> **Try the agent without publishing anything: switch on Test mode.** Everything is proposed in Telegram as usual,
> but nothing is published, not even after "Make it so". "Manual only" is different: the agent then runs only when
> you ask, but what you approve is published.

**Run now** starts a cycle at once; **Pause schedule** / **Resume schedule** stops and restarts the schedule.
**Recent cycles** lists the last cycles with what was proposed and what happened to each proposal.

### Answer the agent in Telegram

Each proposal starts with 🟦 FACEBOOK PAGE or 🟥 YOUTUBE CHANNEL and shows the comment or post, the book it used and
the proposed text. Answer with:

- **✅ Make it so** (or write "make it so"): post it.
- **✏️ Edit** (or write "edit"): tap the text the bot sends to copy it, change it, and send it back; exactly that text
  is proposed again.
- **Skip** (or write "skip"): post nothing.
- **Anything else**, e.g. "shorter, mention volume 2": the agent rewrites it and asks again.
- For a book post with a picture: **🔄 New picture** (up to 3) or **🚫 Without picture**.

Only the newest proposal counts; answering an older one gets "That proposal is no longer current".

Commands: **/next** runs a cycle now, **/post_facebook** proposes a new book post now, **/post_youtube** a comment
under a video now (both also beyond the daily limit), **/status** shows the schedule and the running cycle,
**/pause** and **/resume** stop and restart the schedule, **/help** lists everything.

## Usage, limits and costs

Every AI request costs a little. The usage button in the top bar shows your costs and tokens so far; click it for
**LLM usage & costs**:

- **Your budget**: what you spent today and this month, against your limits. The day renews at midnight UTC, the
  month on the 1st. When a budget is used up, AI features pause until it renews.
- The costs **by operation** and your **latest calls**, and an **Excel** download of all calls.

A picture costs about $0.07. Each text card, campaign and chat shows what it cost, so you can see the price of every
feature in your own use.

## How human should it sound

The **How human?** slider (0 to 100) sets how the AI writes: low values sound like polished marketing, high values
like a person writing casually. From 60 on, posts and replies are checked for typical AI wording and rewritten when
it is found. A "human N" badge on a text shows the setting it was written with.

## MCP servers and API keys

The app's books and tools can also be used from AI assistants such as Claude Desktop, through two MCP servers
(marketer-books and marketer-guardrails). This is for advanced users.

1. Click **Keys** in the top bar, name the key (e.g. "Claude Desktop") and click **Create key**.
2. Copy the key at once: it is shown only once. **Copy Claude Desktop config** gives the ready settings for Claude
   Desktop (restart it afterwards); for the MCP Inspector, copy the URL and the header value.
3. **Revoke** stops a key at once.

The **MCP servers** page in the sidebar shows the servers and lets you try their tools in the **Tool console**.

## The guest demo

**Try as guest** opens a shared demo account with two classic books. As a guest you can ask the books questions,
write texts, campaign kits and pictures, and analyse discussions.

- You cannot upload, delete or re-process books, change covers or make summaries, connect Facebook or YouTube, use
  the marketing agent, or create API keys. Create your own account for those.
- Everything visitors make is deleted when nobody has used the demo for 15 minutes, and a guest session ends after
  an hour: then press **Try as guest** again.
- The guest has its own small budget, and each visitor can start the demo a few times a day.
- Please do not enter personal data in the demo.

## Privacy and safety

- **Nothing is posted without you**: every post and reply needs your click in the app or your "Make it so" in
  Telegram.
- **Your connections are encrypted**: the access to your Facebook Page and YouTube channel is stored encrypted, and
  you can disconnect at any time.
- **Other people's text is never obeyed**: comments, discussions and book passages are only read as material.
  Suspicious text is marked, and texts that look like instructions to an AI are not posted.
- **Only your own links**: links the AI writes that are not your book links are removed from its texts.
- The full privacy notice is under **Privacy** at the bottom of every page.

## Troubleshooting

- **"Backend unreachable" or System status "Offline"**: the server cannot be reached. Wait a minute and reload; the
  free server can take up to a minute to wake up.
- **"Your session has expired" / you are back at sign-in**: sign in again. Guest sessions end after an hour.
- **A book stays "failed"**: click **Retry**. Scanned PDFs without text cannot be read.
- **"Budget used up"**: your daily or monthly AI budget is spent; it renews at midnight UTC or on the 1st.
- **"Choose a book under Working on first"**: the discussion agent and the scans need one book chosen.
- **Facebook: reading or posting fails**: connect again and keep all permissions switched on.
- **YouTube finds no videos**: you probably connected another channel of your Google account; connect again and pick
  the one with your videos.
- **Telegram does not answer**: check the schedule is not paused (/status) and that only one server runs the bot.
