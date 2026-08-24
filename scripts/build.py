#!/usr/bin/env python3
"""
The Transfer Wire -- multi-sport transfer news builder.

Fetches RSS feeds for RUGBY and FOOTBALL, keeps only transfer/signing/rumour
items, cleans the text, tags each story with sport / league / country, and
writes a static, phone-friendly page to index.html.

A second page (fixtures.html) is produced by fixtures.py.

No paid services. Runs on GitHub Actions on a daily schedule. Everything the
reader interacts with (filters, search, NEW badges, text size) is client-side
JavaScript, so it survives every daily rebuild.
"""

import html
import json
import re
import sys
from datetime import datetime, timezone, timedelta

import feedparser  # installed via requirements.txt in the workflow

MAX_ITEMS = 120         # cap so the page stays fast on mobile
MAX_AGE_DAYS = 10       # drop anything older than this

# ----------------------------------------------------------------------------
# 1. SOURCES
#    Each feed is tagged with the SPORT it belongs to. League + country are
#    detected per-story from the text (see TAGS below), because a single feed
#    (e.g. BBC Football) carries many leagues.
#    Format: (sport, source_name, url)
#
#    Two changes from Gregg's original handover, verified live before adding:
#    - RugbyPass: the handover's URL (/feed/) 404s. The real feed is at
#      /feeds/rss/ (same fix needed the first time this project was built).
#    - ESPN Soccer: consistently returns HTTP 202 with an empty body (tried
#      multiple path variants, all blocked) -- dropped. Replaced with
#      90min.com, verified live to return 90 real items.
# ----------------------------------------------------------------------------
FEEDS = [
    # ===================== RUGBY =====================
    ("Rugby", "BBC Sport - Rugby Union", "https://feeds.bbci.co.uk/sport/rugby-union/rss.xml"),
    ("Rugby", "BBC Sport - Welsh Rugby", "https://feeds.bbci.co.uk/sport/rugby-union/welsh/rss.xml"),
    ("Rugby", "WalesOnline Rugby", "https://www.walesonline.co.uk/sport/rugby/?service=rss"),
    ("Rugby", "RugbyPass", "https://www.rugbypass.com/feeds/rss/"),
    ("Rugby", "The Guardian - Rugby Union", "https://www.theguardian.com/sport/rugby-union/rss"),
    ("Rugby", "Sky Sports - Rugby Union", "https://www.skysports.com/rss/12040"),

    # ===================== FOOTBALL =====================
    ("Football", "BBC Sport - Football", "https://feeds.bbci.co.uk/sport/football/rss.xml"),
    ("Football", "Sky Sports - Transfer Centre", "https://www.skysports.com/rss/12691"),
    ("Football", "The Guardian - Football", "https://www.theguardian.com/football/rss"),
    ("Football", "The Guardian - Transfer Window", "https://www.theguardian.com/football/transfer-window/rss"),
    ("Football", "90min", "https://www.90min.com/feed"),
]

# ----------------------------------------------------------------------------
# 2. TRANSFER FILTER  --  an item is kept only if one of these appears in the
#    title or summary. Shared across both sports.
# ----------------------------------------------------------------------------
TRANSFER_KEYWORDS = [
    "transfer", "signs", "sign", "signing", "signed", "joins", "join",
    "move", "moves", "switch", "deal", "contract", "extend", "extension",
    "recruit", "target", "linked", "rumour", "rumor", "speculation",
    "loan", "release", "released", "departs", "departure", "leaves",
    "exit", "swoop", "capture", "agreement", "pen", "penned", "sealed",
    "sacked", "appoint", "appointed", "new coach", "head coach", "manager",
    "wantaway", "poised", "set to join", "in talks", "eyeing", "bid",
    "fee", "medical", "unveiled", "clause", "buyout", "free agent",
]

# ----------------------------------------------------------------------------
# 3. TAGS  --  per sport, map a LEAGUE label to the keywords that identify it,
#    plus the COUNTRY it sits in. Detection is text-based on title + summary.
#    Order matters: first match wins for the league.
#    Structure: TAGS[sport] = list of (league, country, [keywords])
# ----------------------------------------------------------------------------
TAGS = {
    "Rugby": [
        ("Premiership",     "England",       ["premiership", "gallagher", "leicester tigers", "saracens", "harlequins", "bath rugby", "sale sharks", "northampton", "exeter chiefs", "bristol bears", "gloucester rugby"]),
        ("URC",             "Multi-nation",  ["united rugby championship", "urc"]),
        ("Wales",           "Wales",         ["wales", "welsh", "cardiff rugby", "ospreys", "scarlets", "dragons", "wru"]),
        ("Top 14",          "France",        ["top 14", "top14", "toulouse", "racing 92", "toulon", "la rochelle", "bordeaux", "clermont", "montpellier"]),
        ("Champions Cup",   "Europe",        ["champions cup", "investec champions", "european rugby"]),
        ("South Africa",    "South Africa",  ["south africa", "springbok", "currie cup", "bulls", "sharks", "stormers"]),
        ("New Zealand",     "New Zealand",   ["new zealand", "all blacks", "super rugby", "crusaders", "hurricanes", "highlanders"]),
        ("Australia",       "Australia",     ["australia", "wallabies", "waratahs", "brumbies", "queensland reds"]),
        ("Japan",           "Japan",         ["japan", "league one", "japanese", "brave blossoms"]),
        ("International",    "International", ["six nations", "rugby championship", "test match", "autumn nations", "lions tour", "rugby world cup"]),
    ],
    "Football": [
        ("Premier League",  "England",       ["premier league", "arsenal", "chelsea", "liverpool", "manchester united", "man utd", "manchester city", "man city", "tottenham", "spurs", "newcastle", "aston villa", "west ham", "everton", "brighton", "wolves", "nottingham forest", "brentford", "crystal palace", "fulham", "bournemouth"]),
        ("La Liga",         "Spain",         ["la liga", "real madrid", "barcelona", "atletico madrid", "sevilla", "valencia", "villarreal", "real betis", "athletic bilbao"]),
        ("Serie A",         "Italy",         ["serie a", "juventus", "inter milan", "ac milan", "napoli", "as roma", "lazio", "atalanta", "fiorentina"]),
        ("Bundesliga",      "Germany",       ["bundesliga", "bayern munich", "borussia dortmund", "dortmund", "rb leipzig", "bayer leverkusen", "wolfsburg"]),
        ("Ligue 1",         "France",        ["ligue 1", "psg", "paris saint-germain", "marseille", "as monaco", "lyon", "lille"]),
        ("MLS",             "USA",           ["mls", "major league soccer", "inter miami", "la galaxy", "lafc", "atlanta united"]),
        ("Saudi Pro League","Saudi Arabia",  ["saudi pro league", "al nassr", "al-nassr", "al hilal", "al-hilal", "al ittihad", "al-ittihad", "al ahli", "saudi league"]),
        ("Champions League","Europe",        ["champions league", "uefa champions"]),
        ("International",    "International", ["world cup", "euro 2028", "nations league", "international friendly", "world cup qualifier", "copa america", "afcon"]),
    ],
}


# ----------------------------------------------------------------------------
# 4. HELPERS
# ----------------------------------------------------------------------------
def clean_text(raw: str) -> str:
    if not raw:
        return ""
    text = re.sub(r"<[^>]+>", " ", raw)
    text = html.unescape(text)
    text = re.sub(r"\s+", " ", text).strip()
    return text


def shorten(text: str, limit: int = 260) -> str:
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


def tag_story(sport: str, title: str, summary: str):
    """Return (league, country). Falls back to ('General', '') if unknown."""
    blob = (title + " " + summary).lower()
    for league, country, needles in TAGS.get(sport, []):
        if any(n in blob for n in needles):
            return league, country
    return "General", ""


def parse_date(entry):
    for key in ("published_parsed", "updated_parsed"):
        val = entry.get(key)
        if val:
            return datetime(*val[:6], tzinfo=timezone.utc)
    return None


def make_id(title: str) -> str:
    """Stable short id for a story, used by the browser to track 'seen'."""
    import hashlib
    return hashlib.md5(title.lower().encode("utf-8")).hexdigest()[:12]


# ----------------------------------------------------------------------------
# 5. COLLECT
# ----------------------------------------------------------------------------
def collect():
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=MAX_AGE_DAYS)
    seen_titles = set()
    items = []

    for sport, source_name, url in FEEDS:
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

            league, country = tag_story(sport, title, summary)
            items.append({
                "id": make_id(title),
                "title": title,
                "summary": shorten(summary),
                "link": link,
                "source": source_name,
                "sport": sport,
                "league": league,
                "country": country,
                "dt": dt or now,
            })

    items.sort(key=lambda x: x["dt"], reverse=True)
    return items[:MAX_ITEMS]


# ----------------------------------------------------------------------------
# 6. RENDER
# ----------------------------------------------------------------------------
def render(items):
    now = datetime.now(timezone.utc)
    updated = now.strftime("%A %d %B %Y, %H:%M UTC")

    sports = ["Rugby", "Football"]
    leagues_by_sport = {s: [] for s in sports}
    countries_by_league = {}
    for it in items:
        s, lg, c = it["sport"], it["league"], it["country"]
        if lg not in leagues_by_sport.setdefault(s, []):
            leagues_by_sport[s].append(lg)
        countries_by_league.setdefault(lg, [])
        if c and c not in countries_by_league[lg]:
            countries_by_league[lg].append(c)

    for s in leagues_by_sport:
        order = [lg for lg, _, _ in TAGS.get(s, [])]
        leagues_by_sport[s].sort(
            key=lambda lg: order.index(lg) if lg in order else 999
        )

    cards = []
    for it in items:
        when = it["dt"].strftime("%a %d %b")
        pills = [f'<span class="pill sport {it["sport"].lower()}">{html.escape(it["sport"])}</span>']
        if it["league"] and it["league"] != "General":
            pills.append(f'<span class="pill league">{html.escape(it["league"])}</span>')
        pills.append(f'<span class="pill source">{html.escape(it["source"])}</span>')
        summary_html = (
            f'<p class="summary">{html.escape(it["summary"])}</p>'
            if it["summary"] else ""
        )
        search_blob = html.escape((it["title"] + " " + (it["summary"] or "")).lower())
        cards.append(f"""
        <article class="card" data-id="{it['id']}"
                 data-sport="{html.escape(it['sport'])}"
                 data-league="{html.escape(it['league'])}"
                 data-country="{html.escape(it['country'])}"
                 data-search="{search_blob}">
          <span class="new-badge" hidden>NEW</span>
          <div class="meta">
            {' '.join(pills)}
            <span class="date">{when}</span>
          </div>
          <h2><a href="{html.escape(it['link'])}" target="_blank" rel="noopener">{html.escape(it['title'])}</a></h2>
          {summary_html}
          <a class="readmore" href="{html.escape(it['link'])}" target="_blank" rel="noopener">Read full story &rarr;</a>
        </article>""")

    cards_html = "\n".join(cards) if cards else (
        '<p class="empty">No transfer stories found in the feeds right now. '
        'Check back after the next daily update.</p>'
    )

    data_json = json.dumps({
        "leaguesBySport": leagues_by_sport,
        "countriesByLeague": countries_by_league,
    })

    return TEMPLATE.format(
        updated=updated,
        count=len(items),
        cards=cards_html,
        data_json=data_json,
        year=now.year,
    )


# ----------------------------------------------------------------------------
# 7. TEMPLATE
# ----------------------------------------------------------------------------
TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>The Transfer Wire</title>
<meta name="description" content="Daily rugby and football transfer news. Rumours and confirmed moves, filtered, trimmed, easy to read.">
<meta name="theme-color" content="#123c2a">
<link rel="manifest" href="manifest.webmanifest">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=Bricolage+Grotesque:opsz,wght@12..96,600;12..96,800&family=Atkinson+Hyperlegible:ital,wght@0,400;0,700;1,400&display=swap" rel="stylesheet">
<style>
  :root {{
    --ink:#10231b; --paper:#f3efe4; --card:#ffffff; --line:#d8d2c0;
    --pitch:#1f5c3d; --pitch-2:#2e7d52; --chalk:#e9b949; --muted:#5c6b62;
    --football:#2b5fd0;
  }}
  * {{ box-sizing:border-box; }}
  html {{ -webkit-text-size-adjust:100%; }}
  body {{
    margin:0; background:var(--paper); color:var(--ink);
    font-family:"Atkinson Hyperlegible",system-ui,sans-serif;
    font-size:18px; line-height:1.65; letter-spacing:0.01em;
  }}
  a {{ color:var(--pitch); }}
  .wrap {{ max-width:720px; margin:0 auto; }}

  .topbar {{
    position:sticky; top:0; z-index:30; background:var(--pitch);
    padding:10px 16px; display:flex; gap:8px; align-items:center;
    border-bottom:3px solid var(--chalk);
  }}
  .topbar .search {{
    flex:1 1 auto; min-width:0;
    font-family:"Atkinson Hyperlegible",system-ui,sans-serif; font-size:1rem;
    color:var(--ink); background:#fff; border:0; border-radius:999px;
    padding:11px 16px;
  }}
  .topbar .search:focus-visible {{ outline:3px solid var(--chalk); outline-offset:1px; }}
  .size-btn {{
    flex:0 0 auto; font-family:"Bricolage Grotesque",system-ui,sans-serif;
    font-weight:700; font-size:0.9rem; color:#fff; background:transparent;
    border:1.5px solid rgba(255,255,255,.5); border-radius:9px;
    width:38px; height:38px; cursor:pointer;
  }}
  .size-btn:hover, .size-btn:focus-visible {{ border-color:var(--chalk); }}

  header {{ background:var(--pitch); color:#fff; padding:22px 20px 24px; }}
  .brand {{
    font-family:"Bricolage Grotesque",system-ui,sans-serif; font-weight:800;
    font-size:clamp(1.9rem,6.5vw,2.8rem); line-height:1.02; margin:0;
    letter-spacing:-0.02em;
  }}
  .brand .ball {{ color:var(--chalk); }}
  .tagline {{ margin:8px 0 0; font-size:0.98rem; color:#cfe6da; max-width:48ch; }}
  .updated {{ margin-top:14px; font-size:0.82rem; color:#b9d8c8; display:flex; gap:10px; align-items:center; flex-wrap:wrap; }}
  .dot {{ width:8px; height:8px; border-radius:50%; background:var(--chalk); display:inline-block; }}
  nav.pages {{ margin-top:16px; display:flex; gap:8px; }}
  nav.pages a {{
    font-weight:700; font-size:0.9rem; text-decoration:none; color:#fff;
    background:rgba(255,255,255,.12); padding:8px 16px; border-radius:999px;
  }}
  nav.pages a.active {{ background:var(--chalk); color:var(--ink); }}

  .controls {{ padding:14px 16px 4px; display:flex; flex-direction:column; gap:10px; }}
  .selectrow {{ display:flex; gap:8px; }}
  .selectrow select {{
    flex:1 1 0; min-width:0;
    font-family:"Atkinson Hyperlegible",system-ui,sans-serif; font-size:0.95rem;
    font-weight:700; color:var(--ink); background:#fff;
    border:1.5px solid var(--line); border-radius:12px; padding:10px 12px;
  }}
  .leagues {{ display:flex; gap:8px; overflow-x:auto; padding-bottom:4px; scrollbar-width:none; }}
  .leagues::-webkit-scrollbar {{ display:none; }}
  .filter-btn {{
    flex:0 0 auto; font-family:"Atkinson Hyperlegible",system-ui,sans-serif;
    font-size:0.9rem; font-weight:700; color:var(--pitch); background:#fff;
    border:1.5px solid var(--line); border-radius:999px; padding:7px 15px;
    cursor:pointer; white-space:nowrap;
  }}
  .filter-btn.active {{ background:var(--pitch); color:#fff; border-color:var(--pitch); }}

  main {{ padding:16px 16px 60px; }}
  .count {{ font-size:0.85rem; color:var(--muted); margin:4px 0 18px; text-transform:uppercase; letter-spacing:0.08em; }}
  .card {{ position:relative; background:var(--card); border:1px solid var(--line); border-radius:14px; padding:18px 18px 16px; margin-bottom:16px; }}
  .card[hidden] {{ display:none; }}
  .new-badge {{
    position:absolute; top:12px; right:12px; background:var(--chalk);
    color:var(--ink); font-family:"Bricolage Grotesque",system-ui,sans-serif;
    font-weight:800; font-size:0.68rem; letter-spacing:0.05em;
    padding:3px 8px; border-radius:999px;
  }}
  .meta {{ display:flex; gap:8px; align-items:center; flex-wrap:wrap; margin-bottom:10px; padding-right:44px; }}
  .pill {{ font-size:0.72rem; font-weight:700; padding:3px 9px; border-radius:999px; letter-spacing:0.03em; }}
  .pill.sport.rugby {{ background:var(--pitch); color:#fff; }}
  .pill.sport.football {{ background:var(--football); color:#fff; }}
  .pill.league {{ background:#e7efe9; color:var(--pitch); }}
  .pill.source {{ background:#eee7d5; color:var(--muted); }}
  .date {{ font-size:0.78rem; color:var(--muted); margin-left:auto; }}
  .card h2 {{ font-family:"Bricolage Grotesque",system-ui,sans-serif; font-weight:700; font-size:1.28rem; line-height:1.22; margin:0 0 8px; letter-spacing:-0.01em; }}
  .card h2 a {{ color:var(--ink); text-decoration:none; }}
  .card h2 a:hover, .card h2 a:focus {{ color:var(--pitch); text-decoration:underline; }}
  .summary {{ margin:0 0 12px; color:#26362d; }}
  .readmore {{ font-weight:700; font-size:0.9rem; text-decoration:none; color:var(--pitch-2); }}
  .readmore:hover, .readmore:focus {{ text-decoration:underline; }}
  .empty {{ text-align:center; color:var(--muted); padding:40px 0; }}

  footer {{ max-width:720px; margin:0 auto; padding:0 16px 40px; color:var(--muted); font-size:0.8rem; line-height:1.5; }}
  footer a {{ color:var(--pitch-2); }}
  :focus-visible {{ outline:3px solid var(--chalk); outline-offset:2px; border-radius:4px; }}
  @media (prefers-reduced-motion: no-preference) {{
    .card {{ transition:transform .15s ease, box-shadow .15s ease; }}
    .card:hover {{ transform:translateY(-2px); box-shadow:0 8px 20px rgba(16,35,27,.08); }}
  }}
</style>
</head>
<body>
  <div class="topbar">
    <input type="search" id="search" class="search" placeholder="Search player, club or country…" aria-label="Search stories" autocomplete="off">
    <button id="text-smaller" class="size-btn" aria-label="Smaller text">A&minus;</button>
    <button id="text-bigger" class="size-btn" aria-label="Bigger text">A+</button>
  </div>

  <header>
    <div class="wrap">
      <h1 class="brand">The Transfer Wire <span class="ball">&#9917;</span></h1>
      <p class="tagline">Daily rugby &amp; football transfer news. Rumours and confirmed moves, filtered, trimmed, easy to read.</p>
      <div class="updated"><span class="dot"></span> Updated {updated}</div>
      <nav class="pages">
        <a href="index.html" class="active">Transfers</a>
        <a href="fixtures.html">Fixtures &amp; Results</a>
      </nav>
    </div>
  </header>

  <div class="controls wrap">
    <div class="selectrow">
      <select id="sport-select" aria-label="Sport">
        <option value="all">All sports</option>
        <option value="Rugby">Rugby</option>
        <option value="Football">Football</option>
      </select>
      <select id="country-select" aria-label="Country">
        <option value="all">All countries</option>
      </select>
    </div>
    <div class="leagues" id="leagues">
      <button class="filter-btn active" data-filter="all">All leagues</button>
    </div>
  </div>

  <main class="wrap">
    <p class="count" id="count">{count} stories</p>
    <div id="feed">
    {cards}
    </div>
    <p class="empty" id="no-results" hidden>Nothing matches. Try clearing the search or choosing All.</p>
  </main>

  <footer>
    <p>The Transfer Wire pulls public RSS feeds and shows the headline, a short trimmed summary, and a link to the full article at the original source. Copyright of each story stays with its publisher. Rebuilt automatically every morning.</p>
    <p>&copy; {year} The Transfer Wire &middot; a personal, non-commercial news reader.</p>
  </footer>

  <script id="filter-data" type="application/json">{data_json}</script>
  <script>
    (function () {{
      var DATA = JSON.parse(document.getElementById('filter-data').textContent);
      var cards = Array.prototype.slice.call(document.querySelectorAll('.card'));
      var countEl = document.getElementById('count');
      var noResults = document.getElementById('no-results');
      var searchEl = document.getElementById('search');
      var sportSel = document.getElementById('sport-select');
      var countrySel = document.getElementById('country-select');
      var leaguesBox = document.getElementById('leagues');

      var state = {{ sport:'all', league:'all', country:'all', query:'' }};

      // ---------- NEW badge: compare against ids seen on last visit ----------
      var SEEN_KEY = 'ttw-seen-ids';
      var seen = {{}};
      try {{ seen = JSON.parse(localStorage.getItem(SEEN_KEY) || '{{}}'); }} catch (e) {{ seen = {{}}; }}
      var currentIds = [];
      cards.forEach(function (card) {{
        var id = card.getAttribute('data-id');
        currentIds.push(id);
        if (!seen[id]) {{ card.querySelector('.new-badge').hidden = false; }}
      }});
      var nextSeen = {{}};
      currentIds.forEach(function (id) {{ nextSeen[id] = Date.now(); }});
      try {{ localStorage.setItem(SEEN_KEY, JSON.stringify(nextSeen)); }} catch (e) {{}}

      function rebuildLeagues() {{
        var out = '<button class="filter-btn active" data-filter="all">All leagues</button>';
        var list = [];
        if (state.sport === 'all') {{
          Object.keys(DATA.leaguesBySport).forEach(function (s) {{
            DATA.leaguesBySport[s].forEach(function (lg) {{
              if (list.indexOf(lg) === -1) list.push(lg);
            }});
          }});
        }} else {{
          list = (DATA.leaguesBySport[state.sport] || []).slice();
        }}
        list.forEach(function (lg) {{
          if (lg === 'General') return;
          out += '<button class="filter-btn" data-filter="' + lg + '">' + lg + '</button>';
        }});
        leaguesBox.innerHTML = out;
        state.league = 'all';
        bindLeagueButtons();
      }}

      function bindLeagueButtons() {{
        leaguesBox.querySelectorAll('.filter-btn').forEach(function (btn) {{
          btn.addEventListener('click', function () {{
            leaguesBox.querySelectorAll('.filter-btn').forEach(function (b) {{ b.classList.remove('active'); }});
            btn.classList.add('active');
            state.league = btn.getAttribute('data-filter');
            apply();
          }});
        }});
      }}

      function rebuildCountries() {{
        var set = [];
        cards.forEach(function (card) {{
          if (state.sport !== 'all' && card.getAttribute('data-sport') !== state.sport) return;
          var c = card.getAttribute('data-country');
          if (c && set.indexOf(c) === -1) set.push(c);
        }});
        set.sort();
        var out = '<option value="all">All countries</option>';
        set.forEach(function (c) {{ out += '<option value="' + c + '">' + c + '</option>'; }});
        countrySel.innerHTML = out;
        state.country = 'all';
      }}

      function apply() {{
        var shown = 0;
        cards.forEach(function (card) {{
          var ok = true;
          if (state.sport !== 'all' && card.getAttribute('data-sport') !== state.sport) ok = false;
          if (ok && state.league !== 'all' && card.getAttribute('data-league') !== state.league) ok = false;
          if (ok && state.country !== 'all' && card.getAttribute('data-country') !== state.country) ok = false;
          if (ok && state.query && card.getAttribute('data-search').indexOf(state.query) === -1) ok = false;
          card.hidden = !ok;
          if (ok) shown++;
        }});
        countEl.textContent = shown + (shown === 1 ? ' story' : ' stories');
        noResults.hidden = shown !== 0;
      }}

      sportSel.addEventListener('change', function () {{
        state.sport = sportSel.value;
        rebuildLeagues();
        rebuildCountries();
        apply();
      }});
      countrySel.addEventListener('change', function () {{
        state.country = countrySel.value;
        apply();
      }});
      searchEl.addEventListener('input', function () {{
        state.query = searchEl.value.trim().toLowerCase();
        apply();
      }});

      bindLeagueButtons();
      rebuildCountries();

      var STEPS = [16, 18, 20, 23, 26];
      var idx = 1;
      try {{ var sv = parseInt(localStorage.getItem('ttw-textsize'),10); if(!isNaN(sv)&&sv>=0&&sv<STEPS.length) idx=sv; }} catch(e){{}}
      function applySize() {{ document.body.style.fontSize = STEPS[idx]+'px'; try{{localStorage.setItem('ttw-textsize',idx);}}catch(e){{}} }}
      document.getElementById('text-bigger').addEventListener('click', function(){{ if(idx<STEPS.length-1){{idx++;applySize();}} }});
      document.getElementById('text-smaller').addEventListener('click', function(){{ if(idx>0){{idx--;applySize();}} }});
      applySize();
    }})();
  </script>
</body>
</html>
"""


def main():
    print("Fetching feeds...")
    items = collect()
    print(f"Kept {len(items)} transfer items.")
    with open("index.html", "w", encoding="utf-8") as fh:
        fh.write(render(items))
    print("Wrote index.html")


if __name__ == "__main__":
    main()
