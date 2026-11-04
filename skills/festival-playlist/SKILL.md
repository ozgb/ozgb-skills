---
name: festival-playlist
description: Build a Spotify playlist from a festival line-up, given the festival's line-up page URL or a poster image. Use when the user wants a playlist, mix or "warm-up" for a festival, gig weekend or multi-artist bill, or invokes "festival-playlist" by name.
---

# Festival playlist

Turn a line-up into one Spotify playlist: N tracks per artist, grouped by day, artists
kept together. All Spotify calls go through `scripts/spotify_playlist.py` (run it with
`uv run`, which installs its dependencies). Paths below are relative to this skill's directory.

## Setup (first run only)

Any command fails with `Not logged in` until the user connects a Spotify developer app.
Run `uv run scripts/spotify_playlist.py auth` in the background: it serves a page at
`http://127.0.0.1:8888/` and exits once login completes. Send the user that link; the page
walks them through creating the app (owner needs Premium, redirect URI
`http://127.0.0.1:8888/callback`) and pasting its Client ID. The token and client ID are saved
in `~/.cache/festival-playlist/`, so this happens once.

## Quota

Dev-mode apps get roughly a thousand or two API calls per day; past that, Spotify bans an
endpoint for ~24h and the script exits with `Rate-limited by Spotify for N min`. All GETs are
cached for a week, so re-running `match` or going from dry run to real build is free.
Spend quota deliberately:

- Run one command at a time, never two in parallel.
- Investigate a single artist with a one-off query, not by re-running `match` on the line-up.
- Each run prints its API call count; an 80-act line-up costs ~150 for `match` and ~150 for `build`.

## 1. Extract the line-up

Write `lineup.json` in a scratch directory:

```json
{"festival": "Field Day", "year": 2026,
 "days": [{"name": "Saturday", "artists": ["Headliner", "Second", "Small Print"]}]}
```

- **URL:** fetch the line-up page. If it is JS-rendered or only an image, search for the
  festival's Clashfinder page or a news article that lists the line-up as text.
- **Poster:** read every tier, including the smallest print. Zoom or crop if the tool
  allows; small print is where misreadings happen.
- One entry per Spotify artist:
  - `A b2b B` and `A x B` become two entries.
  - Drop set qualifiers: `(DJ set)`, `(live)`, `presents …`, `- Special Guest`.
  - Skip non-artists: "+ many more", hosts, talks, comedy, "TBA".
- List artists in poster order within each day. No day split given → one day named `Line-up`.
- **Completion:** every name on the line-up is in the file or was dropped for a stated
  reason. Show the user the per-day count and the dropped names before continuing.

## 2. Match artists

```bash
uv run scripts/spotify_playlist.py match lineup.json   # writes matches.json beside it
```

Each artist gets a status, and it prints the ones that need attention:

- `matched`: exactly one artist with that name. Trust it.
- `ambiguous`: several profiles share the name (often duplicates of one act), or the only
  match differs by "The" (`Comfort` vs `The Comfort`). `id` defaults to the candidate with
  the most releases. Dev mode returns no genres or popularity, so judge by each candidate's
  `releases` count and `latest` titles and years: the act on a current festival bill usually
  has recent releases. Edit `id` and `spotify_name` in `matches.json`. Can't tell → ask the
  user, with the Spotify URL of each candidate, or set `id` null to skip it.
- `missing`: no exact name match (case, spacing, punctuation, "The" and `(UK)`-style
  suffixes are already ignored). Try an alias, or the act behind a project name
  (`Acid Brass` is credited to the Williams Fairey Band). Set `id`/`spotify_name` by hand.
  DJs and one-off collaborations are often not on Spotify; leave `id` null and the build skips them.

**Completion:** no `ambiguous` entry is unreviewed, and every remaining `missing` is one
you tried to fix.

## 3. Build

Ask the user for the tracks per artist (default 3) and the playlist name if they haven't
said. Then dry-run:

```bash
uv run scripts/spotify_playlist.py build matches.json -n 3 --dry-run
```

Show the user the totals plus the `Skipped` and `Fewer than N tracks` lines, and spot-check
the tracklist for wrong-artist picks: a `spotify_name` that differs from the poster
(`The Dials` for `DIALS`), or titles out of keeping with the bill. Fix `matches.json` and repeat until it looks right,
then run without `--dry-run`. Flags: `--name`, `--description`, `--public` (default private).

`POST /me/playlists` can return a 502 that persists for days. Retry it once at most:
a 502 can still create the playlist, and each retry risks a duplicate. Fallback: every
build writes `tracks.txt` beside `matches.json`, one track link per line. The user creates
the playlist in the Spotify desktop app, copies the file's contents, and pastes into it.

Reply with the playlist link (or the `tracks.txt` path), total track count, and every
artist left out and why.

## Limits

- Spotify removed the artist top-tracks endpoint and the popularity fields for
  developer-mode apps in Feb 2026. The script takes each artist's first N distinct tracks
  from search results ranked by relevance. That usually puts the hits first but not always,
  so say so if the user asks why a favourite is missing.
- Developer-mode apps allow 5 users, and the app owner must have Premium.
- `/artists/{id}/albums` has a much tighter quota than search; the script avoids it.
