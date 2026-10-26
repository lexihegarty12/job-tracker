import json
import re
import sqlite3
import html
import urllib.request
from datetime import date, datetime
from pathlib import Path

import streamlit as st


APP_DIR = Path(__file__).parent
DATA_DIR = APP_DIR / "data"
DB_PATH = DATA_DIR / "job_tracker.db"
STATUSES = ["Applied / Waiting for update", "Saved", "Interviewing", "Offer", "Rejected", "Withdrawn"]
ACTIVE_STATUSES = ["Applied / Waiting for update", "Saved", "Interviewing", "Offer"]


def db():
    DATA_DIR.mkdir(exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute(
        """CREATE TABLE IF NOT EXISTS opportunities (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            company TEXT NOT NULL,
            title TEXT NOT NULL,
            link TEXT,
            location TEXT,
            deadline TEXT,
            status TEXT NOT NULL DEFAULT 'Applied / Waiting for update',
            priority TEXT NOT NULL DEFAULT 'Medium',
            next_action TEXT,
            next_action_due TEXT,
            source TEXT,
            network_contact TEXT,
            resume_version TEXT,
            cover_letter_version TEXT,
            job_description TEXT NOT NULL DEFAULT '',
            date_opened TEXT NOT NULL DEFAULT '',
            heard_back_follow_up TEXT NOT NULL DEFAULT '',
            second_final_interview_date TEXT NOT NULL DEFAULT '',
            interview_date TEXT,
            thank_you_sent INTEGER NOT NULL DEFAULT 0,
            notes TEXT,
            last_email_event TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )"""
    )
    existing_columns = {row[1] for row in conn.execute("PRAGMA table_info(opportunities)").fetchall()}
    migrations = {
        "job_description": "ALTER TABLE opportunities ADD COLUMN job_description TEXT NOT NULL DEFAULT ''",
        "date_opened": "ALTER TABLE opportunities ADD COLUMN date_opened TEXT NOT NULL DEFAULT ''",
        "heard_back_follow_up": "ALTER TABLE opportunities ADD COLUMN heard_back_follow_up TEXT NOT NULL DEFAULT ''",
        "second_final_interview_date": "ALTER TABLE opportunities ADD COLUMN second_final_interview_date TEXT NOT NULL DEFAULT ''",
    }
    for column, statement in migrations.items():
        if column not in existing_columns:
            conn.execute(statement)
        conn.commit()
    conn.execute("""UPDATE opportunities SET status = CASE status
        WHEN 'Saved' THEN 'Saved'
        WHEN 'Applied' THEN 'Applied / Waiting for update'
        WHEN 'Waiting for update' THEN 'Applied / Waiting for update'
        WHEN 'Offered position' THEN 'Offer'
        ELSE status END
        WHERE status IN ('Saved', 'Applied', 'Waiting for update', 'Offered position')""")
    conn.commit()
    return conn


def load_rows(conn):
    return [dict(r) for r in conn.execute("SELECT * FROM opportunities ORDER BY CASE status WHEN 'Offer' THEN 1 WHEN 'Interviewing' THEN 2 WHEN 'Applied / Waiting for update' THEN 3 WHEN 'Saved' THEN 4 WHEN 'Rejected' THEN 5 ELSE 6 END, COALESCE(deadline, '9999-12-31')").fetchall()]


def save_opportunity(conn, payload, row_id=None):
    now = datetime.now().isoformat(timespec="seconds")
    fields = ["company", "title", "link", "location", "deadline", "status", "priority", "next_action", "next_action_due", "source", "network_contact", "resume_version", "cover_letter_version", "job_description", "date_opened", "heard_back_follow_up", "second_final_interview_date", "interview_date", "thank_you_sent", "notes", "last_email_event"]
    values = [payload.get(f, "") for f in fields]
    if row_id:
        conn.execute("UPDATE opportunities SET " + ", ".join(f"{f}=?" for f in fields) + ", updated_at=? WHERE id=?", values + [now, row_id])
    else:
        conn.execute("INSERT INTO opportunities (" + ",".join(fields) + ",created_at,updated_at) VALUES (" + ",".join("?" for _ in fields) + ",?,?)", values + [now, now])
    conn.commit()


def parse_date(value):
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except Exception:
        return None


def import_job_link(url, status="Applied / Waiting for update"):
    """Read available job metadata from a real posting page; never invent fields."""
    request = urllib.request.Request(url.strip(), headers={"User-Agent": "Mozilla/5.0 JobTracker"})
    with urllib.request.urlopen(request, timeout=8) as response:
        page = response.read(800000).decode("utf-8", "ignore")
    scripts = re.findall(r'<script[^>]*type=["\']application/ld\+json["\'][^>]*>(.*?)</script>', page, re.I | re.S)
    structured = {}
    for script in scripts:
        try:
            candidate = json.loads(html.unescape(script.strip()))
            items = candidate if isinstance(candidate, list) else [candidate]
            for item in items:
                if isinstance(item, dict) and (item.get("@type") == "JobPosting" or "JobPosting" in item.get("@type", [])):
                    structured = item
                    break
        except (ValueError, TypeError):
            continue
    def meta(pattern):
        match = re.search(pattern, page, re.I | re.S)
        return html.unescape(match.group(1)).strip() if match else ""
    title = structured.get("title", "") or meta(r'<meta[^>]+(?:property|name)=["\'](?:og:title|twitter:title)["\'][^>]+content=["\'](.*?)["\']') or meta(r"<title[^>]*>(.*?)</title>")
    company = structured.get("hiringOrganization", {})
    company = company.get("name", "") if isinstance(company, dict) else ""
    location = structured.get("jobLocation", {})
    if isinstance(location, list):
        location = location[0] if location else {}
    address = location.get("address", {}) if isinstance(location, dict) else {}
    location_text = ", ".join(str(address.get(k, "")) for k in ("addressLocality", "addressRegion", "addressCountry") if address.get(k)) if isinstance(address, dict) else ""
    if structured.get("jobLocationType") == "TELECOMMUTE":
        location_text = "Remote" + (f" · {location_text}" if location_text else "")
    description = structured.get("description", "") or meta(r'<meta[^>]+(?:property|name)=["\'](?:og:description|description)["\'][^>]+content=["\'](.*?)["\']')
    description = html.unescape(description)
    description = re.sub(r"<\s*br\s*/?>|</\s*(p|div|h[1-6])\s*>", "\n\n", description, flags=re.I)
    description = re.sub(r"<\s*li[^>]*>", "\n• ", description, flags=re.I)
    description = re.sub(r"</\s*li\s*>", "\n", description, flags=re.I)
    description = re.sub(r"<[^>]+>", "", description)
    description = re.sub(r"\n{3,}", "\n\n", description).strip()
    opened = structured.get("datePosted", "")
    closes = structured.get("validThrough", "")
    return dict(company=company, title=title, link=url.strip(), location=location_text, deadline=closes[:10] if closes else "", date_opened=opened[:10] if opened else "", status=status, priority="Medium", next_action="Follow up on application", next_action_due=date.today().isoformat(), source="Imported from posting link", network_contact="", resume_version="", cover_letter_version="", job_description=description[:12000], interview_date="", thank_you_sent=0, notes="", last_email_event="", heard_back_follow_up="", second_final_interview_date="")


def save_uploaded_file(uploaded_file, prefix):
    if not uploaded_file:
        return ""
    folder = DATA_DIR / "documents"
    folder.mkdir(exist_ok=True)
    safe_name = re.sub(r"[^A-Za-z0-9._-]", "_", uploaded_file.name)
    target = folder / f"{prefix}_{safe_name}"
    target.write_bytes(uploaded_file.getvalue())
    return str(target.relative_to(APP_DIR))


def days_label(value):
    d = parse_date(value or "")
    if not d:
        return "No date"
    diff = (d - date.today()).days
    if diff < 0:
        return d.strftime("%b %-d")
    if diff == 0:
        return "Today"
    if diff == 1:
        return "Tomorrow"
    return f"in {diff}d"


def close_label(value):
    d = parse_date(value or "")
    if not d:
        return "—", ""
    diff = (d - date.today()).days
    if diff < 0:
        return d.strftime("%b %-d, %Y"), "closed"
    if diff == 0:
        return d.strftime("%b %-d, %Y"), "today"
    return d.strftime("%b %-d, %Y"), f"in {diff} days"


def css():
    st.markdown("""
    <style>
    html, body, [data-testid="stAppViewContainer"], [data-testid="stHeader"], [data-testid="stToolbar"], .stApp, .stApp * { font-family: Arial, sans-serif !important; }
    .stApp, [data-testid="stAppViewContainer"], [data-testid="stHeader"], [data-testid="stToolbar"] { background: #ffffff !important; color: #000000 !important; }
    .block-container { max-width: 1400px; padding-top: 2rem; }
    h1, h2, h3, p, label, [data-testid="stMarkdownContainer"] { color: #000000; letter-spacing: -0.02em; }
    .hero { background: #ffffff; color:#000000; padding:.5rem 0 1.25rem; border-bottom:2px solid #000000; border-radius:0; margin-bottom:1.2rem; }
    .hero h1 { color:#000000; margin:0; font-size:2.65rem; }
    .hero p { color:#000000; margin:.4rem 0 0; font-size:1.05rem; }
    .metric { background:#ffffff; border:1px solid #000000; border-radius:16px; padding:1rem 1.15rem; min-height:100px; }
    .metric .num { font-size:2rem; font-weight:750; color:#000000; }
    .metric .label { color:#000000; font-size:.85rem; }
    .sheet-summary { display:flex; gap:0; border:1px solid #000; border-radius:12px; overflow:hidden; margin:.75rem 0 1.25rem; }
    .sheet-summary-item { flex:1; padding:.8rem 1rem; border-right:1px solid #000; background:#fafafa; }
    .sheet-summary-item:last-child { border-right:0; }
    .sheet-summary-item .value { font-size:1.55rem; font-weight:750; line-height:1.1; }
    .sheet-summary-item .label { font-size:.75rem; color:#444; margin-top:.25rem; }
    .task-card { background:#ffffff; border:1px solid #000000; border-left:5px solid #000000; border-radius:12px; padding:.75rem 1rem; margin:.45rem 0; }
    .task-card strong { color:#000000; }
    .task-card p { margin:.25rem 0; }
    .section-kicker { text-transform:uppercase; letter-spacing:.11em; font-size:.72rem; font-weight:750; color:#555; margin:1.5rem 0 .5rem; }
    .empty-card { border:1px dashed #999; padding:1.25rem; border-radius:12px; color:#444; background:#fafafa; }
    .status-pill { display:inline-block; border:1px solid #222; border-radius:999px; padding:.18rem .55rem; font-size:.72rem; font-weight:700; background:#fff; }
    .progress-track { height:10px; background:#e5e5e5; border-radius:20px; overflow:hidden; }
    .progress-fill { height:100%; background:#000; border-radius:20px; }
    .muted { color:#333333; font-size:.85rem; }
    .tag { display:inline-block; border:1px solid #000000; border-radius:100px; padding:.18rem .55rem; font-size:.75rem; font-weight:650; background:#ffffff; color:#000000; }
    .stButton > button, .stDownloadButton > button { background:#ffffff; color:#000000; border:1px solid #000000; }
    .stButton > button:hover, .stDownloadButton > button:hover { background:#f2f2f2; color:#000000; border-color:#000000; }
    button[kind="primary"], [data-testid="stFormSubmitButton"] button { background:#000000 !important; color:#ffffff !important; border:1px solid #000000 !important; min-height:44px !important; }
    button[kind="primary"]:hover, [data-testid="stFormSubmitButton"] button:hover { background:#333333 !important; color:#ffffff !important; }
    [data-testid="stAlert"] { background:#ffffff !important; color:#000000 !important; border:1px solid #000000 !important; }
    [data-testid="stProgressBar"] > div > div { background-color:#000000; }
    [data-baseweb="tab-highlight"] { background-color:#000000; }
    [data-baseweb="select"] > div, input, textarea, [data-testid="stFileUploaderDropzone"] { background:#ffffff !important; color:#000000 !important; border-color:#000000 !important; }
    input[type="radio"] { accent-color:#000000 !important; }
    [data-testid="stRadio"] { filter: grayscale(1) contrast(1.2); }
    input::placeholder, textarea::placeholder { color:#667085 !important; opacity:1 !important; }
    [data-testid="stFileUploaderDropzone"] { background:#ffffff !important; border:1px solid #000000 !important; min-height:74px !important; }
    [data-testid="stFileUploaderDropzone"] button { background:#ffffff !important; color:#000000 !important; border:1px solid #000000 !important; min-height:44px !important; padding:0 16px !important; font-size:0 !important; }
    [data-testid="stFileUploaderDropzone"] button::after { content:"Upload"; color:#000000 !important; font-size:16px !important; font-weight:600 !important; }
    [data-testid="stFileUploaderDropzone"] button * { display:none !important; }
    [data-testid="stFileUploaderDropzone"] button:hover { background:#f2f2f2 !important; color:#000000 !important; }
    [data-testid="stFileUploaderDropzone"] button svg { display:none !important; }
    [data-testid="stFileUploaderDropzone"] small { color:#4b5563 !important; font-size:16px !important; opacity:1 !important; }
    [data-testid="stFormSubmitButton"] button, [data-testid="stFormSubmitButton"] button p, [data-testid="stFormSubmitButton"] button span, button[kind="primary"], button[kind="primary"] p, button[kind="primary"] span { background:#000000 !important; color:#ffffff !important; border-color:#000000 !important; }
    [data-testid="stCheckbox"] input { width:20px !important; height:20px !important; accent-color:#000000 !important; }
    [data-testid="stCheckbox"] [role="checkbox"] { width:20px !important; height:20px !important; background:#ffffff !important; border:2px solid #000000 !important; border-radius:3px !important; }
    [data-testid="stCheckbox"] [role="checkbox"][aria-checked="true"] { background:#000000 !important; }
    [data-testid="stCheckbox"] [role="checkbox"][aria-checked="true"] svg { color:#ffffff !important; fill:#ffffff !important; }
    [data-testid="stDataEditor"] { font-size:19px !important; color:#000000 !important; }
    [data-testid="stDataEditor"] [role="columnheader"] { background:#f1f5f9 !important; color:#334155 !important; font-size:17px !important; font-weight:700 !important; line-height:1.35 !important; border-bottom:1px solid #cbd5e1 !important; }
    [data-testid="stDataEditor"] [role="gridcell"] { background:#ffffff !important; color:#000000 !important; border-bottom:1px solid #e2e8f0 !important; border-right:0 !important; min-height:72px !important; line-height:1.45 !important; }
    [data-testid="stDataEditor"] a { color:#173b5e !important; }
    .st-key-description-panel { position:sticky; top:1rem; max-height:80vh; overflow-y:auto; padding:1rem; border-left:1px solid #e2e8f0; background:#ffffff; }
    .job-description-full { max-width:750px; color:#000000; font-size:18px; line-height:1.6; overflow-wrap:anywhere; }
    @media (max-width: 800px) { [data-testid="stDataEditor"] { font-size:16px !important; } }
    </style>
    """, unsafe_allow_html=True)


def kpi(label, value):
    st.markdown(f'<div class="metric"><div class="num">{value}</div><div class="label">{label}</div></div>', unsafe_allow_html=True)


def opportunity_card(row):
    due = days_label(row.get("next_action_due"))
    priority = row.get("priority", "Medium")
    st.markdown(
        f'<div class="task-card"><strong>{html.escape(row.get("company", ""))}</strong> · {html.escape(row.get("title", ""))}'
        f'<p>{html.escape(row.get("next_action") or "Choose the next move")} <span class="tag">{html.escape(priority)}</span></p>'
        f'<span class="muted">Due {html.escape(due)} · {html.escape(row.get("status", ""))}</span></div>',
        unsafe_allow_html=True,
    )


def dashboard(conn, rows):
    today = date.today()
    active = [r for r in rows if r.get("status") in ACTIVE_STATUSES]
    due_soon = [r for r in active if parse_date(r.get("next_action_due", "")) and 0 <= (parse_date(r.get("next_action_due", "")) - today).days <= 7]
    interviews = [r for r in active if r.get("status") == "Interviewing"]
    applications = [r for r in rows if r.get("status") in ("Applied / Waiting for update", "Interviewing", "Offer")]

    st.markdown('<div class="hero"><h1>This week</h1></div>', unsafe_allow_html=True)

    c1, c2, c3, c4 = st.columns(4)
    with c1: kpi("Active opportunities", len(active))
    with c2: kpi("Actions due this week", len(due_soon))
    with c3: kpi("Interviews in motion", len(interviews))
    with c4: kpi("Applications sent", len(applications))

    left, right = st.columns([1.45, 1], gap="large")
    with left:
        st.markdown('<div class="section-kicker">Your next moves</div>', unsafe_allow_html=True)
        action_rows = sorted(due_soon, key=lambda r: r.get("next_action_due") or "9999-12-31")
        if action_rows:
            for row in action_rows[:8]:
                opportunity_card(row)
        else:
            st.markdown('<div class="empty-card">No actions due in the next 7 days. Add a new opportunity or move a saved role forward.</div>', unsafe_allow_html=True)
        st.markdown('<div class="section-kicker">Quick capture</div>', unsafe_allow_html=True)
        q1, q2 = st.columns(2)
        with q1:
            if st.button("＋ Add a job", use_container_width=True, type="primary"):
                st.session_state["next_view"] = "Add job"; st.rerun()
        with q2:
            if st.button("View the spreadsheet", use_container_width=True):
                st.session_state["next_view"] = "Job spreadsheet"; st.rerun()
    with right:
        st.markdown('<div class="section-kicker">Search health</div>', unsafe_allow_html=True)
        stage_counts = {status: len([r for r in rows if r.get("status") == status]) for status in STATUSES}
        total = max(len(rows), 1)
        for status in ["Saved", "Applied / Waiting for update", "Interviewing", "Offer"]:
            count = stage_counts.get(status, 0)
            st.markdown(f'<p style="margin:.65rem 0 .2rem"><strong>{html.escape(status)}</strong><span style="float:right">{count}</span></p><div class="progress-track"><div class="progress-fill" style="width:{min(100, count/total*100):.0f}%"></div></div>', unsafe_allow_html=True)


def opportunity_form(conn, existing=None, key="form"):
    r = existing or {}
    with st.form(key, clear_on_submit=not existing):
        st.subheader("Edit opportunity" if existing else "Add opportunity")
        c1, c2 = st.columns(2)
        company = c1.text_input("Company *", r.get("company", ""))
        title = c2.text_input("Role / internship title *", r.get("title", ""))
        link = st.text_input("Posting link", r.get("link", ""), placeholder="https://...")
        c1, c2, c3 = st.columns(3)
        location = c1.text_input("Location / work arrangement", r.get("location", ""), placeholder="Remote · US")
        deadline = c2.date_input("Application deadline", parse_date(r.get("deadline", "")) or date.today(), format="YYYY-MM-DD")
        status = c3.selectbox("Stage", STATUSES, index=STATUSES.index(r.get("status", "Applied / Waiting for update")) if r.get("status") in STATUSES else 0)
        c1, c2, c3 = st.columns(3)
        priority = c1.selectbox("Priority", ["High", "Medium", "Low"], index=["High", "Medium", "Low"].index(r.get("priority", "Medium")))
        next_action = c2.text_input("Next action", r.get("next_action", ""), placeholder="What is the very next move?")
        next_due = c3.date_input("Next action due", parse_date(r.get("next_action_due", "")) or date.today(), format="YYYY-MM-DD")
        job_description = st.text_area("Job description", r.get("job_description", ""), height=180, placeholder="Paste the full job description here.")
        st.markdown("**Career Services fields**")
        c1, c2 = st.columns(2)
        source = c1.text_input("How did you find it?", r.get("source", ""), placeholder="LinkedIn, career fair, alum...")
        network_contact = c2.text_input("Network connection", r.get("network_contact", ""))
        c1, c2 = st.columns(2)
        resume_file = c1.file_uploader("Resume submitted", type=["pdf", "doc", "docx"], key=f"resume-{key}")
        cover_file = c2.file_uploader("Cover letter submitted", type=["pdf", "doc", "docx"], key=f"cover-{key}")
        c1, c2, c3 = st.columns(3)
        c1.caption(f"Saved file: {Path(r['resume_version']).name}" if r.get("resume_version") else "No resume uploaded")
        c2.caption(f"Saved file: {Path(r['cover_letter_version']).name}" if r.get("cover_letter_version") else "No cover letter uploaded")
        thank_you = c3.checkbox("Thank-you note sent", bool(r.get("thank_you_sent", 0)))
        notes = st.text_area("Notes", r.get("notes", ""), height=100)
        submitted = st.form_submit_button("Save opportunity", type="primary", use_container_width=True)
        if submitted:
            if not company.strip() or not title.strip():
                st.error("Add a company and role title first.")
                return False
            resume_path = save_uploaded_file(resume_file, f"resume_{company.strip().lower().replace(' ', '_')}") or r.get("resume_version", "")
            cover_path = save_uploaded_file(cover_file, f"cover_letter_{company.strip().lower().replace(' ', '_')}") or r.get("cover_letter_version", "")
            payload = dict(company=company.strip(), title=title.strip(), link=link.strip(), location=location.strip(), deadline=deadline.isoformat(), status=status, priority=priority, next_action=next_action.strip(), next_action_due=next_due.isoformat(), source=source.strip(), network_contact=network_contact.strip(), resume_version=resume_path, cover_letter_version=cover_path, job_description=job_description.strip(), date_opened=r.get("date_opened", ""), heard_back_follow_up=r.get("heard_back_follow_up", ""), second_final_interview_date=r.get("second_final_interview_date", ""), interview_date=r.get("interview_date", ""), thank_you_sent=int(thank_you), notes=notes.strip(), last_email_event=r.get("last_email_event", ""))
            save_opportunity(conn, payload, r.get("id"))
            st.session_state["next_view"] = "Job spreadsheet"
            st.success("Saved. Opening opportunities.")
            st.rerun()
    return True


def main():
    st.set_page_config(page_title="JobTracker", page_icon="◈", layout="wide")
    css()
    conn = db()
    rows = load_rows(conn)
    st.markdown('<div class="hero"><h1>JobTracker</h1></div>', unsafe_allow_html=True)
    if "next_view" in st.session_state:
        st.session_state["view"] = st.session_state.pop("next_view")
    views = ["Today", "Add job", "Job spreadsheet", "Application statuses"]
    view = st.radio("Navigate", views, horizontal=True, label_visibility="collapsed", key="view")

    if view == "Today":
        dashboard(conn, rows)

    elif view == "Add job":
        st.subheader("Add a job")
        st.caption("Paste a posting link to import available job fields, then review and save.")
        link_to_import = st.text_input("Posting link to import", placeholder="https://company.com/jobs/123")
        if st.button("Import link", type="primary"):
            if not link_to_import.strip().startswith(("http://", "https://")):
                st.error("Enter a valid http:// or https:// posting link.")
            else:
                try:
                    st.session_state["draft"] = import_job_link(link_to_import)
                    if not st.session_state["draft"].get("title") and not st.session_state["draft"].get("company") and not st.session_state["draft"].get("job_description"):
                        st.warning("The page loaded but did not expose job fields. Review the link and enter the details manually.")
                    else:
                        st.success("Available job fields imported. Review them before saving.")
                except Exception:
                    st.error("This posting could not be read automatically. Enter the details manually or use another posting link.")
        if "draft" in st.session_state:
            opportunity_form(conn, st.session_state["draft"], key="draft-form")
        else:
            opportunity_form(conn, key="new-form")

    elif view == "Job spreadsheet":
        st.subheader("Job spreadsheet")
        applied_count = len([r for r in rows if r.get("status") in ("Applied / Waiting for update", "Interviewing", "Offer")])
        waiting_count = len([r for r in rows if r.get("status") == "Applied / Waiting for update"])
        interview_count = len([r for r in rows if r.get("status") == "Interviewing"])
        offer_count = len([r for r in rows if r.get("status") == "Offer"])
        st.markdown(
            f'<div class="sheet-summary"><div class="sheet-summary-item"><div class="value">{applied_count}</div><div class="label">Jobs applied to</div></div>'
            f'<div class="sheet-summary-item"><div class="value">{waiting_count}</div><div class="label">Awaiting response</div></div>'
            f'<div class="sheet-summary-item"><div class="value">{interview_count}</div><div class="label">Interviews</div></div>'
            f'<div class="sheet-summary-item"><div class="value">{offer_count}</div><div class="label">Offers</div></div></div>',
            unsafe_allow_html=True,
        )
        c1, c2, c3 = st.columns([2, 1, 1])
        search = c1.text_input("Search company, role, notes, or contact", placeholder="Try: analytics, Maya, remote")
        filter_status = c2.selectbox("Stage", ["All"] + STATUSES)
        filter_priority = c3.selectbox("Priority", ["All", "High", "Medium", "Low"])
        filtered = [r for r in rows if (not search or search.lower() in json.dumps(r).lower()) and (filter_status == "All" or r["status"] == filter_status) and (filter_priority == "All" or r["priority"] == filter_priority)]
        st.caption(f"Showing {len(filtered)} of {len(rows)} opportunities · active roles sort above archived outcomes")

        columns = [
            "Company", "Role", "Location", "Posting link", "Opened", "Closes",
            "Application Status", "Priority", "Next action", "Next action due",
            "How did you find it?", "Network connection", "Resume submitted",
            "Cover letter submitted", "Job description", "Follow-up date",
            "Second/final interview date", "Interview date", "Thank-you note sent",
            "Notes", "Last email event",
        ]
        table_rows = []
        for r in filtered:
            close_text, close_note = close_label(r.get("deadline"))
            close_value = f"{close_text} ({close_note})" if close_note else close_text
            resume_path = APP_DIR / r["resume_version"] if r.get("resume_version") else None
            cover_path = APP_DIR / r["cover_letter_version"] if r.get("cover_letter_version") else None
            table_rows.append({
                "Company": r.get("company") or "",
                "Role": r.get("title") or "",
                "Location": r.get("location") or "",
                "Posting link": r.get("link") or "",
                "Opened": r.get("date_opened") or "",
                "Closes": close_value,
                "Application Status": r.get("status") or "Applied / Waiting for update",
                "Priority": r.get("priority") or "",
                "Next action": r.get("next_action") or "",
                "Next action due": r.get("next_action_due") or "",
                "How did you find it?": r.get("source") or "",
                "Network connection": r.get("network_contact") or "",
                "Resume submitted": resume_path.name if resume_path and resume_path.exists() else "",
                "Cover letter submitted": cover_path.name if cover_path and cover_path.exists() else "",
                "Job description": r.get("job_description") or "",
                "Follow-up date": r.get("heard_back_follow_up") or "",
                "Second/final interview date": r.get("second_final_interview_date") or "",
                "Interview date": r.get("interview_date") or "",
                "Thank-you note sent": "Yes" if r.get("thank_you_sent") else "No",
                "Notes": r.get("notes") or "",
                "Last email event": r.get("last_email_event") or "",
            })

        left, right = st.columns([3, 2], gap="large")
        with left:
            edited_table = st.data_editor(
                table_rows,
                column_order=columns,
                hide_index=True,
                use_container_width=True,
                height=700,
                row_height=80,
                disabled=[column for column in columns if column != "Application Status"],
                column_config={
                    "Company": st.column_config.TextColumn("Company", width="medium"),
                    "Role": st.column_config.TextColumn("Role", width="large"),
                    "Location": st.column_config.TextColumn("Location", width="medium"),
                    "Posting link": st.column_config.LinkColumn("Posting link", display_text="Open posting", width="medium"),
                    "Opened": st.column_config.TextColumn("Opened", width="small"),
                    "Closes": st.column_config.TextColumn("Closes", width="small"),
                    "Application Status": st.column_config.SelectboxColumn("Application Status", options=STATUSES, required=True, width="medium"),
                    "Priority": st.column_config.TextColumn("Priority", width="small"),
                    "Next action": st.column_config.TextColumn("Next action", width="large"),
                    "Next action due": st.column_config.TextColumn("Next action due", width="small"),
                    "How did you find it?": st.column_config.TextColumn("How did you find it?", width="medium"),
                    "Network connection": st.column_config.TextColumn("Network connection", width="medium"),
                    "Resume submitted": st.column_config.TextColumn("Resume submitted", width="medium"),
                    "Cover letter submitted": st.column_config.TextColumn("Cover letter submitted", width="medium"),
                    "Job description": st.column_config.TextColumn("Job description", width="large"),
                    "Follow-up date": st.column_config.TextColumn("Follow-up date", width="small"),
                    "Second/final interview date": st.column_config.TextColumn("Second/final interview date", width="small"),
                    "Interview date": st.column_config.TextColumn("Interview date", width="small"),
                    "Thank-you note sent": st.column_config.TextColumn("Thank-you note sent", width="small"),
                    "Notes": st.column_config.TextColumn("Notes", width="large"),
                    "Last email event": st.column_config.TextColumn("Last email event", width="large"),
                },
                key="job-spreadsheet",
            )

            edited_rows = edited_table.to_dict("records")
            changed = False
            for index, edited_row in enumerate(edited_rows):
                if index < len(filtered) and edited_row.get("Application Status") != filtered[index].get("status"):
                    new_status = edited_row.get("Application Status")
                    if new_status in STATUSES:
                        conn.execute("UPDATE opportunities SET status=?, updated_at=? WHERE id=?", (new_status, datetime.now().isoformat(timespec="seconds"), filtered[index]["id"]))
                        changed = True
            if changed:
                conn.commit()
                st.rerun()

        selected_index = 0
        if filtered:
            selected_index = min(selected_index, len(filtered) - 1)
            selected_job = filtered[selected_index]
        else:
            selected_job = None

        with right.container(key="description-panel", height=700):
            if selected_job:
                st.subheader(selected_job.get("company") or "Company")
                st.markdown(f"**Role:** {html.escape(selected_job.get('title') or '—')}  \n**Location:** {html.escape(selected_job.get('location') or '—')}  \n**Closes:** {html.escape(close_label(selected_job.get('deadline'))[0])}", unsafe_allow_html=True)
                if selected_job.get("link"):
                    st.markdown(f"[Open original posting]({selected_job['link']})")
                status = st.selectbox("Application Status", STATUSES, index=STATUSES.index(selected_job.get("status")) if selected_job.get("status") in STATUSES else 0, key=f"panel-status-{selected_job['id']}")
                if status != selected_job.get("status"):
                    conn.execute("UPDATE opportunities SET status=?, updated_at=? WHERE id=?", (status, datetime.now().isoformat(timespec="seconds"), selected_job["id"]))
                    conn.commit()
                    st.rerun()
                st.markdown("---")
                description = selected_job.get("job_description") or ""
                if description.strip():
                    st.markdown('<div class="job-description-full">' + html.escape(description).replace("\n", "<br>") + "</div>", unsafe_allow_html=True)
                else:
                    st.info("No description saved")
                    pasted_description = st.text_area("Paste job description", height=260, key=f"paste-description-{selected_job['id']}")
                    if st.button("Save description", key=f"save-description-{selected_job['id']}", type="primary"):
                        conn.execute("UPDATE opportunities SET job_description=?, updated_at=? WHERE id=?", (pasted_description.strip(), datetime.now().isoformat(timespec="seconds"), selected_job["id"]))
                        conn.commit()
                        st.rerun()
            else:
                st.info("No opportunities match the current filters.")

    elif view == "Application statuses":
        st.subheader("Application statuses")
        st.caption("Move each opportunity forward by keeping the next action visible.")
        board_statuses = ["Saved", "Applied / Waiting for update", "Interviewing", "Offer"]
        board = st.columns(4, gap="small")
        for column, status in zip(board, board_statuses):
            with column:
                matching = [r for r in rows if r.get("status") == status]
                st.markdown(f'<div class="section-kicker">{html.escape(status)} · {len(matching)}</div>', unsafe_allow_html=True)
                if matching:
                    for row in matching:
                        opportunity_card(row)
                        if row.get("link"):
                            st.link_button("Open posting", row["link"], use_container_width=True)
                        if st.button("Edit", key=f"board-edit-{row['id']}", use_container_width=True):
                            st.session_state["edit_id"] = row["id"]
                            st.session_state["next_view"] = "Job spreadsheet"
                            st.rerun()
                else:
                    st.markdown('<div class="empty-card">Nothing here yet.</div>', unsafe_allow_html=True)



if __name__ == "__main__":
    main()
