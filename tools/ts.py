#!/usr/bin/env python3
"""Compact driver for Tech Summit 2026. Renders only what a player needs to decide."""
import json, os, sys, textwrap
sys.path.insert(0, __file__.rsplit("/", 1)[0])
from ts_api import post, auth, login  # noqa: E402

W = 110


def wrap(t, indent="    "):
    return "\n".join(textwrap.fill(line, W, initial_indent=indent, subsequent_indent=indent) or indent
                     for line in str(t).split("\n"))


def render_hud(h, cur=None):
    if not h:
        return
    th = {t["id"]: t for t in h.get("themes", [])}
    c = th.get(cur, {})
    print(f"[HUD] turn {h.get('turn')}/{h.get('turns_total')}  total_score={h.get('total_score')}  "
          f"signed={h.get('passed')}")
    if c:
        print(f"[THEME] {c.get('name')} ({cur}) state={c.get('state')} score={c.get('score')}")
    f = h.get("flow") or {}
    if f:
        g = f.get("goal") or {}
        print(f"[FLOW] score={f.get('score')} goal={json.dumps(g, ensure_ascii=False)} "
              f"affinity={json.dumps(f.get('affinity'), ensure_ascii=False)}")
    elif h.get("affinity"):
        print(f"[AFFINITY] {json.dumps(h['affinity'], ensure_ascii=False)}")


def render(r):
    if r.get("error"):
        print("[ERROR]", r["error"])
    for a in r.get("acts", []):
        k = a.get("act")
        if k == "say":
            who = a.get("speaker") or a.get("who") or "旁白"
            print(f"\n<{who}>")
            print(wrap(a.get("text", "")))
            # materials ride along on `say` acts and unlock only at this node — never drop them
            for m in a.get("materials") or []:
                print(f"    [MATERIAL] key={m.get('key')}  name={m.get('name')}")
        elif k == "prompt":
            print(f"\n[PROMPT] {a.get('text','')}")
            for i, o in enumerate(a.get("options") or a.get("choices") or []):
                print(f"   [{i}] {o if isinstance(o,str) else o.get('text') or o.get('label')}")
        elif k == "feedback":
            print(f"\n[FEEDBACK score={a.get('score')}] {a.get('text','')}")
            if a.get("evidence") or a.get("key"):
                print("   evidence:", a.get("evidence") or a.get("key"))
        elif k == "meet":
            print("\n[MEET] choose attendees:")
            for c in a.get("candidates") or a.get("npcs") or []:
                print("   ", json.dumps(c, ensure_ascii=False) if not isinstance(c, str) else c)
        elif k in ("notice", "gate", "end", "visit_end"):
            print(f"\n[{k.upper()}] {json.dumps({x: y for x, y in a.items() if x != 'act'}, ensure_ascii=False)}")
        elif k in ("scene", "sprite"):
            pass
        else:
            print(f"\n[{k}] {json.dumps(a, ensure_ascii=False)[:600]}")

    p = r.get("pending") or {}
    if p:
        print(f"\n[PENDING] kind={p.get('kind')} node={p.get('node')} expect={p.get('expect')} "
              f"speaker={p.get('speaker')} round={p.get('round')}/{p.get('max_rounds')} "
              f"upload={p.get('upload')} {p.get('upload_kind') if p.get('upload') else ''}")
        if p.get("upload_hint"):
            print(wrap("hint: " + p["upload_hint"]))
        for k2 in ("candidates", "options", "materials", "brief", "task", "spec"):
            if p.get(k2):
                print(f"  {k2}: {json.dumps(p[k2], ensure_ascii=False)[:2000]}")
        for h in (p.get("history") or [])[-6:]:
            print(f"  · {h.get('kind') or h.get('role')}: {str(h.get('text'))[:300]}")
    print(f"\n[EXPECT] {r.get('expect')}")
    render_hud(r.get("hud"), r.get("current") or (r.get("hud") or {}).get("current"))


def upload(path):
    """POST /upload → PUT the bytes to the presigned URL → return file_info for /game/play."""
    import urllib.request
    name = os.path.basename(path)
    r = auth("/upload", {"filename": name})
    if not r.get("upload_url"):
        return None, r
    data = open(path, "rb").read()
    req = urllib.request.Request(r["upload_url"], data=data, method="PUT",
                                 headers={"Content-Type": "application/octet-stream"})
    with urllib.request.urlopen(req, timeout=180) as resp:
        resp.read()
    return {"key": r["key"], "name": name, "size": len(data)}, r


def submit(a):
    """submit <file> [text-file] — upload a deliverable, optionally with an accompanying message."""
    fi, raw = upload(a[0])
    if not fi:
        return {"error": f"upload failed: {json.dumps(raw, ensure_ascii=False)[:300]}"}
    text = open(a[1]).read().strip() if len(a) > 1 else ""
    print(f"[UPLOADED] {fi['name']} ({fi['size']} bytes) key={fi['key']}")
    return auth("/game/play", {"action": {"type": "text", "text": text}, "file_info": fi})


CMDS = {
    "status":  lambda a: auth("/game/status"),
    "submit":  submit,
    "poll":    lambda a: auth("/game/poll"),
    "visit":   lambda a: auth("/game/action", {"theme": a[0], **({"npcs": a[1].split(",")} if len(a) > 1 else {})}),
    "advance": lambda a: auth("/game/play", {}),
    "choose":  lambda a: auth("/game/play", {"action": {"type": "choice", "index": int(a[0])}}),
    "say":     lambda a: auth("/game/play", {"action": {"type": "text", "text": a[0]}}),
    "meet":    lambda a: auth("/game/play", {"action": {"type": "meet", "npcs": a[0].split(",")}}),
    "leave":   lambda a: auth("/game/leave"),
    "material": lambda a: auth("/game/material", {"key": a[0]}),
    "board":   lambda a: auth("/leaderboard/api"),
}

#: commands that mutate game state — these require holding the shared game lock
WRITE_CMDS = {"visit", "advance", "choose", "say", "meet", "leave", "submit"}


def check_lock(cmd):
    """Refuse a state-mutating call unless this agent holds the lock; refresh heartbeat if it does."""
    if cmd not in WRITE_CMDS or os.environ.get("TS_NO_LOCK"):
        return
    import subprocess
    agent = os.environ.get("TS_AGENT", "")
    lockpy = os.path.join(os.path.dirname(os.path.abspath(__file__)), "gamelock.py")
    if not agent:
        print("[LOCK] TS_AGENT 未设置 —— 写操作必须声明自己是哪个 agent。"
              "  export TS_AGENT=<你的代号>", file=sys.stderr)
        sys.exit(3)
    p = subprocess.run([sys.executable, lockpy, "heartbeat", agent], capture_output=True, text=True)
    if p.returncode != 0:
        print(f"[LOCK] {agent} 未持有游戏锁，拒绝执行 `{cmd}`。\n{p.stdout.strip()}\n"
              f"→ python3 tools/gamelock.py acquire {agent} --purpose '...'\n"
              f"→ 拿不到就去准备材料（docs/RULES.md §12），别空等。", file=sys.stderr)
        sys.exit(3)


if __name__ == "__main__":
    cmd, args = sys.argv[1], sys.argv[2:]
    if cmd == "sayfile":
        args = [open(args[0]).read().strip()]
        cmd = "say"
    check_lock(cmd)
    r = CMDS[cmd](args)
    render(r)
    with open("/tmp/ts_last.json", "w") as f:
        json.dump(r, f, ensure_ascii=False, indent=2)
