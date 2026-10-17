"""Framework-neutral API layer shared by serve.py (stdlib) and api.py (FastAPI). Demo sessions only."""
import re, threading, logging
import engine as E
SESSIONS = {"demo-customer": ("customer", "C001"), "demo-handler": ("claims_handler", None), "demo-admin": ("administrator", None)}
STAFF = {"claims_handler", "administrator"}
LOCK = threading.Lock(); log = logging.getLogger("smartclaim")
ID = r"(INC-[0-9A-F]{8})"

def handle(db, method, path, token, body=None, query=None):
    body, q = body or {}, query or {}
    s = SESSIONS.get(token or "")
    if not s: return 401, {"error": "Invalid or missing session"}
    role, cid = s
    def cust():
        if role != "customer": raise PermissionError("Customer session required")
        return cid
    def staff():
        if role not in STAFF: raise PermissionError("Staff role required")
    try:
        with LOCK:
            if method == "GET" and path == "/api/me": return 200, {"role": role}
            if method == "POST":
                if path == "/api/incidents/analyze": return 200, E.analyze(db, cust(), body.get("text"))
                if path == "/api/notifications/prepare": return 200, E.prepare_notification(db, str(body.get("incident_id")), cust())
                if path == "/api/notifications/dispatch": return 200, E.dispatch_notification(db, str(body.get("incident_id")), cust(), body.get("consent") is True, body=body.get("body"))
                if path == "/api/claims/draft": return 200, E.draft_claim(db, str(body.get("incident_id")), cust())
                if path == "/api/claims/submit": return 200, E.submit_claim(db, str(body.get("incident_id")), cust(), edits=body.get("edits"))
                m = re.fullmatch(r"/api/staff/incidents/" + ID + "/(override|resolve)", path)
                if m:
                    staff()
                    if m[2] == "resolve": E.resolve(db, m[1], role)
                    else: E.override(db, m[1], role, str(body.get("outcome")), str(body.get("reason", ""))[:200])
                    return 200, E.incident_detail(db, m[1])
            if method == "GET":
                m = re.fullmatch(r"/api/incidents/" + ID, path)
                if m:
                    inc = E._inc(db, m[1])
                    if role == "customer" and inc["customer_id"] != cid: raise PermissionError("Not your incident")
                    return 200, E.incident_detail(db, m[1])
                if path == "/api/dashboard/metrics": staff(); return 200, E.metrics(db, since=q.get("since"), category=q.get("category"))
                if path == "/api/staff/incidents": staff(); return 200, {"incidents": E.list_incidents(db, **{k: q.get(k) for k in ("status", "category", "urgency", "outcome", "since")})}
                m = re.fullmatch(r"/api/staff/incidents/" + ID, path)
                if m: staff(); return 200, E.incident_detail(db, m[1])
        return 404, {"error": "Not found"}
    except PermissionError as e: return 403, {"error": str(e)}
    except KeyError as e: return 404, {"error": str(e).strip("'\"")}
    except ValueError as e: return 422, {"error": str(e)}
    except Exception: log.exception("unhandled"); return 500, {"error": "Internal error"}
