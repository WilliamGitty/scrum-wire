# The Transfer Wire — daily rugby & football transfer news

A self-updating website that pulls rugby and football RSS feeds every
morning, keeps only transfer / signing / rumour stories, trims the waffle,
and shows them on a clean, phone-friendly, dyslexia-friendly page. A second
page shows today's fixtures, yesterday's results, and — for any league with
nothing on today — its next scheduled fixture, so quiet days and off-season
gaps (e.g. rugby in August) never just show a blank page. Runs entirely on
free GitHub features. No server, no ongoing cost, nothing to keep running on
your own machine.

Rebuilt from Gregg's updated handover brief (24 August 2026), evolving the
original rugby-only "Scrum Wire" into a combined two-sport site. Same
architecture and design as specified there — RSS in, filtered, no
AI-generated content — with the changes noted below.

## How it works

- `scripts/build.py` fetches the rugby + football feeds, filters for
  transfer news, tags each story by sport/league/country, writes `index.html`.
- `scripts/fixtures.py` fetches today's fixtures, yesterday's results, and
  a "Coming Up" section (each quiet league's next scheduled fixture),
  writes `fixtures.html`. Degrades gracefully (explains itself, doesn't
  break the build) if no data source is connected yet.
- `.github/workflows/build.yml` runs both scripts automatically (GitHub
  Actions — this is the "cronjob") and deploys straight to GitHub Pages.
- Live at: **https://williamgitty.github.io/transfer-wire/**

## What's new in this rebuild

- **Football added alongside rugby** — same filtering/tagging approach,
  separate feed list, one combined page with a sport filter.
- **Sport → league → country filtering**, a pinned search box, and per-story
  "NEW" badges (stored in each device's browser via `localStorage`, so
  what's "new" to you doesn't affect anyone else).
- **10-day auto-delete** — stories older than 10 days drop off automatically
  on the next build.
- **Fixtures & Results page** — today's fixtures and yesterday's final
  scores, in a second page linked from the header nav.
- **PWA support** — `manifest.webmanifest` + `icon.svg` at the repo root, so
  the site can be "added to home screen" like an app.
- **Dyslexia-friendly styling carried over** — Atkinson Hyperlegible body
  font, Bricolage Grotesque headings, high contrast, adjustable text size.

## Changes from Gregg's handover doc

1. **RugbyPass feed URL.** The handover's URL (`/feed/`) still 404s — same
   issue as the original Scrum Wire build. Real feed: `/feeds/rss/`.
2. **ESPN Soccer feed dropped.** It consistently returns HTTP 202 with an
   empty body (tried multiple path variants — all blocked, likely
   bot-protected). Replaced with **90min.com** (`https://www.90min.com/feed`),
   verified live to return 90 real items.
3. **Deploys via GitHub Actions' Pages action** (`actions/deploy-pages`)
   rather than "Deploy from a branch" + a `/docs` folder — functionally the
   same result, just the pattern used consistently across the other
   RSS/AI briefings in this account. `index.html` and `fixtures.html` live
   at the repo root, not inside `docs/`.
4. **Cron redundancy.** Three staggered daily triggers (06:30, 07:00, 07:30
   UTC) instead of one — GitHub's Actions scheduler has repeatedly, silently
   dropped single scheduled triggers on other briefings built this way.
   Harmless if more than one fires; the page just rebuilds from the same
   live feeds again.

## Fixtures & Results — data source

Fixtures/results aren't in the transfer RSS feeds, so `scripts/fixtures.py`
needs its own data source:

- **Football**: [football-data.org](https://www.football-data.org/) free
  tier. Needs a free account (sign up yourself — this can't be automated)
  and its API token added as a GitHub repo secret named
  `FOOTBALL_DATA_TOKEN` (Settings → Secrets and variables → Actions → New
  repository secret). Without it, the fixtures page still builds — it just
  explains that a data source isn't connected yet.
- **Rugby**: no reliable free fixtures API found yet. Left for a follow-up —
  `fixtures.py`'s data structures already support adding rugby matches
  (`sport: "Rugby"` entries), so it's a case of finding/wiring a source, not
  restructuring the page.

## Sources — verified live before adding

Every feed was checked with a live `curl` request before being added
(several guessed URLs from official league/club sites 404'd or don't exist —
those sites don't publish their own RSS feeds).

| Sport | Source | Feed |
|---|---|---|
| Rugby | BBC Sport – Rugby Union | direct feed |
| Rugby | BBC Sport – Welsh Rugby | direct feed |
| Rugby | WalesOnline Rugby | direct feed |
| Rugby | RugbyPass | direct feed — **note:** handover doc had `/feed/`, which 404s; real path is `/feeds/rss/` |
| Rugby | The Guardian – Rugby Union | direct feed |
| Rugby | Sky Sports – Rugby Union | direct feed |
| Football | BBC Sport – Football | direct feed |
| Football | Sky Sports – Transfer Centre | direct feed |
| Football | The Guardian – Football | direct feed |
| Football | The Guardian – Transfer Window | direct feed |
| Football | 90min | direct feed — **note:** replaces ESPN Soccer, which is blocked (HTTP 202, empty body) |

League and country tags (Premiership, URC, Top 14, Springboks, Premier
League, La Liga, etc.) are detected per-story from the article text, not
from separate feeds — see `TAGS` near the top of `scripts/build.py`.

## Tweaks you might want later

**Change the update times** — edit the `cron:` lines in
`.github/workflows/build.yml` (UTC).

**Add or remove news sources** — edit the `FEEDS` list near the top of
`scripts/build.py`. Format: `(sport, source name, RSS url)`. Always test a
candidate feed live before adding it:

```bash
curl -s -A "Mozilla/5.0" --max-time 10 -L "<feed-url>" | grep -oE "<\?xml|<rss|<feed"
```

**Make the filter tighter or looser** — edit `TRANSFER_KEYWORDS` in
`scripts/build.py`.

**Add or change league/country tags** — edit `TAGS` in `scripts/build.py`.

**Add football competitions to the fixtures page** — edit
`FOOTBALL_COMPETITIONS` in `scripts/fixtures.py` (uses football-data.org
competition codes).

**Rename the site / change colours** — the title and colour variables
(`:root {...}`) live in the `TEMPLATE` strings in `build.py` and
`fixtures.py`.

## If something looks wrong

- **Page is blank / "No transfer stories found"** — the feeds had no
  matching items in the last 10 days, or a feed URL changed. Run the
  workflow manually (Actions tab → Run workflow) and check the log.
- **Fixtures page says no data source connected** — `FOOTBALL_DATA_TOKEN`
  repo secret isn't set yet, or rugby fixtures (no source wired in).
- **Page not updating** — GitHub pauses scheduled workflows on repos with
  no activity for 60 days; any commit (including the workflow's own daily
  one) re-enables it, so this shouldn't happen in normal operation.
- **A feed errors in the log** — a publisher moved their RSS URL. Update it
  in the `FEEDS` list (test it live first, per the command above).
