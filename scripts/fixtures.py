#!/usr/bin/env python3
"""
The Transfer Wire -- Fixtures & Results page builder.

Design (agreed with Gregg): the site rebuilds ONCE a day, so instead of live
scores we show:
  * TODAY'S FIXTURES  -- games happening today (kickoff times)
  * YESTERDAY'S RESULTS -- final scores from the day before (settled overnight)

This avoids any need for live/real-time data: by the next morning's build,
yesterday's matches are finished and their scores are final.

DATA SOURCE NOTE
----------------
Fixtures/results are NOT in the transfer RSS feeds, so this page needs a sports
data source:
  * Football -- football-data.org (free tier, needs a free API token -> repo
    secret FOOTBALL_DATA_TOKEN).
  * Rugby -- ESPN's public scoreboard API (site.api.espn.com). No signup or
    key needed. This is an UNOFFICIAL/undocumented endpoint used widely by
    hobby projects, not a published ESPN product -- it could change or be
    withdrawn without notice. If it ever breaks, the rugby section just goes
    quiet (RUGBY_COMPETITIONS below can be swapped for a documented API if
    one appears).

This script DEGRADES GRACEFULLY: if a source has no data (off-season, no
token, endpoint down) it still writes a valid page, so it never breaks the
daily build.
"""

import html
import json
import os
import sys
from datetime import datetime, timezone, timedelta

try:
    import urllib.request
    import urllib.error
except Exception:  # pragma: no cover
    urllib = None


# ----------------------------------------------------------------------------
# Competitions to show, grouped by sport. football-data.org competition codes
# are given where relevant; extend as needed.
# ----------------------------------------------------------------------------
FOOTBALL_COMPETITIONS = {
    # label : football-data.org code
    "Premier League": "PL",
    "La Liga": "PD",
    "Serie A": "SA",
    "Bundesliga": "BL1",
    "Ligue 1": "FL1",
    "Champions League": "CL",
    # MLS / Saudi / internationals: not on football-data free tier; would need
    # an alternative source.
}

FOOTBALL_DATA_TOKEN = os.environ.get("FOOTBALL_DATA_TOKEN", "").strip()

# label : ESPN numeric league ID (verified live via
# sports.core.api.espn.com/v2/sports/rugby/leagues before adding)
RUGBY_COMPETITIONS = {
    "Gallagher Premiership": "267979",
    "United Rugby Championship": "270557",
    "Top 14": "270559",
    "Six Nations": "180659",
}


def _get_json(url, headers=None):
    req = urllib.request.Request(url, headers=headers or {}, )
    req.add_header("Accept-Encoding", "gzip")
    with urllib.request.urlopen(req, timeout=20) as resp:
        raw = resp.read()
        if resp.info().get("Content-Encoding") == "gzip":
            import gzip
            raw = gzip.decompress(raw)
        return json.loads(raw.decode("utf-8"))


def fetch_football(day: datetime):
    """Return list of match dicts for a given UTC date, or [] if unavailable."""
    if not FOOTBALL_DATA_TOKEN:
        return []
    date_str = day.strftime("%Y-%m-%d")
    headers = {"X-Auth-Token": FOOTBALL_DATA_TOKEN}
    out = []
    for label, code in FOOTBALL_COMPETITIONS.items():
        url = (f"https://api.football-data.org/v4/competitions/{code}/matches"
               f"?dateFrom={date_str}&dateTo={date_str}")
        try:
            data = _get_json(url, headers)
        except Exception as exc:  # noqa: BLE001
            print(f"  ! football-data {label} {date_str}: {exc}", file=sys.stderr)
            continue
        for m in data.get("matches", []):
            home = m.get("homeTeam", {}).get("shortName") or m.get("homeTeam", {}).get("name", "?")
            away = m.get("awayTeam", {}).get("shortName") or m.get("awayTeam", {}).get("name", "?")
            score = m.get("score", {}).get("fullTime", {})
            hs, as_ = score.get("home"), score.get("away")
            kickoff = m.get("utcDate", "")
            try:
                ko = datetime.fromisoformat(kickoff.replace("Z", "+00:00")).strftime("%H:%M")
            except Exception:
                ko = ""
            out.append({
                "sport": "Football",
                "league": label,
                "home": home,
                "away": away,
                "home_score": hs,
                "away_score": as_,
                "kickoff": ko,
                "status": m.get("status", ""),
            })
    return out


def fetch_rugby(day: datetime):
    """Return list of match dicts for a given UTC date, or [] if unavailable."""
    date_str = day.strftime("%Y%m%d")
    out = []
    for label, league_id in RUGBY_COMPETITIONS.items():
        url = (f"https://site.api.espn.com/apis/site/v2/sports/rugby/"
               f"{league_id}/scoreboard?dates={date_str}")
        try:
            data = _get_json(url)
        except Exception as exc:  # noqa: BLE001
            print(f"  ! ESPN rugby {label} {date_str}: {exc}", file=sys.stderr)
            continue
        for e in data.get("events", []):
            comp = (e.get("competitions") or [{}])[0]
            competitors = comp.get("competitors", [])
            home = next((c for c in competitors if c.get("homeAway") == "home"), {})
            away = next((c for c in competitors if c.get("homeAway") == "away"), {})
            status = comp.get("status", {}).get("type", {}).get("name", "")
            hs = home.get("score") if status == "STATUS_FINAL" else None
            as_ = away.get("score") if status == "STATUS_FINAL" else None
            kickoff = e.get("date", "")
            try:
                ko = datetime.fromisoformat(kickoff.replace("Z", "+00:00")).strftime("%H:%M")
            except Exception:
                ko = ""
            out.append({
                "sport": "Rugby",
                "league": label,
                "home": home.get("team", {}).get("displayName", "?"),
                "away": away.get("team", {}).get("displayName", "?"),
                "home_score": hs,
                "away_score": as_,
                "kickoff": ko,
                "status": status,
            })
    return out


def match_row(m, show_score):
    left = html.escape(m["home"])
    right = html.escape(m["away"])
    if show_score and m["home_score"] is not None and m["away_score"] is not None:
        mid = f'<span class="score">{m["home_score"]} &ndash; {m["away_score"]}</span>'
    else:
        mid = f'<span class="kickoff">{html.escape(m["kickoff"] or "TBC")}</span>'
    return f"""
      <div class="match" data-sport="{html.escape(m['sport'])}" data-league="{html.escape(m['league'])}">
        <span class="team home">{left}</span>
        {mid}
        <span class="team away">{right}</span>
        <span class="mleague">{html.escape(m['league'])}</span>
      </div>"""


def section(title, matches, show_score):
    if not matches:
        body = '<p class="empty">Nothing listed for the selected leagues.</p>'
    else:
        # group by league for tidy display
        by_league = {}
        for m in matches:
            by_league.setdefault(m["league"], []).append(m)
        blocks = []
        for lg, ms in by_league.items():
            rows = "\n".join(match_row(m, show_score) for m in ms)
            blocks.append(f'<h3 class="lg-head">{html.escape(lg)}</h3>{rows}')
        body = "\n".join(blocks)
    return f'<section class="fx-section"><h2>{html.escape(title)}</h2>{body}</section>'


def render(today_matches, yesterday_matches, note):
    now = datetime.now(timezone.utc)
    updated = now.strftime("%A %d %B %Y, %H:%M UTC")
    today_label = now.strftime("%A %d %B")
    yday_label = (now - timedelta(days=1)).strftime("%A %d %B")

    note_html = f'<p class="note">{html.escape(note)}</p>' if note else ""

    today_html = section(f"Today's Fixtures - {today_label}", today_matches, show_score=False)
    yday_html = section(f"Yesterday's Results - {yday_label}", yesterday_matches, show_score=True)

    return TEMPLATE.format(
        updated=updated,
        note=note_html,
        today=today_html,
        yesterday=yday_html,
        year=now.year,
    )


TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Fixtures &amp; Results - The Transfer Wire</title>
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
  body {{ margin:0; background:var(--paper); color:var(--ink); font-family:"Atkinson Hyperlegible",system-ui,sans-serif; font-size:18px; line-height:1.6; }}
  .wrap {{ max-width:720px; margin:0 auto; }}
  header {{ background:var(--pitch); color:#fff; padding:22px 20px 24px; border-bottom:6px solid var(--chalk); }}
  .brand {{ font-family:"Bricolage Grotesque",system-ui,sans-serif; font-weight:800; font-size:clamp(1.7rem,6vw,2.5rem); margin:0; letter-spacing:-0.02em; }}
  .brand .ball {{ color:var(--chalk); }}
  .updated {{ margin-top:12px; font-size:0.82rem; color:#b9d8c8; }}
  nav.pages {{ margin-top:16px; display:flex; gap:8px; }}
  nav.pages a {{ font-weight:700; font-size:0.9rem; text-decoration:none; color:#fff; background:rgba(255,255,255,.12); padding:8px 16px; border-radius:999px; }}
  nav.pages a.active {{ background:var(--chalk); color:var(--ink); }}

  .controls {{ padding:14px 16px 0; display:flex; gap:8px; }}
  .controls select {{ flex:1 1 0; font-family:"Atkinson Hyperlegible",system-ui,sans-serif; font-size:0.95rem; font-weight:700; color:var(--ink); background:#fff; border:1.5px solid var(--line); border-radius:12px; padding:10px 12px; }}

  main {{ padding:16px 16px 60px; }}
  .note {{ background:#fff6da; border:1px solid var(--chalk); border-radius:12px; padding:12px 14px; font-size:0.9rem; color:#5a4a12; }}
  .fx-section {{ margin-top:22px; }}
  .fx-section > h2 {{ font-family:"Bricolage Grotesque",system-ui,sans-serif; font-size:1.15rem; margin:0 0 12px; letter-spacing:-0.01em; }}
  .lg-head {{ font-size:0.82rem; text-transform:uppercase; letter-spacing:0.08em; color:var(--muted); margin:16px 0 6px; }}
  .match {{ display:grid; grid-template-columns:1fr auto 1fr; align-items:center; gap:8px; background:var(--card); border:1px solid var(--line); border-radius:12px; padding:12px 14px; margin-bottom:8px; position:relative; }}
  .team {{ font-weight:700; }}
  .team.home {{ text-align:right; }}
  .team.away {{ text-align:left; }}
  .score {{ font-family:"Bricolage Grotesque",system-ui,sans-serif; font-weight:800; font-size:1.1rem; background:var(--pitch); color:#fff; padding:3px 12px; border-radius:8px; white-space:nowrap; }}
  .kickoff {{ font-weight:700; color:var(--muted); background:#eee7d5; padding:3px 12px; border-radius:8px; white-space:nowrap; }}
  .mleague {{ display:none; }}
  .match[hidden] {{ display:none; }}
  .empty {{ color:var(--muted); padding:10px 0; }}
  footer {{ max-width:720px; margin:0 auto; padding:20px 16px 40px; color:var(--muted); font-size:0.8rem; }}
</style>
</head>
<body>
  <header>
    <div class="wrap">
      <h1 class="brand">Fixtures &amp; Results <span class="ball">&#9917;</span></h1>
      <div class="updated">Updated {updated}</div>
      <nav class="pages">
        <a href="index.html">Transfers</a>
        <a href="fixtures.html" class="active">Fixtures &amp; Results</a>
      </nav>
    </div>
  </header>

  <div class="controls wrap">
    <select id="sport-select" aria-label="Sport">
      <option value="all">All sports</option>
      <option value="Rugby">Rugby</option>
      <option value="Football">Football</option>
    </select>
    <select id="league-select" aria-label="League">
      <option value="all">All leagues</option>
    </select>
  </div>

  <main class="wrap">
    {note}
    {today}
    {yesterday}
  </main>

  <footer>
    <p>Today's fixtures and yesterday's final results. Because the site refreshes once each morning, scores appear the day after a match is played. &copy; {year} The Transfer Wire.</p>
  </footer>

  <script>
    (function () {{
      var matches = Array.prototype.slice.call(document.querySelectorAll('.match'));
      var sportSel = document.getElementById('sport-select');
      var leagueSel = document.getElementById('league-select');

      function leaguesFor(sport) {{
        var set = [];
        matches.forEach(function (m) {{
          if (sport !== 'all' && m.getAttribute('data-sport') !== sport) return;
          var lg = m.getAttribute('data-league');
          if (lg && set.indexOf(lg) === -1) set.push(lg);
        }});
        set.sort();
        return set;
      }}
      function rebuildLeagues() {{
        var out = '<option value="all">All leagues</option>';
        leaguesFor(sportSel.value).forEach(function (lg) {{
          out += '<option value="' + lg + '">' + lg + '</option>';
        }});
        leagueSel.innerHTML = out;
      }}
      function apply() {{
        matches.forEach(function (m) {{
          var ok = true;
          if (sportSel.value !== 'all' && m.getAttribute('data-sport') !== sportSel.value) ok = false;
          if (ok && leagueSel.value !== 'all' && m.getAttribute('data-league') !== leagueSel.value) ok = false;
          m.hidden = !ok;
        }});
      }}
      sportSel.addEventListener('change', function () {{ rebuildLeagues(); apply(); }});
      leagueSel.addEventListener('change', apply);
      rebuildLeagues();
    }})();
  </script>
</body>
</html>
"""


def main():
    now = datetime.now(timezone.utc)
    yesterday = now - timedelta(days=1)

    today_matches, yday_matches = [], []

    print("Fetching rugby fixtures/results...")
    today_matches += fetch_rugby(now)
    yday_matches += fetch_rugby(yesterday)

    if FOOTBALL_DATA_TOKEN:
        print("Fetching football fixtures/results...")
        today_matches += fetch_football(now)
        yday_matches += fetch_football(yesterday)
        note = ""
    else:
        note = ("Football fixtures & results need a free football-data.org "
                "token adding as the FOOTBALL_DATA_TOKEN repo secret. Rugby "
                "doesn't need one, so rugby fixtures already show below "
                "when there are any scheduled.")

    page = render(today_matches, yday_matches, note)
    with open("fixtures.html", "w", encoding="utf-8") as fh:
        fh.write(page)
    print("Wrote fixtures.html")


if __name__ == "__main__":
    main()
