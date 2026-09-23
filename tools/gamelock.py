#!/usr/bin/env python3
"""Cooperative lock for the single shared Tech Summit game slot.

The platform allows exactly one player session to be *inside* a company at a time, and
concurrent /game/play calls collide with "操作太快，另一处请求正在处理". So every agent that
wants to drive the game must hold this lock first. Read-only calls (status/poll) never need it.

Atomicity: O_EXCL file create — the kernel guarantees only one winner.
Fairness:  FIFO queue file, so a waiting agent cannot be starved by a fast re-acquirer.
Liveness:  TTL + heartbeat — a crashed holder's lock expires and can be taken over.

    python3 tools/gamelock.py acquire  Kestrel-7 --purpose "ME Live roundtable" --ttl 1200
    python3 tools/gamelock.py heartbeat Kestrel-7
    python3 tools/gamelock.py release  Kestrel-7
    python3 tools/gamelock.py status
    python3 tools/gamelock.py queue    Petrel-9          # join the line without blocking
    python3 tools/gamelock.py wait     Petrel-9 --timeout 600
"""
import argparse, json, os, sys, time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
LOCK = os.path.join(ROOT, ".game.lock")
QUEUE = os.path.join(ROOT, ".game.queue")
LOG = os.path.join(ROOT, ".game.lock.log")
DEFAULT_TTL = 1200  # 20 min — long enough for a multi-round negotiation node
QUEUE_TTL = 180     # a queue entry not refreshed within this window forfeits its place


def now():
    return time.time()


def log(msg):
    with open(LOG, "a") as f:
        f.write(f"{time.strftime('%Y-%m-%d %H:%M:%S')} {msg}\n")


def read_lock():
    try:
        with open(LOCK) as f:
            return json.load(f)
    except Exception:
        return None


def expired(rec):
    return rec is not None and now() - rec.get("heartbeat", rec.get("acquired_at", 0)) > rec.get("ttl", DEFAULT_TTL)


def read_queue_raw():
    """[(name, last_refreshed_epoch)] in FIFO order, as stored."""
    out = []
    try:
        with open(QUEUE) as f:
            for l in f.read().splitlines():
                if not l.strip():
                    continue
                parts = l.split("\t")
                try:
                    out.append((parts[0], float(parts[1])))
                except (IndexError, ValueError):
                    out.append((parts[0], 0.0))
    except Exception:
        return []
    return out


def read_queue():
    """Live queue only: entries whose holder stopped refreshing forfeit their place.

    Without this, an agent that queued once and then wandered off pins the head of the
    line forever and starves everyone behind it even while the lock sits free.
    """
    t = now()
    return [n for n, ts in read_queue_raw() if t - ts <= QUEUE_TTL]


def write_queue(entries):
    """entries: list of (name, ts) or bare names (bare names get a fresh timestamp)."""
    tmp = QUEUE + ".tmp"
    with open(tmp, "w") as f:
        for e in entries:
            n, ts = e if isinstance(e, tuple) else (e, now())
            f.write(f"{n}\t{int(ts)}\n")
    os.replace(tmp, QUEUE)


def enqueue(holder):
    """Append if absent, and always refresh this holder's timestamp (proof of still waiting)."""
    t = now()
    q = [(n, ts) for n, ts in read_queue_raw() if t - ts <= QUEUE_TTL and n != holder]
    prior = [ts for n, ts in read_queue_raw() if n == holder]
    q.append((holder, t))
    if prior:  # keep original FIFO position, just refresh the timestamp
        q.sort(key=lambda e: prior[0] if e[0] == holder else e[1])
    write_queue(q)
    return [n for n, _ in q].index(holder)


def dequeue(holder):
    t = now()
    write_queue([(n, ts) for n, ts in read_queue_raw() if n != holder and t - ts <= QUEUE_TTL])


def try_acquire(holder, purpose, ttl):
    rec = read_lock()
    if rec is not None:
        if rec["holder"] == holder:  # re-entrant: refresh
            rec.update(heartbeat=now(), purpose=purpose or rec.get("purpose"), ttl=ttl)
            with open(LOCK, "w") as f:
                json.dump(rec, f)
            dequeue(holder)
            return True, rec, "reacquired"
        if expired(rec):
            log(f"STEAL by {holder}: {rec['holder']} lock expired "
                f"({int(now() - rec.get('heartbeat', 0))}s since heartbeat)")
            os.unlink(LOCK)
        else:
            return False, rec, "held"

    # FIFO: only the head of the queue may take a free lock
    q = read_queue()
    if q and q[0] != holder:
        enqueue(holder)
        return False, read_lock(), f"queued behind {q[0]}"

    rec = {"holder": holder, "pid": os.getpid(), "purpose": purpose or "",
           "acquired_at": now(), "heartbeat": now(), "ttl": ttl}
    try:
        fd = os.open(LOCK, os.O_CREAT | os.O_EXCL | os.O_WRONLY, 0o644)
    except FileExistsError:
        return False, read_lock(), "raced"
    with os.fdopen(fd, "w") as f:
        json.dump(rec, f)
    dequeue(holder)
    log(f"ACQUIRE {holder} :: {purpose}")
    return True, rec, "acquired"


def fmt(rec):
    if not rec:
        return "free"
    age = int(now() - rec["acquired_at"])
    since_hb = int(now() - rec.get("heartbeat", rec["acquired_at"]))
    return (f"held by {rec['holder']} for {age}s (heartbeat {since_hb}s ago, ttl {rec['ttl']}s"
            f"{', EXPIRED' if expired(rec) else ''}) :: {rec.get('purpose', '')}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["acquire", "release", "status", "heartbeat", "queue", "wait"])
    ap.add_argument("holder", nargs="?", default=os.environ.get("TS_AGENT", ""))
    ap.add_argument("--purpose", default="")
    ap.add_argument("--ttl", type=int, default=DEFAULT_TTL)
    ap.add_argument("--timeout", type=int, default=600)
    a = ap.parse_args()

    if a.cmd == "status":
        print(fmt(read_lock()))
        t = now()
        rows = read_queue_raw()
        live = [f"{n}({int(t - ts)}s)" for n, ts in rows if t - ts <= QUEUE_TTL]
        stale = [f"{n}({int(t - ts)}s, STALE)" for n, ts in rows if t - ts > QUEUE_TTL]
        print("queue:", " -> ".join(live) if live else "(empty)")
        if stale:
            print("forfeited:", ", ".join(stale))
        return 0

    if not a.holder:
        print("ERROR: holder required (or set TS_AGENT)")
        return 2

    if a.cmd == "acquire":
        ok, rec, why = try_acquire(a.holder, a.purpose, a.ttl)
        print(("LOCKED " if ok else "BUSY ") + why + " | " + fmt(read_lock()))
        if not ok:
            print("queue:", " -> ".join(read_queue()) or "(empty)")
            print("→ 拿不到锁不要空等：去准备材料（见 docs/RULES.md §12），备好后再 acquire。")
        return 0 if ok else 1

    if a.cmd == "heartbeat":
        rec = read_lock()
        if not rec or rec["holder"] != a.holder:
            print("ERROR: you do not hold the lock |", fmt(rec))
            return 1
        rec["heartbeat"] = now()
        with open(LOCK, "w") as f:
            json.dump(rec, f)
        print("OK", fmt(rec))
        return 0

    if a.cmd == "release":
        rec = read_lock()
        if not rec:
            print("already free")
            return 0
        if rec["holder"] != a.holder:
            print("ERROR: held by", rec["holder"], "- refusing to release someone else's lock")
            return 1
        os.unlink(LOCK)
        log(f"RELEASE {a.holder} after {int(now() - rec['acquired_at'])}s")
        q = read_queue()
        print(f"RELEASED. next in queue: {q[0] if q else '(nobody)'}")
        return 0

    if a.cmd == "queue":
        pos = enqueue(a.holder)
        print(f"queued at position {pos} |", fmt(read_lock()))
        print(f"note: a queue place must be refreshed at least every {QUEUE_TTL}s "
              f"(`queue` again, or use `wait`), otherwise it is forfeited.")
        return 0

    if a.cmd == "wait":
        enqueue(a.holder)
        deadline = now() + a.timeout
        while now() < deadline:
            ok, rec, why = try_acquire(a.holder, a.purpose, a.ttl)
            if ok:
                print("LOCKED", why)
                return 0
            time.sleep(10)
        print("TIMEOUT still", fmt(read_lock()))
        return 1


if __name__ == "__main__":
    sys.exit(main())
