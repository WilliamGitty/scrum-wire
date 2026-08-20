# Scrum Wire — daily rugby transfer news

A self-updating website that pulls rugby RSS feeds every morning, keeps only
transfer / signing / rumour stories, trims the waffle, and shows them on a
clean, phone-friendly, dyslexia-friendly page. Runs entirely on free GitHub
features. No server, no ongoing cost, nothing to keep running on your own
machine.

Built from Gregg's handover brief (20 August 2026). Same architecture and
design as specified there — RSS in, filtered, no AI-generated content —
with two changes from the original doc, noted below.

## How it works

- `scripts/build.py` fetches the feeds, filters for transfer news, writes `index.html`.
- `.github/workflows/build.yml` runs that script automatically (GitHub Actions
  — this is the "cronjob") and deploys straight to GitHub Pages.
- Live at: **https://williamgitty.github.io/scrum-wire/**

## Changes from Gregg's original handover doc

1. **Cron redundancy.** The original had one daily trigger. GitHub's Actions
   scheduler has repeatedly, silently dropped single scheduled triggers on
   other briefings built this way — so this runs three staggered times daily
   (06:30, 07:00, 07:30 UTC) instead of one. Harmless if more than one fires;
   the page just rebuilds from the same live feeds again.
2. **Deploys via GitHub Actions' Pages action** (`actions/deploy-pages`)
   rather than "Deploy from a branch" + a `/docs` folder — functionally the
   same result, just the pattern used consistently across the other RSS
   briefings in this account. `index.html` lives at the repo root, not
   `docs/index.html`.

## Sources — verified live before adding

Every feed below was checked with a live `curl` request before being added
(several guessed URLs from official league/club sites 404'd or don't exist —
those sites don't publish their own RSS feeds).

| League | Source | Feed |
|---|---|---|
| Wales | BBC Sport – Welsh Rugby | direct feed |
| Wales | WalesOnline Rugby | direct feed |
| Premiership / General | BBC Sport – Rugby Union | direct feed |
| Premiership / General | RugbyPass | direct feed — **note:** Gregg's doc had `/feed/`, which 404s; the real path is `/feeds/rss/` |
| Premiership / General | The Guardian – Rugby Union | direct feed |
| Premiership / General | Sky Sports – Rugby Union | direct feed |
| URC | Google News search ("URC rugby transfer") | no dedicated URC transfer RSS exists — see note below |
| Top 14 | Google News search ("Top 14 rugby transfer") | same reason |
| South Africa | SA Rugby Mag | direct feed |
| South Africa | Google News search ("springbok rugby transfer") | supplements SA Rugby Mag |
| New Zealand | Google News search ("all blacks rugby transfer") | no dedicated NZ rugby transfer RSS found |
| Australia | SMH – Rugby Union | direct feed |
| Australia | Google News search ("wallabies rugby transfer") | supplements SMH |
| Japan | Google News search ("japan rugby league one transfer") | no dedicated Japan rugby RSS found |
| Champions Cup | Google News search ("champions cup rugby transfer") | EPCR's own site has no RSS |

**Why Google News search feeds for the harder leagues:** URC, Top 14, South
Africa, New Zealand, Australia, and Japan don't have their own reliable
transfer-news RSS feeds — checked directly against official league/club
sites and known rugby press sites, none publish one. `news.google.com/rss/search?q=...`
is a real, public RSS endpoint that aggregates genuine articles from
legitimate outlets (Planet Rugby, RugbyPass, FloRugby, local press, etc.) —
verified live to return real transfer headlines, not spam, before adding.
Links go through a Google News redirect to the original article, same as
clicking a Google News result normally would.

## Tweaks you might want later

**Change the update times** — edit the `cron:` lines in
`.github/workflows/build.yml` (UTC).

**Add or remove news sources** — edit the `FEEDS` list near the top of
`scripts/build.py`. Each entry is `(league label, source name, RSS url)`.
Always test a candidate feed live before adding it:

```bash
curl -s -A "Mozilla/5.0" --max-time 10 -L "<feed-url>" | grep -oE "<\?xml|<rss|<feed"
```

**Make the filter tighter or looser** — edit `TRANSFER_KEYWORDS` in
`scripts/build.py`.

**Add more leagues to the tags** — edit `LEAGUE_TAGS`.

**Rename the site / change colours** — the title and colour variables
(`:root {...}`) live in the `TEMPLATE` string near the bottom of `build.py`.

## Want real AI-written summaries later?

The current version shows each feed's own summary, trimmed. If you want each
story rewritten into a tight 2-line brief, `build.py` can call an AI API on
the schedule — that needs a paid API key added as a GitHub secret
(`ANTHROPIC_API_KEY`) and a small code change. Not required — everything
works without it, and it introduces a small ongoing cost plus a runtime
dependency on the API.

## If something looks wrong

- **Page is blank / "No transfer stories found"** — the feeds had no
  matching items in the last 10 days, or a feed URL changed. Run the
  workflow manually (Actions tab → Run workflow) and check the log.
- **Page not updating** — GitHub pauses scheduled workflows on repos with
  no activity for 60 days; any commit (including the workflow's own daily
  one) re-enables it, so this shouldn't happen in normal operation.
- **A feed errors in the log** — a publisher moved their RSS URL. Update it
  in the `FEEDS` list (test it live first, per the command above).
