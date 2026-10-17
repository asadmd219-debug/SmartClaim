"""SmartClaim core: classifier (LLM hook + deterministic fallback), rules engine, mock adapters,
idempotent workflows, audit log, metrics. Stdlib only (sqlite3). All data is synthetic."""
import json, random, re, sqlite3, time, uuid
from datetime import datetime, timedelta, timezone

CATS = ["fire_smoke", "electrical", "water_leak", "water_damage", "theft", "storm", "glass", "appliance", "structural", "other"]
CLAIM_CATS = {"theft", "storm", "glass", "appliance", "electrical", "structural"}
LOW_CONF, CLARIFY_CONF = 0.6, 0.5   # configurable thresholds
KW = {
 "fire_smoke": r"\bsmoke|\bfire\b|burning|\bflame|savu|tulipalo|palaa",
 "electrical": r"\bsocket|\boutlet|\bsparks?\b|electric|\bfuse|\bwiring|pistorasia|sähkö|oikosulku",
 "water_leak": r"\bleak|\bdrip|pouring|\bburst|\bflood|vuota|tippuu|\bvuoto|\bletku",
 "water_damage": r"wet patch|\bwet\b|\bdamp|\bstain|\bmou?ld|märkä|kostea|homei",
 "theft": r"stole|\bstolen|\bburglar|break.?in|broke into|\btheft|varka|murto|murtau",
 "storm": r"\bstorm|\bhail|\bwind\b|\bfallen tree|myrsky|rakeet",
 "glass": r"\bwindow|\bglass|ikkuna|lasi",
 "appliance": r"dishwasher|refrigerator|\bfridge|\bfreezer|washing machine|\boven\b|\bstove|astianpesu|jääkaap|pakastin|pesukone|\bappliance",
 "structural": r"\bcrack|\bcollaps|\bfoundation|\bsagging|halkeam|sortu",
}
EMERGENCY = r"smoke.*(socket|outlet)|(socket|outlet).*(smoke|spark|burn)|\bfire\b|\bflames?\b|gas leak|kaasu|\bsparking|tulipalo|\bintruder (is )?(still|inside)|\bsavu"
INJECTION = r"ignore (all |any |previous |the )*(instructions|rules)|system prompt|you are now|approve (the )?claim|reveal .*(prompt|key)|<\s*script"
GUIDE = {
 "A": "Move everyone to safety. Call 112 now. Do not use water on electrical equipment. Claim details can wait.",
 "water": "If it is safe, close the water supply, switch off power near the water and move belongings away from it.",
 "theft": "Do not touch anything. If the intruder may still be there, leave and call 112. Otherwise report to the police and keep the report number.",
 "storm": "Keep away from broken glass or fallen objects. Cover openings temporarily if safe and photograph the damage.",
 "default": "Photograph the damage and avoid using damaged equipment.",
}

def now_utc(): return datetime.now(timezone.utc)
def iso(d): return d.astimezone(timezone.utc).isoformat(timespec="seconds")

# ---------- database ----------
SCHEMA = """
CREATE TABLE IF NOT EXISTS customers(id TEXT PRIMARY KEY, name TEXT, address TEXT, property_type TEXT, policy_ref TEXT);
CREATE TABLE IF NOT EXISTS policies(ref TEXT PRIMARY KEY, type TEXT, status TEXT, covered TEXT, deductible INTEGER, exclusions TEXT, notes TEXT);
CREATE TABLE IF NOT EXISTS incidents(id TEXT PRIMARY KEY, customer_id TEXT, created_at TEXT, text TEXT, category TEXT, urgency TEXT,
  confidence REAL, outcome TEXT, status TEXT, destination TEXT, rule_ids TEXT, analysis TEXT, recommend_ms REAL, completed_at TEXT, override_by TEXT);
CREATE TABLE IF NOT EXISTS events(id INTEGER PRIMARY KEY AUTOINCREMENT, incident_id TEXT, ts TEXT, type TEXT, detail TEXT);
CREATE TABLE IF NOT EXISTS notifications(id TEXT PRIMARY KEY, incident_id TEXT UNIQUE, recipient TEXT, body TEXT, status TEXT, created_at TEXT, updated_at TEXT);
CREATE TABLE IF NOT EXISTS claims(id TEXT PRIMARY KEY, incident_id TEXT UNIQUE, policy_ref TEXT, draft TEXT, status TEXT, created_at TEXT, updated_at TEXT);
"""
def connect(path=":memory:"):
    db = sqlite3.connect(path, check_same_thread=False); db.row_factory = sqlite3.Row; db.executescript(SCHEMA); return db

def audit(db, iid, typ, detail="", ts=None):
    db.execute("INSERT INTO events(incident_id,ts,type,detail) VALUES(?,?,?,?)", (iid, iso(ts or now_utc()), typ, detail[:300]))

# ---------- classification ----------
def classify_fallback(text):
    t = text.lower()
    hits = {c: len(re.findall(p, t)) for c, p in KW.items()}
    emergency = bool(re.search(EMERGENCY, t))
    order = [c for c in CATS if c != "other"]
    primary = max(order, key=lambda c: (hits[c], -order.index(c)))
    n = hits[primary]
    if emergency and n == 0: primary, n = "fire_smoke", 1
    if n == 0: primary = "other"
    secondary = sum(v for c, v in hits.items() if c != primary)
    conf = 0.3 if n == 0 else min(0.95, 0.6 + 0.1 * n + 0.05 * min(secondary, 2))
    if emergency: primary = "fire_smoke" if re.search(r"smoke|fire|savu|flame", t) else "electrical"; conf = max(conf, 0.9)
    unknown_src = bool(re.search(r"don.?t know|not sure|unknown|en tiedä|mistä", t))
    water_active = primary == "water_leak" or bool(re.search(r"getting wet|flood|pouring|burst", t))
    urgency = "emergency" if emergency else "high" if (water_active or primary == "water_damage") else "medium" if n else "low"
    ptype = "apartment" if re.search(r"apartment|flat|asunto", t) else "house" if re.search(r"\bhouse\b|omakotitalo", t) else None
    src = next((m.group(0) for m in [re.search(KW["appliance"], t)] if m), None) if primary.startswith("water") else None
    return {"category": primary, "urgency": urgency, "confidence": round(conf, 2), "emergency": emergency,
            "source_unknown": unknown_src and primary.startswith("water"), "source_appliance": src,
            "property_type_stated": ptype, "hazards": ["electrical"] if primary in ("electrical", "water_leak") else [], "method": "fallback"}

def classify(text, provider=None):
    """provider: optional callable(text)->dict. Its output is schema-validated; anything invalid falls back."""
    if provider:
        try:
            r = provider(text)
            if r["category"] in CATS and r["urgency"] in ("emergency", "high", "medium", "low") and 0 <= float(r["confidence"]) <= 1:
                r.setdefault("emergency", r["urgency"] == "emergency"); r["method"] = "llm"
                if re.search(EMERGENCY, text.lower()): return classify_fallback(text)  # safety rules never downgraded by an LLM
                return r
        except Exception: pass
    return classify_fallback(text)

# ---------- rules engine ----------
def lookup_policy(db, customer_id):
    c = db.execute("SELECT * FROM customers WHERE id=?", (customer_id,)).fetchone()
    p = db.execute("SELECT * FROM policies WHERE ref=?", (c["policy_ref"],)).fetchone() if c else None
    return c, p

def decide(a, customer, policy, suspicious=False):
    cat, ptype = a["category"], (customer["property_type"] if customer else a.get("property_type_stated"))
    covered = bool(policy and policy["status"] == "active" and cat in json.loads(policy["covered"]))
    def out(o, rule, dest, safety, why):
        return {"outcome": o, "rule_ids": [rule], "destination": dest, "safety": safety, "reason": why, "policy_covers": covered}
    if suspicious: return out("D", "R-INJ-1", "human_review", GUIDE["default"], "The text contained instruction-like content, so a person must review it.")
    if a["emergency"]: return out("A", "R-EMG-1", "emergency_112", GUIDE["A"], "Possible immediate danger. Safety comes before any claim or notification.")
    if a["confidence"] < CLARIFY_CONF: return out("D", "R-CLARIFY-1", "clarification", GUIDE["default"], "Not enough detail. One question is needed to choose a safe next step.")
    if a["confidence"] < LOW_CONF: return out("D", "R-LOWCONF-1", "human_review", GUIDE["default"], "Low classification confidence, so no automatic action is taken.")
    if cat in ("water_leak", "water_damage"):
        if a["source_unknown"] or cat == "water_damage":
            return out("D", "R-WATER-UNK-1", "human_review", GUIDE["water"], "The source of the water is not known. Maintenance assessment is recommended and responsibility is not decided.")
        if ptype == "apartment":
            return out("B", "R-WATER-APT-1", "property_manager", GUIDE["water"], "A possible water leak in an apartment building: notifying building maintenance may be the fastest next step. Responsibility and coverage are not confirmed.")
    if cat in CLAIM_CATS or cat in ("water_leak",):
        g = GUIDE["theft"] if cat == "theft" else GUIDE["storm"] if cat in ("storm", "glass") else GUIDE["default"]
        if covered: return out("C", "R-CLAIM-1", "claim_draft", g, "This type of incident may fall under your policy. A draft claim can be prepared. Coverage is decided by the claims process, not here.")
        return out("D", "R-COVERAGE-UNK-1", "human_review", g, "Coverage for this incident could not be confirmed from the policy data, so a person will assess it.")
    return out("D", "R-OTHER-1", "human_review", GUIDE["default"], "This incident type needs human assessment.")

def analyze(db, customer_id, text, provider=None, created_at=None):
    t0 = time.perf_counter()
    text = re.sub(r"[\x00-\x08\x0b-\x1f]", "", str(text or "")).strip()
    if not 3 <= len(text) <= 1000: raise ValueError("Description must be 3-1000 characters")
    cust, pol = lookup_policy(db, customer_id)
    if not cust: raise PermissionError("Unknown customer session")
    a = classify(text, provider)
    d = decide(a, cust, pol, bool(re.search(INJECTION, text.lower())))
    ms = round((time.perf_counter() - t0) * 1000, 2); ts = created_at or now_utc()
    iid = "INC-" + uuid.uuid4().hex[:8].upper()
    status = "needs_review" if d["outcome"] == "D" and d["destination"] == "human_review" else "awaiting_customer" if d["outcome"] != "A" else "emergency_shown"
    if d["outcome"] == "D" and d["destination"] == "clarification": status = "needs_clarification"
    db.execute("INSERT INTO incidents VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)", (iid, customer_id, iso(ts), text, a["category"], a["urgency"], a["confidence"],
        d["outcome"], status, d["destination"], json.dumps(d["rule_ids"]), json.dumps({**a, **d}), ms, None, None))
    audit(db, iid, "analyzed", f"{a['category']}/{a['urgency']} conf={a['confidence']} -> {d['outcome']} via {d['rule_ids'][0]}", ts)
    if status == "needs_review": audit(db, iid, "queued_for_review", d["reason"], ts)
    db.commit()
    question = "What was damaged, and where in your home?" if d["destination"] == "clarification" else None
    return {"id": iid, "category": a["category"], "urgency": a["urgency"], "outcome": d["outcome"], "safety": d["safety"], "message": d["reason"],
            "question": question, "status": status, "rule_ids": d["rule_ids"], "disclaimer": "AI-assisted guidance, not a coverage or legal decision."}

# ---------- mock adapters (replace with authorised integrations) ----------
class MockNotifier:
    def send(self, recipient, body): return "simulated_delivered"
class MockClaims:
    def create(self, policy_ref, draft): return "submitted_pending_review"

def _inc(db, iid):
    r = db.execute("SELECT * FROM incidents WHERE id=?", (iid,)).fetchone()
    if not r: raise KeyError("Unknown incident")
    return r

def _default_body(cust, inc):
    return f"Urgent incident at {cust['address']}: {inc['text']} (category {inc['category']}, urgency {inc['urgency']}). Please inspect."

def prepare_notification(db, iid, customer_id):
    inc = _inc(db, iid)
    if inc["customer_id"] != customer_id: raise PermissionError("Not your incident")
    if inc["outcome"] != "B": raise ValueError("This incident is not routed to a notification")
    cust, _ = lookup_policy(db, customer_id); audit(db, iid, "notification_prepared")
    db.commit()
    return {"incident_id": iid, "recipient": "Property manager or maintenance (demo)", "address": cust["address"], "body": _default_body(cust, inc)}

def dispatch_notification(db, iid, customer_id, consent, notifier=None, body=None):
    inc = _inc(db, iid)
    if inc["customer_id"] != customer_id: raise PermissionError("Not your incident")
    if not consent: raise ValueError("Consent is required before sending customer information")
    if inc["outcome"] != "B": raise ValueError("This incident is not routed to a notification")
    ex = db.execute("SELECT * FROM notifications WHERE incident_id=?", (iid,)).fetchone()
    if ex: return dict(ex) | {"duplicate": True}          # idempotent: second click changes nothing
    cust, _ = lookup_policy(db, customer_id); ts = iso(now_utc())
    body = (str(body).strip() if body else _default_body(cust, inc))[:1000]
    nid = "NTF-" + uuid.uuid4().hex[:8].upper()
    db.execute("INSERT INTO notifications VALUES(?,?,?,?,?,?,?)", (nid, iid, "Property manager (demo)", body, "queued", ts, ts)); audit(db, iid, "notification_queued", nid)
    st = (notifier or MockNotifier()).send("Property manager (demo)", body)
    db.execute("UPDATE notifications SET status=?, updated_at=? WHERE id=?", (st, iso(now_utc()), nid))
    db.execute("UPDATE incidents SET status='notified', completed_at=? WHERE id=?", (iso(now_utc()), iid)); audit(db, iid, "notification_" + st, nid); db.commit()
    return {"id": nid, "incident_id": iid, "status": st, "duplicate": False, "note": "Recorded in demo system. No real recipient was contacted."}

def draft_claim(db, iid, customer_id):
    inc = _inc(db, iid)
    if inc["customer_id"] != customer_id: raise PermissionError("Not your incident")
    if inc["outcome"] != "C": raise ValueError("This incident is not routed to a claim")
    ex = db.execute("SELECT * FROM claims WHERE incident_id=?", (iid,)).fetchone()
    if ex: return dict(ex) | {"duplicate": True}
    cust, pol = lookup_policy(db, customer_id); ts = iso(now_utc())
    draft = {"policy_ref": pol["ref"], "category": inc["category"], "description": inc["text"], "date": inc["created_at"], "address": cust["address"],
             "deductible_eur": pol["deductible"], "suggested_evidence": ["photos", "receipts"], "handler_summary": f"{inc['category']} reported via SmartClaim; coverage not assessed."}
    cid = "CLM-" + uuid.uuid4().hex[:8].upper()
    db.execute("INSERT INTO claims VALUES(?,?,?,?,?,?,?)", (cid, iid, pol["ref"], json.dumps(draft), "draft", ts, ts)); audit(db, iid, "claim_drafted", cid); db.commit()
    return {"id": cid, "status": "draft", "draft": draft, "duplicate": False}

def submit_claim(db, iid, customer_id, claims=None, edits=None):
    c = db.execute("SELECT * FROM claims WHERE incident_id=?", (iid,)).fetchone()
    if not c or _inc(db, iid)["customer_id"] != customer_id: raise KeyError("No draft claim for this incident")
    if c["status"] != "draft": return dict(c) | {"duplicate": True}
    if edits and edits.get("description"):
        d = json.loads(c["draft"]); d["description"] = str(edits["description"])[:1000]
        db.execute("UPDATE claims SET draft=? WHERE id=?", (json.dumps(d), c["id"])); c = db.execute("SELECT * FROM claims WHERE id=?", (c["id"],)).fetchone()
    st = (claims or MockClaims()).create(c["policy_ref"], c["draft"])
    db.execute("UPDATE claims SET status=?, updated_at=? WHERE id=?", (st, iso(now_utc()), c["id"]))
    db.execute("UPDATE incidents SET status='claim_submitted', completed_at=? WHERE id=?", (iso(now_utc()), iid)); audit(db, iid, "claim_" + st, c["id"]); db.commit()
    return {"id": c["id"], "status": st, "duplicate": False, "note": "Submitted to demo claims adapter. No coverage decision has been made."}

def override(db, iid, role, new_outcome, reason):
    if role not in ("claims_handler", "administrator"): raise PermissionError("Staff role required")
    if new_outcome not in "ABCD": raise ValueError("Invalid outcome")
    _inc(db, iid)
    dest = {"A": "emergency_112", "B": "property_manager", "C": "claim_draft", "D": "human_review"}[new_outcome]
    db.execute("UPDATE incidents SET outcome=?, destination=?, status='awaiting_customer', override_by=? WHERE id=?", (new_outcome, dest, role, iid))
    audit(db, iid, "human_override", f"{role} -> {new_outcome}: {reason}"); db.commit()

# ---------- staff queries ----------
def list_incidents(db, limit=200, **f):
    w, a = ["1=1"], []
    for col in ("status", "category", "urgency", "outcome"):
        if f.get(col): w.append(f"{col}=?"); a.append(f[col])
    if f.get("since"): w.append("created_at>=?"); a.append(f["since"])
    rows = db.execute("SELECT id,created_at,category,urgency,outcome,status,confidence,destination FROM incidents WHERE " + " AND ".join(w) + " ORDER BY created_at DESC LIMIT ?", a + [limit])
    return [dict(r) for r in rows]

def incident_detail(db, iid):
    d = dict(_inc(db, iid)); d["analysis"] = json.loads(d["analysis"]); d["rule_ids"] = json.loads(d["rule_ids"]); d.pop("customer_id")
    d["events"] = [dict(r) for r in db.execute("SELECT ts,type,detail FROM events WHERE incident_id=? ORDER BY id", (iid,))]
    n = db.execute("SELECT * FROM notifications WHERE incident_id=?", (iid,)).fetchone(); c = db.execute("SELECT * FROM claims WHERE incident_id=?", (iid,)).fetchone()
    d["notification"] = dict(n) if n else None
    d["claim"] = (dict(c) | {"draft": json.loads(c["draft"])}) if c else None
    return d

def resolve(db, iid, role):
    if role not in ("claims_handler", "administrator"): raise PermissionError("Staff role required")
    _inc(db, iid); db.execute("UPDATE incidents SET status='resolved', completed_at=COALESCE(completed_at,?) WHERE id=?", (iso(now_utc()), iid)); audit(db, iid, "resolved", role); db.commit()

# ---------- metrics (all from stored rows) ----------
def metrics(db, since=None, category=None):
    w, args = "WHERE 1=1", []
    if since: w += " AND created_at>=?"; args.append(since)
    if category: w += " AND category=?"; args.append(category)
    q = lambda s, a=(): db.execute(s, a).fetchall()
    rows = q(f"SELECT * FROM incidents {w}", args)
    n = len(rows); by = lambda k: {r[0]: r[1] for r in q(f"SELECT {k}, COUNT(*) FROM incidents {w} GROUP BY {k}", args)}
    ids = {r["id"] for r in rows}
    notif = [r for r in q("SELECT * FROM notifications") if r["incident_id"] in ids]
    claims = [r for r in q("SELECT * FROM claims") if r["incident_id"] in ids]
    claimed = {c["incident_id"] for c in claims}
    avoided = [x for x in notif if x["status"] == "simulated_delivered" and x["incident_id"] not in claimed]
    done = [(datetime.fromisoformat(r["completed_at"]) - datetime.fromisoformat(r["created_at"])).total_seconds() for r in rows if r["completed_at"]]
    buckets = {"<0.6": 0, "0.6-0.8": 0, ">=0.8": 0}
    for r in rows: buckets["<0.6" if r["confidence"] < .6 else "0.6-0.8" if r["confidence"] < .8 else ">=0.8"] += 1
    trend = {}
    for r in rows: trend[r["created_at"][:10]] = trend.get(r["created_at"][:10], 0) + 1
    return {"total_incidents": n, "notifications_dispatched_simulated": len(notif), "claims_drafted": len(claims),
            "claims_submitted": sum(c["status"] != "draft" for c in claims), "routed_without_claim_prototype": len(avoided),
            "avg_recommendation_ms": round(sum(r["recommend_ms"] for r in rows) / n, 2) if n else None,
            "avg_completion_seconds": round(sum(done) / len(done), 1) if done else None,
            "awaiting_human_review": sum(r["status"] == "needs_review" for r in rows), "uncertain": sum(r["outcome"] == "D" for r in rows),
            "by_category": by("category"), "by_outcome": by("outcome"), "confidence_buckets": buckets, "trend_by_day": dict(sorted(trend.items())),
            "note": "Prototype routing outcomes on synthetic data, not proven savings."}

# ---------- synthetic seed ----------
STREETS = ["Mannerheimintie", "Aleksanterinkatu", "Hämeenkatu", "Yliopistonkatu", "Kauppakatu", "Rautatienkatu"]
CITIES = [("00100", "Helsinki"), ("20100", "Turku"), ("33100", "Tampere"), ("90100", "Oulu")]
SAMPLES = ["Water is leaking from behind my dishwasher, and the floor is getting wet.", "A storm broke the kitchen window last night.", "My refrigerator stopped working this morning.",
 "There is smoke coming from an electrical socket.", "There is a wet patch on the ceiling, but I don't know where the water is coming from.", "Someone broke into my apartment and stole my laptop.",
 "Something is damaged in my apartment.", "Vettä tippuu katosta keittiössä", "Pesukoneen letku irtosi ja lattia on märkä", "Hail damaged the car port roof", "A crack appeared in the foundation wall"]

def seed(db, customers=30, incidents=100, rnd_seed=42):
    r = random.Random(rnd_seed)
    for i in range(1, customers + 1):
        ref = f"P-{i:04d}"; zip_, city = r.choice(CITIES); pt = "apartment" if i == 1 else r.choice(["apartment", "apartment", "row_house", "house"])
        cov = ["water_leak", "water_damage", "fire_smoke", "storm", "glass", "theft", "electrical", "appliance"] if i == 1 else r.sample(CATS[:-1], r.randint(4, 9))
        db.execute("INSERT OR IGNORE INTO policies VALUES(?,?,?,?,?,?,?)", (ref, "Home insurance (DEMO)", "lapsed" if i % 11 == 0 else "active", json.dumps(cov), r.choice([100, 150, 250]), "demo exclusions", "Synthetic policy, not real If terms"))
        db.execute("INSERT OR IGNORE INTO customers VALUES(?,?,?,?,?)", (f"C{i:03d}", f"Demo Customer {i}", f"{r.choice(STREETS)} {r.randint(1, 80)} A {r.randint(1, 30)}, {zip_} {city}", pt, ref))
    base = now_utc() - timedelta(days=90)
    for _ in range(incidents):
        ts = base + timedelta(minutes=r.randint(0, 90 * 24 * 60)); cid = f"C{r.randint(1, customers):03d}"
        res = analyze(db, cid, r.choice(SAMPLES), created_at=ts)
        if res["outcome"] == "B" and r.random() < .7: dispatch_notification(db, res["id"], cid, True)
        if res["outcome"] == "C" and r.random() < .6:
            draft_claim(db, res["id"], cid)
            if r.random() < .7: submit_claim(db, res["id"], cid)
    db.commit()
