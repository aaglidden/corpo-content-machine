# content-machine

A pipeline for a company's LinkedIn page, from idea to Buffer draft. It watches trade news, picks a weekly shortlist with Claude, interviews your team for its take, and drafts the post in the company's voice. Nothing publishes on its own: every post waits in Buffer as a draft.

It's built for one company and one LinkedIn page. Your team works in a single Slack channel.

Everything runs in the cloud: GitHub Actions does the work, and a Cloudflare Worker starts it. Nothing depends on anyone's computer being on. The news gathering and weekly shortlist also have a GitLab CI version (see below).

Released under the MIT license. The example content is generic: fill in `voice/`, `feeds.yaml` and `slots.yaml` to make it yours.

## The shape

```
capture                 pool                       weekly review          Buffer
───────                 ────                       ─────────────          ──────
Slack "idea: ..."  ───► ideas/  (team ideas)   ─┐
                                                ├─► Sunday shortlist ─► interview ─► draft
trade news (daily) ───► news.json (the news)   ─┘   in Slack             (optional)
```

| When | Workflow | What it does |
|---|---|---|
| Daily | `gather` | Adds new trade news to `news.json` |
| Sundays | `shortlist` | Claude picks 6 to 8 candidates from the week's news and open team ideas, and posts one Slack message per pick |
| Whenever someone writes in the channel or presses a button | `slack` | Saves an idea, runs an interview, or drafts a pick to Buffer |

The company posts once each weekday, so the shortlist is sorted into the week's slots.

## The weekly slots

[`slots.yaml`](slots.yaml) defines the week: Mon news take, Tue stat of the week, Wed opinion, Fri story. Each slot says what it `wants` (what the shortlist looks for) and its `brief` (what the drafter writes to). Edit the file to change the week; add a day, or delete one if the page posts less often.

- **Sunday's shortlist** sorts picks into the slots, about two candidates each, best first. A slot with nothing strong stays empty and the intro message says so.
- **The team still chooses.** Each pick shows its slot. Pressing **Draft this** or finishing an interview writes the post to that slot's brief and sends it to Buffer as a draft.
- **Tuesday makes a graphic.** See below. The graphic is made from the templates in [`templates/stat-of-the-week/`](templates/stat-of-the-week/) (single stat, bar chart, or pie chart).
- **Posting times** stay in Buffer. Drafts don't pick a time.

### Tuesday's stat graphic

`graphic.py` makes it when you draft a pick in the stat slot:

1. Claude reads the sources and chooses the one number and a template from [`templates/stat-of-the-week/`](templates/stat-of-the-week/README.md): a single number, a bar chart or a pie.
2. **The number is checked against the source text.** The quoted sentence has to appear in the sources word for word, and every figure has to be in it. If a check fails, there's no graphic and the draft goes ahead as text with the reason in the reply.
3. HyperFrames renders a 1080×1080 8-second MP4. The `slack` workflow sets up Node for it, and caches Chrome.
4. The caption is written knowing what the graphic says. The graphic replaces the link card, since a post carries one attachment, and the caption names the source.
5. The video is uploaded to a public Cloudflare R2 bucket (`media_host.py`) and attached to the Buffer draft by URL, since Buffer takes media from a URL. It's also uploaded to the Slack channel with the source link, so the team can see it.

If hosting isn't set up or fails, the draft goes to Buffer as text and the Slack copy is the one to attach by hand.

**R2 setup, once:**

1. In the Cloudflare dashboard, R2 → create a bucket (for example `content-machine-graphics`).
2. In the bucket's Settings, turn on the public `r2.dev` URL. That address is `R2_PUBLIC_URL`.
3. R2 → Manage API tokens → create a token with Object Read & Write on that bucket. It gives an access key ID and a secret.
4. Add five repo secrets in GitHub: `R2_ACCOUNT_ID` (shown on the R2 page), `R2_ACCESS_KEY_ID`, `R2_SECRET_ACCESS_KEY`, `R2_BUCKET` and `R2_PUBLIC_URL`.

Everything in the bucket is public, so only graphics go there.

## Capturing an idea

**Every idea comes in as a message in the Slack channel.** The bot saves it as a note in `ideas/`. Either of these works:

- **Typed.** Starting with "idea:" always saves it as an idea. Anything else, Claude decides whether it's an idea, an interview answer or something about the shortlist.
- **A shared link.** Paste an article and add a line with the team's take. The link is saved with the idea, and drafting reads the page and uses it for the preview card.

The bot reacts with 👀 straight away and confirms every save with "💡 Saved to the team's ideas" and the words, so a misread is easy to spot.

Notes in `ideas/` have a `status`: `new`, `shortlisted`, `drafted`, `skipped` or `archived`. New and shortlisted ideas go into every Sunday shortlist until they're drafted or skipped. Set `archived` by hand to retire one. A note written straight into `ideas/` without a status is ignored, so new ideas still go through the bot. An idea's interview is written into its note under `## Interview`.

## The weekly review

`shortlist.py` sends Claude the last seven days of `news.json` and every open idea, along with `voice/identity.md` (what the page covers) and `voice/selection.md` (what's worth a take, plus a calibration table of past verdicts). An idea counts as the company's take already, so it usually beats a news item of similar strength, and it can be paired with a news story that backs it up. The result is `shortlists/<date>.md` as a record and `shortlists/<date>.json` for drafting.

Each pick arrives in Slack with two buttons. News picks lead with **Draft this**; team ideas lead with **Interview us**, since they're often one raw line. Anyone in the channel can also reply in a pick's thread in their own words: "draft this but angle it toward agencies", "interview us on this", "skip, layoffs", or ask a question.

## The interview

`interview.py`. Pressing **Interview us** starts it: the bot asks one question at a time in Slack, adapting each to the last answer, and stops after three or sooner once it has the company's take and something concrete behind it. Then it drafts, with the answers as the heart of the post.

- Reply in the question's thread, and take as long as you like. Otherwise Claude matches a message to the open interview.
- "Draft it" ends early and drafts with what's there. "Drop it" skips the pick and records a skip verdict.
- The state lives on the pick in `shortlists/<date>.json`.

## Drafting

`draft.py` has Claude write the post from, in order of weight: the interview answers, the team's notes, the idea, the angle, and the articles (read in full where the site allows). It goes to Buffer as a draft with a preview card. Nothing publishes from here; Buffer drafts wait for someone to schedule them.

The pick's buttons change to **Drafted to Buffer**, the shortlist records the Buffer ID so it can't be drafted twice, and an idea's note flips to `drafted`.

## Feedback

Verdicts go into `verdicts.json`, and each Sunday's shortlist reads the recent ones as examples of the team's taste:

- **What the team says** in Slack: "skip, layoffs" (skip), "angle's off, it's really about agencies" (right story, wrong angle), "this was the best one" (good pick). The bot confirms with "Noted."
- **Drafting a pick** counts as a good pick; **dropping one mid-interview** counts as a skip.
- **Picks nobody drafted or commented on** count as a weak no. That's worked out at shortlist time, not stored.

The rules stay in `voice/selection.md`. Every so often, patterns in `verdicts.json` are worth turning into a rule there.

The `voice/` files are yours to edit. The shipped ones are placeholders: fill in `identity.md`, `selection.md`, `voice.md` and `channels/linkedin.md`, and add a few of the company's own posts to `voice/examples/linkedin/`. Or send `onboard` to the bot to draft `voice.md` from an interview; the drafts land in `voice-drafts/` for review.

## The news

`gather.py` reads every source in [`feeds.yaml`](feeds.yaml) and adds anything new to `news.json`.

- **Feeds** (RSS/Atom): items published in the last 14 days go in. Feeds marked `filter: true` only let through items that mention a keyword from the list at the top of the file.
- **Sitemaps**, for sites with no feed: any URL we haven't recorded before counts as a new article. The first run only records what's already there.
- `seen.json` remembers everything already handled, so a second run adds nothing.

To change the sources, edit `feeds.yaml`. Each feed needs a `name`, a `category` and a `url`. Add `filter: true` to keep only items that match your keywords.

## Setting up Slack

1. Create a Slack app at api.slack.com/apps ("From scratch") in your workspace.
2. **OAuth & Permissions** → add these bot scopes: `chat:write`, `reactions:write`, `files:write`, `channels:history` (and `groups:history` if the channel is private). Install the app and copy the bot token (`xoxb-...`).
3. Create a channel for the page's content, invite the app to it (`/invite @your-app`), and copy the channel ID (channel details → bottom of the About tab).
4. Deploy the Worker (below), then in the app settings:
   - **Event Subscriptions** → on, Request URL = the Worker's URL, subscribe to the bot events `message.channels` (and `message.groups` for a private channel).
   - **Interactivity & Shortcuts** → on, Request URL = the same Worker URL.
5. Copy the **Signing Secret** from Basic Information.

## Setting up the Worker

```bash
cd worker
npx wrangler deploy
npx wrangler secret put SLACK_SIGNING_SECRET
npx wrangler secret put SLACK_BOT_TOKEN
npx wrangler secret put SLACK_CHANNEL_ID
npx wrangler secret put GITHUB_TOKEN
npx wrangler secret put GITHUB_REPO
```

`GITHUB_TOKEN` is a fine-grained token for your copy of this repo with Contents: read and write. `GITHUB_REPO` is `owner/name`. The Worker starts `gather` daily and `shortlist` on Sundays from the crons in `worker/wrangler.toml` (UTC).

## Run it

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
.venv/bin/python gather.py
NO_SLACK=1 ANTHROPIC_API_KEY=... .venv/bin/python shortlist.py
```

`DRY_RUN=1` prints drafts instead of sending them to Buffer.

The workflows need `ANTHROPIC_API_KEY`, `BUFFER_API_KEY`, `BUFFER_CHANNEL_ID` (the Buffer channel for the company's LinkedIn page), `SLACK_BOT_TOKEN` and `SLACK_CHANNEL_ID` repo secrets, plus the five `R2_*` secrets for graphics.

## Using GitLab

[`.gitlab-ci.yml`](.gitlab-ci.yml) runs `gather` and `shortlist` from GitLab pipeline schedules, as the GitHub workflows do; the setup is in the file's header.

The Slack side (the `slack` workflow, `handle.py` and the Cloudflare Worker) is GitHub-only for now: the Worker starts it with GitHub's `repository_dispatch`, and `handle.py` reads GitHub's event file. Porting it means pointing the Worker at GitLab's pipeline trigger API and passing the message to `handle.py` another way.

## Before you use it

- Fill in `voice/`, and edit `feeds.yaml` and `slots.yaml` for your own sources and week.
- Review every draft in Buffer before it's scheduled. The bot never posts.
- The fonts in `templates/` (Hedvig Letters Serif and Inter) are licensed under the SIL Open Font License; the colors are placeholders to replace with your brand.

## License

MIT, see [LICENSE](LICENSE).
