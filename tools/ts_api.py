#!/usr/bin/env python3
"""Tech Summit 2026 platform client (reverse-engineered from the SPA bundle)."""
import hashlib, json, os, sys, urllib.request

BASE = os.environ.get("TS_BASE", "https://d25uq4rhmmcney.cloudfront.net") + "/api"
APP_KEY = os.environ.get("TS_APP_KEY", "811f5520bb0d735efa1d980a21fea77f30dd7277721c2d63")
TOKEN_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".ts_token")


def post(path, payload):
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {APP_KEY}",
        "x-amz-content-sha256": hashlib.sha256(body).hexdigest(),
    }
    req = urllib.request.Request(BASE + path, data=body, headers=headers, method="POST")
    try:
        with urllib.request.urlopen(req, timeout=120) as r:
            return json.loads(r.read().decode())
    except urllib.error.HTTPError as e:
        raw = e.read().decode()
        try:
            return json.loads(raw)
        except Exception:
            return {"error": f"HTTP {e.code}: {raw[:400]}"}


def token():
    with open(TOKEN_FILE) as f:
        return f.read().strip()


def auth(path, payload=None):
    return post(path, {**(payload or {}), "token": token()})


def login(u, p):
    r = post("/auth/login", {"username": u, "password": p})
    if r.get("token"):
        with open(TOKEN_FILE, "w") as f:
            f.write(r["token"])
    return r


CMDS = {
    "login":   lambda a: login(a[0], a[1]),
    "gate":    lambda a: post("/game/gate", {}),
    "status":  lambda a: auth("/game/status"),
    "welcome": lambda a: auth("/game/welcome"),
    "visit":   lambda a: auth("/game/action", {"theme": a[0], **({"npcs": a[1].split(",")} if len(a) > 1 else {})}),
    "advance": lambda a: auth("/game/play", {}),
    "choose":  lambda a: auth("/game/play", {"action": {"type": "choice", "index": int(a[0])}}),
    "answer":  lambda a: auth("/game/play", {"action": {"type": "text", "text": a[0]}}),
    "meet":    lambda a: auth("/game/play", {"action": {"type": "meet", "npcs": a[0].split(",")}}),
    "poll":    lambda a: auth("/game/poll"),
    "material": lambda a: auth("/game/material", {"key": a[0]}),
    "leave":   lambda a: auth("/game/leave"),
    "board":   lambda a: auth("/leaderboard/api"),
    "history": lambda a: auth("/myhistory/api", {"days": int(a[0]) if a else 7}),
}

if __name__ == "__main__":
    cmd, args = sys.argv[1], sys.argv[2:]
    if cmd == "raw":
        out = auth(args[0], json.loads(args[1]) if len(args) > 1 else {})
    else:
        out = CMDS[cmd](args)
    print(json.dumps(out, ensure_ascii=False, indent=2))
