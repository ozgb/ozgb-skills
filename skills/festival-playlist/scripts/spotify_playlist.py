# /// script
# requires-python = ">=3.11"
# dependencies = ["requests>=2.31"]
# ///
"""Match a festival line-up to Spotify artists and build a playlist from it.

    auth                           log in once via a local page
    match LINEUP.json              write matches.json next to it for review
    build MATCHES.json [--dry-run] create the playlist
"""

import argparse
import base64
import hashlib
import html
import json
import os
import re
import secrets
import sys
import time
import unicodedata
import urllib.parse
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import requests

API = "https://api.spotify.com/v1"
ACCOUNTS = "https://accounts.spotify.com"
SCOPES = "playlist-modify-private playlist-modify-public"
# Spotify rejects "localhost" redirect URIs; it must be the loopback IP.
HOST, PORT = "127.0.0.1", 8888
REDIRECT = f"http://{HOST}:{PORT}/callback"
CACHE_DIR = Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")) / "festival-playlist"
TOKEN = CACHE_DIR / "token.json"
# Dev-mode quota is roughly a thousand or two calls/day before a ~24h ban, so every GET is
# cached and re-runs (match tweaks, dry run -> real build) cost nothing.
HTTP_CACHE = CACHE_DIR / "http"
CACHE_TTL = 7 * 86400
# Dev-mode search caps limit at 10.
PAGE = 10
VERSION_TAGS = re.compile(
    r"\s*[-(\[].*\b(remaster(ed)?|live|edit|version|re-?mix|mix|extended|slowed|sped|rework|dub|vip|mono|stereo|demo|acoustic|instrumental|feat\.?|ft\.?|with)\b.*$",
    re.I,
)


def save_token(tok: dict, client_id: str) -> None:
    TOKEN.parent.mkdir(parents=True, exist_ok=True)
    TOKEN.write_text(json.dumps({**tok, "client_id": client_id, "expires_at": time.time() + tok["expires_in"] - 60}))
    TOKEN.chmod(0o600)


def access_token() -> str:
    if not TOKEN.exists():
        sys.exit("Not logged in. Run the `auth` command first.")
    tok = json.loads(TOKEN.read_text())
    if time.time() < tok["expires_at"]:
        return tok["access_token"]
    r = requests.post(f"{ACCOUNTS}/api/token", timeout=30, data={
        "grant_type": "refresh_token", "refresh_token": tok["refresh_token"], "client_id": tok["client_id"],
    })
    if r.status_code != 200:
        sys.exit(f"Token refresh failed ({r.status_code}: {r.text[:200]}). Run `auth` again.")
    new = r.json()
    # Spotify only sometimes rotates the refresh token.
    new.setdefault("refresh_token", tok["refresh_token"])
    save_token(new, tok["client_id"])
    return new["access_token"]


PAGE_CSS = "body{font:16px system-ui;max-width:34em;margin:3em auto;padding:0 16px}input{width:100%;padding:.5em;font:inherit}button{margin-top:1em;padding:.6em 1.2em;font:inherit}code{background:#8882;padding:0 .3em}"


def page(body: str) -> bytes:
    return f"<!doctype html><meta charset=utf-8><title>Festival playlist login</title><style>{PAGE_CSS}</style>{body}".encode()


def cmd_auth(_: argparse.Namespace) -> None:
    saved = json.loads(TOKEN.read_text()).get("client_id", "") if TOKEN.exists() else ""
    state = {"verifier": None, "client_id": None, "csrf": secrets.token_urlsafe(16), "done": False}

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def reply(self, code: int, body: bytes = b"", location: str | None = None):
            self.send_response(code)
            if location:
                self.send_header("Location", location)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            self.wfile.write(body)

        def do_GET(self):
            url = urllib.parse.urlparse(self.path)
            q = dict(urllib.parse.parse_qsl(url.query))
            if url.path == "/":
                self.reply(200, page(f"""
<h1>Connect Spotify</h1>
<ol><li>Create an app at <a href="https://developer.spotify.com/dashboard" target=_blank>developer.spotify.com/dashboard</a>
(owner needs Premium), tick <b>Web API</b>, and add the redirect URI <code>{REDIRECT}</code>.</li>
<li>Paste its Client ID below. No secret is needed.</li></ol>
<form action=/login><input name=client_id placeholder="Client ID" value="{html.escape(saved)}" required pattern="[0-9a-fA-F]{{32}}">
<button>Connect to Spotify</button></form>"""))
            elif url.path == "/login" and q.get("client_id"):
                state["client_id"] = q["client_id"].strip()
                state["verifier"] = secrets.token_urlsafe(64)
                challenge = base64.urlsafe_b64encode(hashlib.sha256(state["verifier"].encode()).digest()).rstrip(b"=").decode()
                self.reply(302, location=f"{ACCOUNTS}/authorize?" + urllib.parse.urlencode({
                    "client_id": state["client_id"], "response_type": "code", "redirect_uri": REDIRECT,
                    "code_challenge_method": "S256", "code_challenge": challenge, "scope": SCOPES, "state": state["csrf"],
                }))
            elif url.path == "/callback":
                if q.get("state") != state["csrf"] or "code" not in q:
                    self.reply(400, page(f"<h1>Login failed</h1><p>{html.escape(q.get('error', 'bad state'))}</p><p><a href=/>Try again</a></p>"))
                    return
                r = requests.post(f"{ACCOUNTS}/api/token", timeout=30, data={
                    "grant_type": "authorization_code", "code": q["code"], "redirect_uri": REDIRECT,
                    "client_id": state["client_id"], "code_verifier": state["verifier"],
                })
                if r.status_code != 200:
                    self.reply(400, page(f"<h1>Token exchange failed</h1><pre>{html.escape(r.text[:500])}</pre><p><a href=/>Try again</a></p>"))
                    return
                save_token(r.json(), state["client_id"])
                state["done"] = True
                self.reply(200, page("<h1>Connected</h1><p>You can close this tab and return to the terminal.</p>"))
            else:
                self.reply(404, page("<p>Not found. <a href=/>Start</a></p>"))

    server = HTTPServer((HOST, PORT), Handler)
    print(f"Open http://{HOST}:{PORT}/ to connect Spotify", flush=True)
    while not state["done"]:
        server.handle_request()
    server.server_close()
    me = Spotify().call("GET", "/me")
    print(f"Logged in as {me.get('display_name') or me['id']}. Token saved to {TOKEN}")


class Spotify:
    def __init__(self) -> None:
        self.http = requests.Session()
        self.calls = 0

    def call(self, method: str, path: str, **kw) -> dict:
        cached = None
        if method == "GET":
            key = hashlib.sha256(json.dumps([path, kw.get("params")], sort_keys=True).encode()).hexdigest()
            cached = HTTP_CACHE / f"{key}.json"
            if cached.exists() and time.time() - cached.stat().st_mtime < CACHE_TTL:
                return json.loads(cached.read_text())
        self.calls += 1
        for _ in range(5):
            r = self.http.request(method, API + path, headers={"Authorization": f"Bearer {access_token()}"}, timeout=30, **kw)
            if r.status_code == 429:
                wait = int(r.headers.get("Retry-After", "2")) + 1
                # Spotify can ask for hours; that should be the user's call, not a silent hang.
                if wait > 120:
                    sys.exit(f"Rate-limited by Spotify for {wait // 60} min. Re-run later.")
                progress(f"rate-limited, waiting {wait}s")
                time.sleep(wait)
                continue
            if r.status_code >= 400:
                sys.exit(f"{method} {path} -> {r.status_code}: {r.text[:300]}")
            body = r.json() if r.content else {}
            if cached:
                HTTP_CACHE.mkdir(parents=True, exist_ok=True)
                cached.write_text(json.dumps(body))
            return body
        sys.exit(f"{method} {path}: still rate-limited after 5 retries")

    def search(self, q: str, kind: str, pages: int = 1, start: int = 0) -> list[dict]:
        items = []
        for page in range(start, start + pages):
            res = self.call("GET", "/search", params={"q": q, "type": kind, "limit": PAGE, "offset": page * PAGE})
            batch = res[kind + "s"]["items"]
            items += [i for i in batch if i]
            if len(batch) < PAGE:
                break
        return items

    def releases(self, artist_name: str) -> list[dict]:
        # /artists/{id}/albums has a far tighter dev-mode quota than search (a 24h ban after
        # ~200 calls), so releases come from album search and are filtered by artist id.
        albums = self.search(f'artist:"{artist_name}"', "album", pages=2)
        return sorted(albums, key=lambda a: a["release_date"], reverse=True)


def progress(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def norm(name: str) -> str:
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode().casefold()
    # Spotify disambiguates namesakes with a country tag: "Ugly (UK)".
    s = re.sub(r"\s*\([a-z]{2,3}\)$", "", s.strip())
    s = re.sub(r"^the\s+", "", s.replace("&", " and "))
    # Spacing and punctuation vary between poster and profile: "BIG|BRAVE", "Big Brave".
    return re.sub(r"[^a-z0-9]", "", s)


def describe(a: dict, albums: list[dict] | None = None) -> dict:
    own = [r for r in albums or [] if any(x["id"] == a["id"] for x in r["artists"])]
    return {
        "id": a["id"],
        "name": a["name"],
        "releases": len(own),
        "latest": [f"{r['name']} ({r['release_date'][:4]})" for r in own[:3]],
        "url": a["external_urls"]["spotify"],
    }


def cmd_match(args: argparse.Namespace) -> None:
    lineup = json.loads(Path(args.lineup).read_text())
    sp = Spotify()
    out_days, counts = [], {"matched": 0, "ambiguous": 0, "missing": 0}
    total, done = sum(len(d["artists"]) for d in lineup["days"]), 0
    for day in lineup["days"]:
        entries = []
        for name in day["artists"]:
            done += 1
            # The artist: filter misses some exact names ("The Grubby Mitts"); widen until one hits.
            bare = re.sub(r"^the\s+", "", name, flags=re.I)
            for q in dict.fromkeys([f'artist:"{name}"', name, bare]):
                results = sp.search(q, "artist")
                exact = [a for a in results if norm(a["name"]) == norm(name)]
                if exact:
                    break
            literal = [a for a in exact if a["name"].casefold() == name.casefold()]
            if len(exact) == 1:
                # "Comfort" matching only "The Comfort" is as likely a namesake as the act.
                status = "matched" if literal or not re.match(r"the\s", exact[0]["name"] + name, re.I) else "ambiguous"
                cands = [describe(exact[0])]
            elif len(literal) == 1:
                status, cands = "matched", [describe(literal[0])] + [describe(a) for a in exact if a is not literal[0]]
            elif exact:
                # No popularity field in dev mode; release count separates the real act from
                # duplicate profiles and namesakes.
                albums = sp.releases(name)
                pool = literal or exact
                cands = sorted((describe(a, albums) for a in pool), key=lambda c: -c["releases"])
                best, runner = cands[0]["releases"], cands[1]["releases"]
                status = "matched" if runner <= 2 and best >= 2 * max(runner, 1) else "ambiguous"
            else:
                status, cands = "missing", [describe(a) for a in results[:3]]
            pick = cands[0] if status != "missing" else None
            counts[status] += 1
            progress(f"[{done}/{total}] {name}: {status}")
            entries.append({
                "lineup_name": name,
                "status": status,
                "id": pick["id"] if pick else None,
                "spotify_name": pick["name"] if pick else None,
                "candidates": cands[:5],
            })
        out_days.append({"name": day["name"], "artists": entries})
    out = Path(args.out) if args.out else Path(args.lineup).with_name("matches.json")
    out.write_text(json.dumps({**lineup, "days": out_days}, indent=2, ensure_ascii=False) + "\n")
    progress(f"{sp.calls} Spotify API calls")
    print(f"{out}: {counts['matched']} matched, {counts['ambiguous']} ambiguous, {counts['missing']} missing")
    for day in out_days:
        for e in day["artists"]:
            if e["status"] != "matched":
                print(f"  {e['status'].upper():9} {e['lineup_name']!r}")
                for c in e["candidates"]:
                    extra = f"  {c['releases']} releases: {'; '.join(c['latest'])}" if e["status"] == "ambiguous" else ""
                    print(f"      {c['id']}  {c['name']}{extra}")


def top_tracks(sp: Spotify, artist_id: str, artist_name: str, n: int) -> list[dict]:
    picked, seen = [], set()

    def take(tracks):
        for t in tracks:
            key = norm(VERSION_TAGS.sub("", t["name"]))
            if key not in seen and len(picked) < n:
                seen.add(key)
                picked.append(t)

    def take_search(results):
        lead = [t for t in results if t["artists"][0]["id"] == artist_id]
        take(lead + [t for t in results if t not in lead and any(a["id"] == artist_id for a in t["artists"])])

    # A plain name query surfaces far more of the artist's own tracks than the artist: filter.
    # Each step only runs while still short, to spend as little quota as possible.
    for fetch in (lambda: sp.search(artist_name, "track"),
                  lambda: sp.search(artist_name, "track", start=1),
                  lambda: sp.search(f'artist:"{artist_name}"', "track")):
        take_search(fetch())
        if len(picked) == n:
            return picked
    if len(picked) < n:
        # Names that are common words ("caroline") drown in search; fall back to recent releases.
        own = [r for r in sp.releases(artist_name) if any(a["id"] == artist_id for a in r["artists"])]
        for release in own:
            take(sp.call("GET", f"/albums/{release['id']}/tracks", params={"limit": n})["items"])
            if len(picked) == n:
                break
    return picked


def cmd_build(args: argparse.Namespace) -> None:
    plan = json.loads(Path(args.matches).read_text())
    sp = Spotify()
    uris, skipped, short = [], [], []
    total, done = sum(len(d["artists"]) for d in plan["days"]), 0
    for day in plan["days"]:
        print(f"## {day['name']}")
        for e in day["artists"]:
            done += 1
            progress(f"[{done}/{total}] {e['lineup_name']}")
            if not e.get("id"):
                skipped.append(e["lineup_name"])
                continue
            tracks = top_tracks(sp, e["id"], e["spotify_name"] or e["lineup_name"], args.tracks)
            if len(tracks) < args.tracks:
                short.append(f"{e['lineup_name']} ({len(tracks)})")
            for t in tracks:
                if t["uri"] not in uris:
                    uris.append(t["uri"])
                    print(f"  {e['spotify_name']} - {t['name']}")
    name = args.name or f"{plan['festival']} {plan.get('year', '')}".strip()
    print(f"\n{len(uris)} tracks for {name!r}")
    if skipped:
        print(f"Skipped (no Spotify id): {', '.join(skipped)}")
    if short:
        print(f"Fewer than {args.tracks} tracks: {', '.join(short)}")
    progress(f"{sp.calls} Spotify API calls")
    # Fallback when playlist creation fails: these links paste straight into a playlist in the desktop app.
    links = Path(args.matches).with_name("tracks.txt")
    links.write_text("".join(f"https://open.spotify.com/track/{u.rsplit(':', 1)[1]}\n" for u in uris))
    print(f"Track links: {links}")
    if args.dry_run:
        return
    pl = sp.call("POST", "/me/playlists", json={
        "name": name,
        "public": args.public,
        "description": args.description or f"{name} line-up, grouped by day.",
    })
    for i in range(0, len(uris), 100):
        sp.call("POST", f"/playlists/{pl['id']}/items", json={"uris": uris[i:i + 100]})
    print(f"Created: {pl['external_urls']['spotify']}")


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(required=True)
    sub.add_parser("auth", help="log in via a local page and cache a token").set_defaults(fn=cmd_auth)
    m = sub.add_parser("match", help="match line-up names to Spotify artists")
    m.add_argument("lineup")
    m.add_argument("-o", "--out", help="default: matches.json beside the line-up")
    m.set_defaults(fn=cmd_match)
    b = sub.add_parser("build", help="create the playlist from reviewed matches")
    b.add_argument("matches")
    b.add_argument("-n", "--tracks", type=int, default=3, help="tracks per artist (default 3)")
    b.add_argument("--name", help="default: '<festival> <year>'")
    b.add_argument("--description")
    b.add_argument("--public", action="store_true", help="default is private")
    b.add_argument("--dry-run", action="store_true", help="print the tracklist, create nothing")
    b.set_defaults(fn=cmd_build)
    args = p.parse_args()
    args.fn(args)


if __name__ == "__main__":
    main()
