# -*- coding: utf-8 -*-
"""维立康 Project SOAR — site-budget & CTA backend (Gate A / Gate B).

Endpoints (all require `Authorization: Bearer <token>`; metrics is business data too):
  POST /budget            SOAR payload -> six-layer budget with full traceability
  POST /amendment         baseline vs revised -> which sites/cells actually need recalculation
  POST /budget/excel      same budget as multi-sheet xlsx + finance CSV (base64)
  GET  /metrics           real operational metrics
  GET  /health            liveness (also authenticated)

Prototype scope: synthetic data only. Production target is AWS China; nothing here depends on
a region-specific service beyond Lambda/DynamoDB/API Gateway, all of which exist in cn-north-1.
"""
import base64, decimal, json, os, time
from datetime import datetime, timezone

import boto3

from engine import build_budget, amendment_impact
import outputs

TABLE = os.environ["TABLE_NAME"]
TOKEN = os.environ["API_TOKEN"]
LAT_SAMPLES = 400

_ddb = boto3.resource("dynamodb", region_name=os.environ.get("AWS_REGION", "ap-southeast-1")).Table(TABLE)


def bump(field, n=1):
    try:
        _ddb.update_item(Key={"pk": "metrics", "sk": "counters"},
                         UpdateExpression="ADD #f :n", ExpressionAttributeNames={"#f": field},
                         ExpressionAttributeValues={":n": decimal.Decimal(n)})
    except Exception:
        pass


def record_latency(ms):
    try:
        _ddb.update_item(Key={"pk": "metrics", "sk": "latency"},
                         UpdateExpression="SET samples = list_append(if_not_exists(samples, :e), :s)",
                         ExpressionAttributeValues={":s": [decimal.Decimal(int(ms))], ":e": []})
    except Exception:
        pass


def note_calc(calc_id, result_summary):
    """§9 keep every calculation so a historical budget can be reproduced."""
    try:
        _ddb.put_item(Item={"pk": "calc", "sk": calc_id, "at": int(time.time()),
                            "summary": json.dumps(result_summary, ensure_ascii=False)[:8000],
                            "ttl": int(time.time()) + 30 * 24 * 3600})
        bump("calculations")
    except Exception:
        pass


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
    c = _ddb.get_item(Key={"pk": "metrics", "sk": "counters"}).get("Item") or {}
    l = _ddb.get_item(Key={"pk": "metrics", "sk": "latency"}).get("Item") or {}
    s = [int(x) for x in (l.get("samples") or [])][-LAT_SAMPLES:]
    return {"invocations": int(c.get("invocations", 0)),
            "calculations": int(c.get("calculations", 0)),
            "sessions": int(c.get("calculations", 0)),
            "latency_ms": {"p50": pct(s, 50), "p95": pct(s, 95)},
            "system_errors": int(c.get("system_errors", 0)),
            "user_errors": int(c.get("user_errors", 0)),
            "throttles": int(c.get("throttles", 0)),
            "generated_at": datetime.now(timezone.utc).isoformat()}


def resp(code, obj, raw=None):
    if raw is not None:
        return {"statusCode": code, "headers": {"Content-Type": "application/json"}, "body": raw}
    return {"statusCode": code, "headers": {"Content-Type": "application/json"},
            "body": json.dumps(obj, ensure_ascii=False, default=str)}


def authed(event):
    h = {k.lower(): v for k, v in (event.get("headers") or {}).items()}
    a = h.get("authorization", "")
    return a.startswith("Bearer ") and a[7:].strip() == TOKEN


def _result_dict(r):
    d = dict(r.__dict__)
    return json.loads(json.dumps(d, ensure_ascii=False, default=str))


def handler(event, context):
    t0 = time.time()
    path = (event.get("rawPath") or event.get("path") or "/").rstrip("/") or "/"
    method = ((event.get("requestContext") or {}).get("http") or {}).get("method", "GET").upper()

    if not authed(event):
        bump("user_errors")
        return resp(401, {"error": "unauthorized"})

    try:
        if path.endswith("/metrics") and method == "GET":
            return resp(200, read_metrics())

        if path.endswith("/health"):
            return resp(200, {"status": "ok", "synthetic_only": True,
                              "generated_at": datetime.now(timezone.utc).isoformat()})

        body = json.loads(event.get("body") or "{}")

        if path.endswith("/budget") and method == "POST":
            r = build_budget(body.get("payload") or body, params=body.get("params"))
            out = _result_dict(r)
            note_calc(r.calc_id, {"authorized_total": str(r.authorized_total),
                                  "site": r.site_code, "study": r.study_number})
            bump("invocations"); record_latency((time.time() - t0) * 1000)
            return resp(200, out)

        if path.endswith("/budget/excel") and method == "POST":
            r = build_budget(body.get("payload") or body, params=body.get("params"))
            xl = outputs.budget_workbook(r)
            bump("invocations"); record_latency((time.time() - t0) * 1000)
            return resp(200, {"calc_id": r.calc_id,
                              "authorized_total": str(r.authorized_total),
                              "xlsx_base64": base64.b64encode(xl).decode(),
                              "csv": outputs.budget_csv(r),
                              "sheets": ["访视费用明细", "费用标准对应关系", "汇总与付费日程"]})

        if path.endswith("/amendment") and method == "POST":
            base = body.get("baseline") or {}
            rev = body.get("revised") or {}
            r_old = build_budget(base.get("payload") or {}, params=base.get("params"))
            r_new = build_budget(rev.get("payload") or {}, params=rev.get("params"))
            imp = amendment_impact(r_old, r_new, body.get("changed_procedures") or [])
            bump("invocations"); record_latency((time.time() - t0) * 1000)
            return resp(200, {"impact": imp,
                              "baseline_authorized": str(r_old.authorized_total),
                              "revised_authorized": str(r_new.authorized_total)})

        bump("user_errors")
        return resp(404, {"error": "not found",
                          "routes": ["POST /budget", "POST /budget/excel", "POST /amendment",
                                     "GET /metrics", "GET /health"]})
    except Exception as e:
        bump("system_errors"); record_latency((time.time() - t0) * 1000)
        return resp(500, {"error": type(e).__name__, "detail": str(e)[:300]})
