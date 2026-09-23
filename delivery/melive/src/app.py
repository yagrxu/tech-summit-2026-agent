# -*- coding: utf-8 -*-
"""ME Live host-chatbot POC — Lambda Function URL handler.

Routes:
  POST /chat     -> Nadia's reply (Bearer required)
  GET  /metrics  -> real operational metrics (Bearer required)

State lives in DynamoDB so metrics survive cold starts and concurrent containers.
"""
import json, os, re, time, decimal
from datetime import datetime, timezone

import boto3
from botocore.config import Config

import persona

REGION = os.environ.get("AWS_REGION", "ap-southeast-1")
MODEL_ID = os.environ.get("MODEL_ID", "global.anthropic.claude-haiku-4-5-20251001-v1:0")
TABLE = os.environ["TABLE_NAME"]
TOKEN = os.environ["API_TOKEN"]
MAX_TURNS = 24          # messages kept per session (12 rounds)
LAT_SAMPLES = 400       # rolling window for percentiles

_brt = boto3.client("bedrock-runtime", region_name=REGION,
                    config=Config(read_timeout=25, connect_timeout=5, retries={"max_attempts": 2}))
_ddb = boto3.resource("dynamodb", region_name=REGION).Table(TABLE)
SYSTEM = persona.system_prompt()

# --- hard-stop detection for V1 (minor). Deterministic so wording never changes the outcome. ---
_MINOR = [
    re.compile(r"\b(?:i\s*(?:a|')?m|im|i\s+am|me)\s*(?:only|just|like)?\s*(\d{1,2})\b(?!\s*(?:th|st|nd|rd)?\s*(?:hour|min|am|pm|dollar))", re.I),
    re.compile(r"\b(\d{1,2})\s*(?:yo|y/o|yrs?\s*old|years?\s*old)\b", re.I),
    re.compile(r"\bturning\s*(\d{1,2})\b", re.I),
]
_MINOR_WORDS = re.compile(
    r"\b(?:i\s*(?:a|')?m|im|i\s+am)\s+(?:a\s+)?(?:minor|underage|under\s*-?\s*age|kid|child|teen|teenager|"
    r"high\s*school(?:er)?|middle\s*school(?:er)?|schoolboy|schoolgirl)\b|\bunder\s*18\b|\bnot\s*18\s*yet\b|"
    r"\bstill\s+in\s+(?:high\s*)?school\b|"
    r"\b(?:i\s*(?:a|')?m|im|i\s+am)\s+in\s+(?:high|middle|elementary|primary|secondary)\s*school\b", re.I)

MINOR_REPLY = "i cant talk to u if ur under 18, sorry — this app is 18+ only"


def is_minor(text: str) -> bool:
    if _MINOR_WORDS.search(text):
        return True
    for rx in _MINOR:
        for m in rx.finditer(text):
            try:
                age = int(m.group(1))
            except (TypeError, ValueError):
                continue
            if 0 < age < 18:
                return True
    return False


# ------------------------------- metrics ---------------------------------
def bump(field, n=1):
    try:
        _ddb.update_item(Key={"pk": "metrics", "sk": "counters"},
                         UpdateExpression=f"ADD #f :n", ExpressionAttributeNames={"#f": field},
                         ExpressionAttributeValues={":n": decimal.Decimal(n)})
    except Exception:
        pass


def record_latency(ms):
    try:
        _ddb.update_item(
            Key={"pk": "metrics", "sk": "latency"},
            UpdateExpression="SET samples = list_append(if_not_exists(samples, :e), :s)",
            ExpressionAttributeValues={":s": [decimal.Decimal(int(ms))], ":e": []})
    except Exception:
        pass


def note_session(session_id):
    """Count distinct sessions exactly once, without a scan."""
    try:
        _ddb.put_item(Item={"pk": "seen", "sk": f"s#{session_id}", "at": int(time.time())},
                      ConditionExpression="attribute_not_exists(pk) AND attribute_not_exists(sk)")
        bump("sessions")
    except Exception:
        pass  # already seen


def pct(xs, p):
    if not xs:
        return 0.0
    xs = sorted(xs)
    if len(xs) == 1:
        return float(xs[0])
    k = (len(xs) - 1) * (p / 100.0)
    lo, hi = int(k), min(int(k) + 1, len(xs) - 1)
    return round(float(xs[lo]) + (float(xs[hi]) - float(xs[lo])) * (k - lo), 1)


def read_metrics():
    c = (_ddb.get_item(Key={"pk": "metrics", "sk": "counters"}).get("Item") or {})
    l = (_ddb.get_item(Key={"pk": "metrics", "sk": "latency"}).get("Item") or {})
    s = [int(x) for x in (l.get("samples") or [])][-LAT_SAMPLES:]
    return {
        "invocations": int(c.get("invocations", 0)),
        "sessions": int(c.get("sessions", 0)),
        "latency_ms": {"p50": pct(s, 50), "p95": pct(s, 95)},
        "system_errors": int(c.get("system_errors", 0)),
        "user_errors": int(c.get("user_errors", 0)),
        "throttles": int(c.get("throttles", 0)),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }


# ------------------------------- memory ----------------------------------
def load_session(session_id):
    it = _ddb.get_item(Key={"pk": f"sess#{session_id}", "sk": "log"}).get("Item") or {}
    return it.get("owner"), list(it.get("msgs") or [])


def save_session(session_id, owner, msgs):
    _ddb.put_item(Item={"pk": f"sess#{session_id}", "sk": "log", "owner": owner,
                        "msgs": msgs[-MAX_TURNS:], "at": int(time.time()),
                        "ttl": int(time.time()) + 7 * 24 * 3600})


# ------------------------------- model -----------------------------------
def generate(history, user_msg):
    msgs = [{"role": m["role"], "content": [{"type": "text", "text": m["text"]}]} for m in history]
    msgs.append({"role": "user", "content": [{"type": "text", "text": user_msg}]})
    body = {"anthropic_version": "bedrock-2023-05-31", "max_tokens": 200, "temperature": 0.7,
            "system": SYSTEM, "messages": msgs}
    r = _brt.invoke_model(modelId=MODEL_ID, body=json.dumps(body))
    data = json.loads(r["body"].read())
    out = "".join(b.get("text", "") for b in data.get("content", []) if b.get("type") == "text")
    return out.strip().strip('"').split("\n")[0].strip()


FALLBACK = "sorry — phone acting up. say that again?"


# ------------------------------- routing ---------------------------------
def resp(code, obj):
    return {"statusCode": code, "headers": {"Content-Type": "application/json"},
            "body": json.dumps(obj, ensure_ascii=False)}


def authed(event):
    h = {k.lower(): v for k, v in (event.get("headers") or {}).items()}
    a = h.get("authorization", "")
    return a.startswith("Bearer ") and a[7:].strip() == TOKEN


def handler(event, context):
    path = (event.get("rawPath") or event.get("path") or "/").rstrip("/") or "/"
    method = ((event.get("requestContext") or {}).get("http") or {}).get("method", "GET").upper()

    if not authed(event):
        bump("user_errors")
        return resp(401, {"error": "unauthorized"})

    if path.endswith("/metrics") and method == "GET":
        try:
            return resp(200, read_metrics())
        except Exception as e:
            bump("system_errors")
            return resp(500, {"error": f"metrics unavailable: {e}"})

    if path.endswith("/chat") and method == "POST":
        t0 = time.time()
        try:
            payload = json.loads(event.get("body") or "{}")
        except Exception:
            bump("user_errors")
            return resp(400, {"error": "invalid json"})

        msg = (payload.get("message") or "").strip()
        sid = (payload.get("session_id") or "").strip()
        uid = (payload.get("user_id") or "").strip()
        if not msg or not sid:
            bump("user_errors")
            return resp(400, {"error": "message and session_id are required"})

        try:
            owner, history = load_session(sid)
            # Isolation: a session belongs to one user. Different user_id => fresh context.
            if owner and uid and owner != uid:
                history = []
                owner = uid
            owner = owner or uid

            if is_minor(msg):
                reply = MINOR_REPLY
                history = []          # hard stop: drop context, nothing carries on
            else:
                try:
                    reply = generate(history, msg)
                except Exception as e:
                    if "Throttl" in type(e).__name__ or "Throttl" in str(e):
                        bump("throttles")
                    bump("system_errors")
                    reply = ""
                if not reply:
                    try:
                        reply = generate(history, msg)
                    except Exception:
                        reply = ""
                if not reply:
                    reply = FALLBACK
                history = history + [{"role": "user", "text": msg},
                                     {"role": "assistant", "text": reply}]

            save_session(sid, owner or "unknown", history)
            note_session(sid)
            bump("invocations")
            record_latency((time.time() - t0) * 1000)
            return resp(200, {"reply": reply, "session_id": sid})
        except Exception as e:
            bump("system_errors")
            bump("invocations")
            record_latency((time.time() - t0) * 1000)
            return resp(200, {"reply": FALLBACK, "session_id": sid, "degraded": str(e)[:200]})

    bump("user_errors")
    return resp(404, {"error": "not found"})
