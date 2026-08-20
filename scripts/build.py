#!/usr/bin/env python3
"""
Rugby transfer news builder.

Fetches RSS feeds, keeps only transfer/signing/rumour items, cleans the text,
and writes a single static HTML page to index.html.

No external services required at runtime beyond fetching public RSS feeds.
Runs on GitHub Actions on a daily schedule.
"""

import html
import re
import sys
from datetime import datetime, timezone, timedelta

import feedparser  # installed via requirements.txt in the workflow

# ----------------------------------------------------------------------------
# 1. SOURCES  --  add or remove feeds here. Each is (League label, name, url).
#
# URC, Top 14, South Africa, New Zealand, Australia, and Japan don't have
# reliable dedicated transfer-news RSS feeds of their own (checked directly
# against their official/press sites - none publish one), so those use
# Google News RSS search feeds scoped to that league + "transfer", which
# aggregate real articles from legitimate outlets (Planet Rugby, RugbyPass,
# FloRugby, local press etc.) - verified live before adding.
# ----------------------------------------------------------------------------
FEEDS = [
    # --- Wales ---
    ("Wales", "BBC Sport – Welsh Rugby", "https://feeds.bbci.co.uk/sport/rugby-union/welsh/rss.xml"),
    ("Wales", "WalesOnline Rugby", "https://www.walesonline.co.uk/sport/rugby/?service=rss"),

    # --- General / Premiership / European ---
    ("Premiership / General", "BBC Sport – Rugby Union", "https://feeds.bbci.co.uk/sport/rugby-union/rss.xml"),
    # RugbyPass's real feed lives at /feeds/rss/, not /feed/ (Gregg's original
    # URL 404s - confirmed by fetching it directly and checking the homepage's
    # own advertised feed link).
    ("Premiership / General", "RugbyPass", "https://www.rugbypass.com/feeds/rss/"),
    ("Premiership / General", "The Guardian – Rugby Union", "https://www.theguardian.com/sport/rugby-union/rss"),
    ("Premiership / General", "Sky Sports – Rugby Union", "https://www.skysports.com/rss/12040"),

    # --- URC ---
    ("URC", "Google News – URC transfers", "https://news.google.com/rss/search?q=URC+rugby+transfer&hl=en-GB&gl=GB&ceid=GB:en"),

    # --- Top 14 ---
    ("Top 14", "Google News – Top 14 transfers", "https://news.google.com/rss/search?q=Top+14+rugby+transfer&hl=en-GB&gl=GB&ceid=GB:en"),

    # --- South Africa ---
    ("South Africa", "SA Rugby Mag", "https://www.sarugbymag.co.za/feed/"),
    ("South Africa", "Google News – Springbok transfers", "https://news.google.com/rss/search?q=springbok+rugby+transfer&hl=en-ZA&gl=ZA&ceid=ZA:en"),

    # --- New Zealand ---
    ("New Zealand", "Google News – All Blacks transfers", "https://news.google.com/rss/search?q=all+blacks+rugby+transfer&hl=en-NZ&gl=NZ&ceid=NZ:en"),

    # --- Australia ---
    ("Australia", "SMH – Rugby Union", "https://www.smh.com.au/rss/sport/rugby-union.xml"),
    ("Australia", "Google News – Wallabies transfers", "https://news.google.com/rss/search?q=wallabies+rugby+transfer&hl=en-AU&gl=AU&ceid=AU:en"),

    # --- Japan ---
    ("Japan", "Google News – Japan rugby transfers", "https://news.google.com/rss/search?q=japan+rugby+league+one+transfer&hl=en&gl=JP&ceid=JP:en"),

    # --- European cups ---
    ("Champions Cup", "Google News – Champions Cup transfers", "https://news.google.com/rss/search?q=champions+cup+rugby+transfer&hl=en-GB&gl=GB&ceid=GB:en"),
]

# ----------------------------------------------------------------------------
# 2. FILTERING  --  an item is kept only if a transfer keyword appears in the
#    title or summary. Tune these lists to make the feed tighter or wider.
# ----------------------------------------------------------------------------
TRANSFER_KEYWORDS = [
    "transfer", "signs", "sign", "signing", "signed", "joins", "join",
    "move", "moves", "switch", "deal", "contract", "extend", "extension",
    "recruit", "target", "linked", "rumour", "rumor", "speculation",
    "loan", "release", "released", "departs", "departure", "leaves",
    "exit", "swoop", "capture", "agreement", "pen", "penned", "sealed",
    "sacked", "appoint", "appointed", "new coach", "head coach",
    "wantaway", "poised", "set to join", "in talks", "eyeing",
]

# Leagues you care about -- items mentioning these get a small league tag and
# rank slightly higher. Purely cosmetic + light prioritisation.
LEAGUE_TAGS = {
    "URC": ["united rugby championship", "urc"],
    "Premiership": ["premiership", "gallagher", "prem "],
    "Top 14": ["top 14", "top14"],
    "Champions Cup": ["champions cup", "european"],
    "Japan": ["japan", "league one", "japanese"],
    "South Africa": ["south africa", "springbok", "currie cup"],
    "New Zealand": ["new zealand", "all blacks", "super rugby"],
    "Australia": ["australia", "wallabies", "super rugby au"],
    "Wales": ["wales", "welsh", "cardiff", "ospreys", "scarlets", "dragons"],
}

MAX_ITEMS = 60          # cap so the page stays fast on mobile
MAX_AGE_DAYS = 10       # ignore anything older than this


# ----------------------------------------------------------------------------
# 3. HELPERS
# ----------------------------------------------------------------------------
def clean_text(raw: str) -> str:
    """Strip HTML tags and collapse whitespace -> plain readable text."""
    if not raw:
        return ""
    text = re.sub(r"<[^>]+>", " ", raw)      # drop tags
    text = html.unescape(text)               # decode &amp; etc.
    text = re.sub(r"\s+", " ", text).strip()  # collapse whitespace
    return text


def shorten(text: str, limit: int = 260) -> str:
    """Trim waffle: keep it to roughly two sentences / a hard char cap."""
    if not text:
        return ""
    if len(text) <= limit:
        return text
    cut = text[:limit]
    last_stop = max(cut.rfind(". "), cut.rfind("! "), cut.rfind("? "))
    if last_stop > 80:
        return cut[: last_stop + 1]
    return cut.rstrip() + "…"


def is_transfer(title: str, summary: str) -> bool:
    blob = (title + " " + summary).lower()
    return any(re.search(r"\b" + re.escape(k), blob) for k in TRANSFER_KEYWORDS)


def league_for(title: str, summary: str) -> str:
    blob = (title + " " + summary).lower()
    for tag, needles in LEAGUE_TAGS.items():
        if any(n in blob for n in needles):
            return tag
    return ""


def parse_date(entry):
    for key in ("published_parsed", "updated_parsed"):
        val = entry.get(key)
        if val:
            return datetime(*val[:6], tzinfo=timezone.utc)
    return None


# ----------------------------------------------------------------------------
# 4. COLLECT
# ----------------------------------------------------------------------------
def collect():
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=MAX_AGE_DAYS)
    seen_titles = set()
    items = []

    for group, source_name, url in FEEDS:
        try:
            parsed = feedparser.parse(url)
        except Exception as exc:  # noqa: BLE001
            print(f"  ! failed to fetch {source_name}: {exc}", file=sys.stderr)
            continue

        for entry in parsed.entries:
            title = clean_text(entry.get("title", ""))
            summary = clean_text(entry.get("summary", entry.get("description", "")))
            link = entry.get("link", "")

            if not title or not link:
                continue
            if not is_transfer(title, summary):
                continue

            key = title.lower()[:80]
            if key in seen_titles:
                continue
            seen_titles.add(key)

            dt = parse_date(entry)
            if dt and dt < cutoff:
                continue

            items.append({
                "title": title,
                "summary": shorten(summary),
                "link": link,
                "source": source_name,
                "group": group,
                "league": league_for(title, summary),
                "dt": dt or now,
            })

    # newest first
    items.sort(key=lambda x: x["dt"], reverse=True)
    return items[:MAX_ITEMS]


# ----------------------------------------------------------------------------
# 5. RENDER
# ----------------------------------------------------------------------------
def render(items):
    now = datetime.now(timezone.utc)
    updated = now.strftime("%A %d %B %Y, %H:%M UTC")
    count = len(items)

    cards = []
    for it in items:
        when = it["dt"].strftime("%a %d %b")
        league_pill = (
            f'<span class="pill league">{html.escape(it["league"])}</span>'
            if it["league"] else ""
        )
        summary_html = (
            f'<p class="summary">{html.escape(it["summary"])}</p>'
            if it["summary"] else ""
        )
        cards.append(f"""
        <article class="card">
          <div class="meta">
            {league_pill}
            <span class="pill source">{html.escape(it["source"])}</span>
            <span class="date">{when}</span>
          </div>
          <h2><a href="{html.escape(it["link"])}" target="_blank" rel="noopener">{html.escape(it["title"])}</a></h2>
          {summary_html}
          <a class="readmore" href="{html.escape(it["link"])}" target="_blank" rel="noopener">Read full story &rarr;</a>
        </article>""")

    cards_html = "\n".join(cards) if cards else (
        '<p class="empty">No transfer stories found in the feeds right now. '
        'Check back after the next daily update.</p>'
    )

    return TEMPLATE.format(
        updated=updated,
        count=count,
        cards=cards_html,
        year=now.year,
    )


TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Scrum Wire &mdash; Rugby Transfer News</title>
<meta name="description" content="Daily rugby transfer rumours and confirmed moves. Wales, Premiership and the world's pro leagues, filtered and clean.">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:opsz,wght@12..96,600;12..96,800&family=Atkinson+Hyperlegible:ital,wght@0,400;0,700;1,400&display=swap" rel="stylesheet">
<style>
  :root {{
    --ink:      #10231b;
    --paper:    #f3efe4;
    --card:     #ffffff;
    --line:     #d8d2c0;
    --pitch:    #1f5c3d;   /* deep pitch green */
    --pitch-2:  #2e7d52;
    --chalk:    #e9b949;   /* touchline yellow */
    --muted:    #5c6b62;
  }}
  * {{ box-sizing: border-box; }}
  html {{ -webkit-text-size-adjust: 100%; }}
  body {{
    margin: 0;
    background: var(--paper);
    color: var(--ink);
    font-family: "Atkinson Hyperlegible", system-ui, sans-serif;
    font-size: 18px;
    line-height: 1.65;
    letter-spacing: 0.01em;
  }}
  a {{ color: var(--pitch); }}

  /* ---- Header ---- */
  header {{
    background: var(--pitch);
    color: #fff;
    padding: 28px 20px 24px;
    border-bottom: 6px solid var(--chalk);
  }}
  .wrap {{ max-width: 720px; margin: 0 auto; }}
  .brand {{
    font-family: "Bricolage Grotesque", system-ui, sans-serif;
    font-weight: 800;
    font-size: clamp(2rem, 7vw, 3rem);
    line-height: 1.02;
    margin: 0;
    letter-spacing: -0.02em;
  }}
  .brand .ball {{ color: var(--chalk); }}
  .tagline {{
    margin: 8px 0 0;
    font-size: 1rem;
    color: #cfe6da;
    max-width: 46ch;
  }}
  .updated {{
    margin-top: 16px;
    font-size: 0.85rem;
    color: #b9d8c8;
    display: flex;
    gap: 10px;
    flex-wrap: wrap;
    align-items: center;
  }}
  .dot {{ width: 8px; height: 8px; border-radius: 50%; background: var(--chalk); display: inline-block; }}

  /* ---- Feed ---- */
  main {{ padding: 22px 16px 60px; }}
  .count {{
    font-size: 0.85rem;
    color: var(--muted);
    margin: 4px 0 20px;
    text-transform: uppercase;
    letter-spacing: 0.08em;
  }}
  .card {{
    background: var(--card);
    border: 1px solid var(--line);
    border-radius: 14px;
    padding: 18px 18px 16px;
    margin-bottom: 16px;
  }}
  .meta {{
    display: flex;
    gap: 8px;
    align-items: center;
    flex-wrap: wrap;
    margin-bottom: 10px;
  }}
  .pill {{
    font-size: 0.72rem;
    font-weight: 700;
    padding: 3px 9px;
    border-radius: 999px;
    letter-spacing: 0.03em;
  }}
  .pill.league {{ background: var(--pitch); color: #fff; }}
  .pill.source {{ background: #eee7d5; color: var(--muted); }}
  .date {{ font-size: 0.78rem; color: var(--muted); margin-left: auto; }}
  .card h2 {{
    font-family: "Bricolage Grotesque", system-ui, sans-serif;
    font-weight: 700;
    font-size: 1.28rem;
    line-height: 1.22;
    margin: 0 0 8px;
    letter-spacing: -0.01em;
  }}
  .card h2 a {{ color: var(--ink); text-decoration: none; }}
  .card h2 a:hover, .card h2 a:focus {{ color: var(--pitch); text-decoration: underline; }}
  .summary {{ margin: 0 0 12px; color: #26362d; }}
  .readmore {{
    font-weight: 700;
    font-size: 0.9rem;
    text-decoration: none;
    color: var(--pitch-2);
  }}
  .readmore:hover, .readmore:focus {{ text-decoration: underline; }}
  .empty {{ text-align: center; color: var(--muted); padding: 40px 0; }}

  footer {{
    max-width: 720px;
    margin: 0 auto;
    padding: 0 16px 40px;
    color: var(--muted);
    font-size: 0.8rem;
    line-height: 1.5;
  }}
  footer a {{ color: var(--pitch-2); }}

  :focus-visible {{ outline: 3px solid var(--chalk); outline-offset: 2px; border-radius: 4px; }}

  @media (prefers-reduced-motion: no-preference) {{
    .card {{ transition: transform .15s ease, box-shadow .15s ease; }}
    .card:hover {{ transform: translateY(-2px); box-shadow: 0 8px 20px rgba(16,35,27,.08); }}
  }}
</style>
</head>
<body>
  <header>
    <div class="wrap">
      <h1 class="brand">Scrum Wire <span class="ball">&#127945;</span></h1>
      <p class="tagline">Daily rugby transfer rumours and confirmed moves. Wales &amp; the Premiership first, the world's pro leagues right behind. Filtered, trimmed, easy to read.</p>
      <div class="updated"><span class="dot"></span> Updated {updated}</div>
    </div>
  </header>
  <main class="wrap">
    <p class="count">{count} stories</p>
    {cards}
  </main>
  <footer>
    <p>Scrum Wire pulls public RSS feeds and shows the headline, a short trimmed summary, and a link to the full article at the original source. Copyright of each story stays with its publisher. Rebuilt automatically every morning.</p>
    <p>&copy; {year} Scrum Wire &middot; a personal, non-commercial news reader.</p>
  </footer>
</body>
</html>
"""


def main():
    print("Fetching feeds...")
    items = collect()
    print(f"Kept {len(items)} transfer items.")
    page = render(items)
    with open("index.html", "w", encoding="utf-8") as fh:
        fh.write(page)
    print("Wrote index.html")


if __name__ == "__main__":
    main()
