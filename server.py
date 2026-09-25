"""Campus Help Desk - backend. Python 3.8+ standard library only (http.server + sqlite3)."""
import json, os, re, sqlite3, time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

HERE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(HERE, "tickets.db")
HR = 3600
SLA = {"P1": (1, 4), "P2": (4, 48), "P3": (24, 120), "P4": (48, 168)}  # (first response, resolution) hours
TEAM = {"Fees": "Accounts", "Attendance": "Academics", "Certificates": "Academics",
        "ID Card": "Administration", "Documents": "Administration", "Other": "Administration"}
FLOW = {"Open": ["In Progress", "Rejected"],
        "In Progress": ["Pending Student", "Pending Internal", "Resolved"],
        "Pending Student": ["In Progress"], "Pending Internal": ["In Progress"],
        "Resolved": ["Closed", "Open"], "Closed": ["Open"]}
NEEDS_NOTE = {"Pending Student", "Pending Internal", "Resolved", "Rejected", "Open"}
DONE = ("Resolved", "Closed", "Rejected")
LEVELS = {1: "Team lead", 2: "Department head", 3: "Management"}


class Err(Exception):
    def __init__(self, code, msg):
        super().__init__(msg); self.code = code


def db():
    c = sqlite3.connect(DB); c.row_factory = sqlite3.Row; return c


def now(c):  # real time + demo offset ("advance time" button)
    return int(time.time()) + int(c.execute("select v from meta where k='offset'").fetchone()[0])


def log(c, tid, actor, action, detail="", internal=0, ts=None):
    c.execute("insert into activity(ticket_id,actor_id,action,detail,internal,ts) values(?,?,?,?,?,?)",
              (tid, actor, action, detail, internal, ts or now(c)))


def prio(cat, text):
    s = text.lower()
    if any(k in s for k in ("hall ticket", "exam tomorrow", "blocked")): return "P1"
    if any(k in s for k in ("urgent", "deadline", "visa", "scholarship", "last date", "convocation")): return "P2"
    return "P4" if cat == "Other" else "P3"


def new_ticket(c, sid, cat, subj, desc, at=None):
    t = at or now(c); p = prio(cat, subj + " " + desc)
    agents = c.execute("""select u.id, (select count(*) from tickets k where k.assignee_id=u.id
        and k.status not in ('Resolved','Closed','Rejected')) n from users u
        where u.role='agent' and u.team=? order by n, u.id""", (TEAM[cat],)).fetchone()
    cur = c.execute("""insert into tickets(student_id,category,subject,description,priority,status,assignee_id,
        created_at,due_at) values(?,?,?,?,?,?,?,?,?)""",
        (sid, cat, subj, desc, p, "Open", agents["id"] if agents else None, t, t + SLA[p][1] * HR))
    tid = cur.lastrowid
    log(c, tid, sid, "created", f"Priority {p} set automatically", ts=t)
    if agents: log(c, tid, 0, "assigned", f"Auto-assigned to {uname(c, agents['id'])} ({TEAM[cat]} team)", ts=t)
    return tid


def uname(c, uid):
    r = c.execute("select name from users where id=?", (uid,)).fetchone()
    return r["name"] if r else "System"


def set_status(c, r, new, actor, note=""):
    t = now(c); old = r["status"]; f = {"status": new}
    if old == "Pending Student":  # SLA clock was paused: push the due date out
        f["due_at"] = r["due_at"] + (t - r["pending_since"]); f["pending_since"] = None
    if new == "Pending Student": f["pending_since"] = t
    if new == "Resolved": f.update(resolved_at=t, resolution_note=note)
    if new == "Open" and old in ("Resolved", "Closed"):
        f.update(resolved_at=None, due_at=t + 86400, reopen_count=r["reopen_count"] + 1)
    if new == "In Progress" and not r["first_response_at"] and actor["role"] != "student": f["first_response_at"] = t
    c.execute(f"update tickets set {','.join(k + '=?' for k in f)} where id=?", (*f.values(), r["id"]))
    log(c, r["id"], actor["id"], "status_changed", f"{old} → {new}" + (f": {note}" if note else ""))


def sweep(c):  # runs before every request; acts as the scheduler in this prototype
    t = now(c)
    for r in c.execute("select * from tickets where status not in ('Closed','Rejected')").fetchall():
        sysu = {"id": 0, "role": "system"}
        if r["status"] == "Resolved" and t - r["resolved_at"] > 3 * 86400:
            set_status(c, r, "Closed", sysu, "Auto-closed: no response for 3 days"); continue
        if r["status"] == "Pending Student" and t - r["pending_since"] > 7 * 86400:
            set_status(c, r, "In Progress", sysu); r = c.execute("select * from tickets where id=?", (r["id"],)).fetchone()
            set_status(c, r, "Resolved", sysu, "Student unresponsive for 7 days"); continue
        if r["status"] in ("Resolved", "Pending Student"): continue  # SLA stopped or paused
        rem, res = r["due_at"] - t, SLA[r["priority"]][1] * HR
        lvl = 3 if (rem < -2 * 86400 or (r["priority"] == "P1" and rem < 0)) else 2 if rem < 0 else 1 if 1 - rem / res >= .75 else 0
        if lvl > r["escalation_level"]:
            c.execute("update tickets set escalation_level=? where id=?", (lvl, r["id"]))
            log(c, r["id"], 0, "escalated", f"Auto-escalated to L{lvl} ({LEVELS[lvl]}): " + ("SLA breached" if lvl > 1 else "75% of SLA used"))


def sla_state(r, t):
    if r["status"] in DONE: return "Closed" if not r["resolved_at"] else ("Met" if r["resolved_at"] <= r["due_at"] else "Missed")
    if r["status"] == "Pending Student": return "Paused"
    rem, res = r["due_at"] - t, SLA[r["priority"]][1] * HR
    return "Breached" if rem < 0 else "At risk" if 1 - rem / res >= .75 else "On track"


def ser(c, r):
    t = now(c); d = dict(r)
    d.update(student=uname(c, r["student_id"]), assignee=uname(c, r["assignee_id"]) if r["assignee_id"] else None,
             team=TEAM[r["category"]], age_days=round((t - r["created_at"]) / 86400, 1), sla=sla_state(r, t), now=t)
    return d


def can_see(me, r):
    if me["role"] == "student": return r["student_id"] == me["id"]
    if me["role"] == "agent": return TEAM[r["category"]] == me["team"] or r["assignee_id"] == me["id"]
    return True


def dashboard(c):
    t = now(c); rows = [dict(r) for r in c.execute("select * from tickets")]
    live = [r for r in rows if r["status"] not in DONE]; done = [r for r in rows if r["resolved_at"]]

    def count(key, rs):
        o = {}
        for r in rs: o[r[key]] = o.get(r[key], 0) + 1
        return o
    ages = dict.fromkeys(["0-2 days", "3-5 days", "6-10 days", "10+ days"], 0)
    for r in live:
        d = (t - r["created_at"]) / 86400; ages["0-2 days" if d < 3 else "3-5 days" if d < 6 else "6-10 days" if d < 11 else "10+ days"] += 1
    fr = [r["first_response_at"] - r["created_at"] for r in rows if r["first_response_at"]]
    avg = lambda xs: round(sum(xs) / len(xs) / HR, 1) if xs else None
    return {"total": len(rows), "open": len(live), "by_status": count("status", rows), "by_category": count("category", rows),
            "by_priority": count("priority", live), "ageing": ages,
            "sla_compliance": round(100 * sum(r["resolved_at"] <= r["due_at"] for r in done) / len(done)) if done else None,
            "avg_resolution_hrs": avg([r["resolved_at"] - r["created_at"] for r in done]), "avg_first_response_hrs": avg(fr),
            "breached": sum(1 for r in live if r["status"] != "Pending Student" and r["due_at"] < t),
            "escalated": sum(1 for r in live if r["escalation_level"] > 0), "reopened": sum(1 for r in rows if r["reopen_count"]),
            "workload": {u["name"]: sum(1 for r in live if r["assignee_id"] == u["id"])
                         for u in c.execute("select * from users where role='agent'")}}


def handle(c, method, path, body, me):
    if path == "/api/users": return 200, [dict(r) for r in c.execute("select * from users")]
    if not me: raise Err(401, "Choose a user to sign in as")
    sweep(c); staff = me["role"] != "student"
    if (method, path) == ("POST", "/api/tickets"):
        if staff: raise Err(403, "Only students raise tickets")
        cat, subj, desc = body.get("category"), (body.get("subject") or "").strip(), (body.get("description") or "").strip()
        if cat not in TEAM or len(subj) < 5 or len(desc) < 10:
            raise Err(400, "Choose a category, add a subject (5+ characters) and a description (10+ characters)")
        return 201, {"id": new_ticket(c, me["id"], cat, subj, desc)}
    if (method, path) == ("GET", "/api/tickets"):
        return 200, [ser(c, r) for r in c.execute("select * from tickets order by id desc") if can_see(me, r)]
    if (method, path) == ("GET", "/api/dashboard"):
        if me["role"] not in ("lead", "admin"): raise Err(403, "Management only")
        return 200, dashboard(c)
    if (method, path) == ("POST", "/api/sim/advance"):
        if me["role"] != "admin": raise Err(403, "Admin only")
        c.execute("update meta set v=v+? where k='offset'", (int(float(body.get("hours", 24)) * HR),)); sweep(c); return 200, {"ok": True}
    m = re.fullmatch(r"/api/tickets/(\d+)(?:/(\w+))?", path)
    if not m: raise Err(404, "Not found")
    r = c.execute("select * from tickets where id=?", (m[1],)).fetchone()
    if not r or not can_see(me, r): raise Err(404, "Ticket not found")
    act = m[2]; t = now(c)
    if method == "GET" and not act:
        d = ser(c, r)
        d["next"] = FLOW.get(r["status"], []) if staff else (["Open"] if r["status"] in ("Resolved", "Closed") else [])
        d["activity"] = [dict(a, actor=uname(c, a["actor_id"])) for a in c.execute(
            "select * from activity where ticket_id=? order by id desc", (r["id"],)) if staff or not a["internal"]]
        return 200, d
    if method != "POST": raise Err(404, "Not found")
    if act == "comment":
        text = (body.get("body") or "").strip(); internal = 1 if (body.get("internal") and staff) else 0
        if not text: raise Err(400, "Write a comment first")
        if r["status"] in ("Closed", "Rejected"): raise Err(400, "Reopen the ticket to add a comment")
        log(c, r["id"], me["id"], "comment", text, internal)
        if staff and not internal and not r["first_response_at"]:
            c.execute("update tickets set first_response_at=? where id=?", (t, r["id"]))
        if not staff and r["status"] == "Pending Student": set_status(c, r, "In Progress", me, "Student replied")
    elif act == "status":
        new, note, old = body.get("status"), (body.get("note") or "").strip(), r["status"]
        if staff and new not in FLOW.get(old, []): raise Err(400, f"A ticket can't move from {old} to {new}")
        if not staff:
            if not (new == "Open" and old in ("Resolved", "Closed")): raise Err(403, "You can only reopen a resolved ticket")
            if r["resolved_at"] and t - r["resolved_at"] > 7 * 86400: raise Err(400, "Tickets can be reopened for 7 days after resolution")
        if new in NEEDS_NOTE and len(note) < 3: raise Err(400, "Add a short note explaining this change")
        set_status(c, r, new, me, note)
    elif act == "assign":
        if not staff: raise Err(403, "Staff only")
        u = c.execute("select * from users where id=? and role in ('agent','lead')", (body.get("user_id"),)).fetchone()
        if not u: raise Err(400, "Choose a staff member")
        c.execute("update tickets set assignee_id=? where id=?", (u["id"], r["id"]))
        log(c, r["id"], me["id"], "assigned", f"Reassigned to {u['name']}")
    elif act == "escalate":
        if r["status"] in DONE: raise Err(400, "Closed or resolved tickets can't be escalated")
        lvl = min(3, r["escalation_level"] + 1)
        c.execute("update tickets set escalation_level=? where id=?", (lvl, r["id"]))
        log(c, r["id"], me["id"], "escalated", f"Manually escalated to L{lvl} ({LEVELS[lvl]}): " + ((body.get("reason") or "").strip() or "No reason given"))
    else: raise Err(404, "Not found")
    return 200, {"ok": True}


def init():
    if os.path.exists(DB): return
    c = db()
    c.executescript("""
    create table users(id integer primary key, name text, role text, team text);
    create table meta(k text primary key, v integer);
    create table tickets(id integer primary key, student_id int, category text, subject text, description text,
      priority text, status text, assignee_id int, created_at int, due_at int, first_response_at int, resolved_at int,
      escalation_level int default 0, pending_since int, resolution_note text, reopen_count int default 0);
    create table activity(id integer primary key, ticket_id int, actor_id int, action text, detail text, internal int default 0, ts int);
    create index ix_t_status on tickets(status); create index ix_a_ticket on activity(ticket_id);
    insert into meta values('offset',0);""")
    c.executemany("insert into users(name,role,team) values(?,?,?)", [
        ("Asha Nair", "student", None), ("Ravi Kumar", "student", None), ("Meera Iyer", "student", None),
        ("Kiran Rao", "agent", "Accounts"), ("Divya Menon", "agent", "Academics"), ("Imran Khan", "agent", "Administration"),
        ("Suresh Patel", "lead", "All"), ("Priya Sharma", "admin", "Management")])
    t = int(time.time()); ago = lambda h: t - int(h * HR)
    seeds = [(1, "Fees", "Fee paid but not reflected on portal", "I paid the tuition fee by UPI five days ago and the portal still shows it as due.", 30),
             (2, "Certificates", "Bonafide certificate for visa application", "I need a bonafide certificate for my visa appointment, please process quickly.", 60),
             (3, "Attendance", "Attendance shows 62% but I attended most classes", "Data structures attendance looks wrong for September. Please verify with the faculty.", 100),
             (1, "ID Card", "Lost ID card, need a duplicate", "I lost my ID card last week and need a replacement issued.", 2),
             (2, "Documents", "Hall ticket not downloadable", "The hall ticket download fails and my exam starts soon.", 3),
             (3, "Other", "Library no-dues form query", "Which office signs the library no-dues form?", 5)]
    for s in seeds: new_ticket(c, *s[:4], at=ago(s[4]))
    for tid, path, note in [(1, ["In Progress"], ""), (6, ["In Progress", "Resolved"], "Sign at the library counter, block B.")]:
        for st in path:
            r = c.execute("select * from tickets where id=?", (tid,)).fetchone()
            set_status(c, r, st, dict(c.execute("select * from users where id=?", (r["assignee_id"],)).fetchone()), note)
    c.commit(); c.close()


class H(BaseHTTPRequestHandler):
    def _run(self, method):
        u = urlparse(self.path)
        if method == "GET" and not u.path.startswith("/api"):
            data = open(os.path.join(HERE, "index.html"), "rb").read()
            self.send_response(200); self.send_header("Content-Type", "text/html; charset=utf-8")
            self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data); return
        n = int(self.headers.get("Content-Length") or 0)
        body = json.loads(self.rfile.read(n) or b"{}") if n else {}
        c = db()
        try:
            me = c.execute("select * from users where id=?", (self.headers.get("X-User-Id"),)).fetchone()
            code, out = handle(c, method, u.path, body, me); c.commit()
        except Err as e: c.rollback(); code, out = e.code, {"error": str(e)}
        except Exception as e: c.rollback(); code, out = 500, {"error": "Server error: " + str(e)}
        finally: c.close()
        data = json.dumps(out).encode()
        self.send_response(code); self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data))); self.end_headers(); self.wfile.write(data)

    def do_GET(self): self._run("GET")
    def do_POST(self): self._run("POST")
    def log_message(self, *a): pass


if __name__ == "__main__":
    init()
    print("Campus Help Desk running at http://localhost:8000  (Ctrl+C to stop)")
    ThreadingHTTPServer(("127.0.0.1", 8000), H).serve_forever()
