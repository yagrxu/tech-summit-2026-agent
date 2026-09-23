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


def read_queue():
    try:
        with open(QUEUE) as f:
            return [l.split("\t")[0] for l in f.read().splitlines() if l.strip()]
    except Exception:
        return []


def write_queue(names):
    tmp = QUEUE + ".tmp"
    with open(tmp, "w") as f:
        for n in names:
            f.write(f"{n}\t{int(now())}\n")
    os.replace(tmp, QUEUE)


def enqueue(holder):
    q = read_queue()
    if holder not in q:
        q.append(holder)
        write_queue(q)
    return q.index(holder)


def dequeue(holder):
    q = [n for n in read_queue() if n != holder]
    write_queue(q)


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
        q = read_queue()
        print("queue:", " -> ".join(q) if q else "(empty)")
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
