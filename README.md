# Assignment_4_-_Student_Support_and_Ticket_Management
Assignment 4 - Student Support and ticket management

# Campus Help Desk: Student Support & Ticket Management

A working prototype for Assignment 4 — Student Support & Ticket Management.

| Layer | Technology | File |
|---|---|---|
| Frontend | HTML, CSS, vanilla JavaScript (single page) | `index.html` |
| Backend | Python REST API (standard library only) | `server.py` |
| Database | SQLite (created automatically) | `tickets.db` |

No `pip install` or `npm install` is needed — only Python itself.

## How to run

1. **Install Python 3.8 or newer.** Check with `python --version` (on Mac/Linux you may need `python3 --version`). Download from python.org if missing. On Windows, tick "Add Python to PATH" during install.
2. **Put all project files in one folder** — `server.py`, `index.html`, and this `README.md`.
3. **Open a terminal in that folder** (Windows: type `cmd` in the folder's address bar, or use VS Code's built-in terminal with the folder open; Mac: right-click the folder → New Terminal at Folder).
4. **Start the server:**
   ```
   python server.py
   ```
   (Mac/Linux: `python3 server.py`)
5. **Open http://localhost:8000** in your browser.
6. **Stop with Ctrl+C.** To reset all data, stop the server, delete `tickets.db`, and start again — sample data is re-created automatically.

If port 8000 is busy, change `8000` in the last line of `server.py`.

## Demo script (about 5 minutes)

Use the "Signed in as" dropdown at the top of the sidebar to switch users. There are no passwords in the prototype.

1. **Asha Nair (student):** open *New request*, choose Fees, subject "Scholarship fee refund", description "Urgent, refund needed before deadline". Priority P2 and the Accounts agent are assigned automatically.
2. **Kiran Rao (agent):** open the ticket, set *In Progress*, then *Pending Student* with the note "Please upload receipt". The SLA shows *Paused*.
3. **Asha:** add a comment. The ticket returns to *In Progress* and the SLA resumes.
4. **Kiran:** add an *internal note* (Asha can't see it), then *Resolved* with a resolution note.
5. **Asha:** reopen it with a reason. Reopen count goes up and a fresh target starts.
6. **Priya Sharma (admin):** click *Skip ahead 1 day* a few times. Tickets cross 75% of SLA (L1), breach (L2) and breach by 2+ days (L3), and each escalation is logged automatically. Resolved tickets auto-close after 3 days.
7. **Suresh Patel (lead) or Priya:** open *Dashboard* for SLA compliance, ageing, workload, escalations and response times.

## How it maps to the assignment

| Requirement | Where |
|---|---|
| Statuses and workflow | `FLOW` in `server.py`: Open → In Progress → Pending (Student/Internal) → Resolved → Closed, plus Rejected and Reopen. Invalid moves are refused. |
| Priorities and SLAs | `SLA` dictionary (P1–P4, first response and resolution hours). Priority is auto-set from category and keywords in `prio()`. |
| Assignment and ownership | Category → team (`TEAM` dictionary), then the least-loaded agent. One owner at a time; reassignment is logged. |
| Ageing | Age in days on every ticket, plus ageing buckets on the dashboard. |
| Resolution tracking | Resolution note required to resolve, resolved time recorded, reopen count, SLA met/missed. |
| Activity history | Append-only `activity` table (created, assigned, status changes, comments, escalations). Internal notes are hidden from students. |
| Escalation | L1 at 75% of SLA (team lead), L2 on breach (department head), L3 at 2+ days overdue or a breached P1 (management). Manual escalation also available. |
| Pending-action workflows | Pending Student pauses the SLA clock and auto-resolves after 7 days of silence. Pending Internal keeps the clock running. |
| Management visibility | Dashboard: open tickets, SLA breaches, escalations, SLA compliance %, average response/resolution time, ageing, workload per agent. |
| Access control | Students see only their own tickets. Agents see their team's. Leads and admins see everything. |

## API summary

Every request sends the header `X-User-Id`.

| Method and path | Purpose |
|---|---|
| `GET /api/users` | List demo users |
| `GET /api/tickets` | Tickets visible to the current user |
| `POST /api/tickets` | Create a ticket (students) |
| `GET /api/tickets/<id>` | Ticket detail with history and allowed next statuses |
| `POST /api/tickets/<id>/status` | Change status (`status`, `note`) |
| `POST /api/tickets/<id>/comment` | Add a comment (`body`, `internal`) |
| `POST /api/tickets/<id>/assign` | Reassign (`user_id`) |
| `POST /api/tickets/<id>/escalate` | Manual escalation (`reason`) |
| `GET /api/dashboard` | Management metrics (lead and admin) |
| `POST /api/sim/advance` | Demo only: skip time forward (admin) |

## Database tables

- `users`: id, name, role (student/agent/lead/admin), team
- `tickets`: student, category, subject, description, priority, status, assignee, created/due/first-response/resolved times, escalation level, pending_since, resolution note, reopen count
- `activity`: ticket, actor, action, detail, internal flag, timestamp
- `meta`: the demo time offset (used by the "skip ahead" button)

## Configuration you can tune

All in `server.py` unless noted:

- **SLA targets** — `SLA` dictionary: `(first_response_hours, resolution_hours)` per priority.
- **Priority keywords** — `prio()`: the word lists that assign P1/P2 automatically.
- **Team routing** — `TEAM` dictionary: which department owns each category.
- **Auto-close / auto-resolve windows** — inside `sweep()`: `3 * 86400` (auto-close after 3 days) and `7 * 86400` (auto-resolve pending tickets after 7 days).
- **Escalation threshold** — inside `sweep()`: the `.75` (75% of SLA elapsed) trigger for L1.
- **Colors, icons, category list** — top of `index.html` (`:root` CSS variables, `CATI` icon map, `CATS` array).

## Known limits (worth mentioning in your write-up)

- Login is a user picker with no passwords. Production needs real authentication (SSO or JWT).
- SLA checks run on each request rather than a scheduled job — production would use cron or a task queue.
- SLA uses calendar hours, not business hours; holidays aren't excluded.
- No email/SMS notifications or file attachments yet.

## Project files

```
server.py            Backend: REST API, SQLite schema, SLA/escalation logic
index.html            Frontend: single-page UI (students, staff, management)
README.md             This file
ai_usage_report.docx  Mandatory AI usage report for submission
.gitignore             Excludes tickets.db from version control
```
