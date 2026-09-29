"""
FastAPI Backend Application for MPLADS Management, Monitoring & Transparency Platform.
Serves API endpoints and static frontend for the MVP prototype.
"""
import os
import sqlite3
import datetime
from typing import Optional, List
from fastapi import FastAPI, Query, HTTPException, Depends
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field

from backend.database import (
    HISTORICAL_DB_PATH,
    LIVE_DB_PATH,
    get_historical_db,
    get_live_db,
    init_live_db
)

app = FastAPI(
    title="Nirakshan MPLADS Platform",
    description="MPLADS Monitoring, Management & Citizen Transparency Portal",
    version="1.0.0"
)

# Enable CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize live database tables and demo seed data on startup
init_live_db()

# --- Pydantic Request Models ---
class RecommendWorkRequest(BaseModel):
    title: str = Field(..., min_length=3, max_length=250)
    description: Optional[str] = ""
    work_category: str = Field(...)
    state: str = Field(...)
    district: str = Field(...)
    constituency: str = Field(...)
    location: Optional[str] = ""
    priority: str = Field(default="Medium")
    beneficiary_purpose: Optional[str] = ""
    estimated_amount: float = Field(..., gt=0)
    recommending_mp_name: str = Field(...)
    recommending_mp_id: Optional[int] = None

class ReviewWorkRequest(BaseModel):
    work_id: str
    action: str = Field(..., pattern="^(APPROVE|RETURN)$")
    sanction_amount: Optional[float] = None
    assigned_agency_id: Optional[int] = None
    assigned_agency_name: Optional[str] = None
    review_comments: Optional[str] = ""

class UpdateProgressRequest(BaseModel):
    work_id: str
    physical_progress_pct: int = Field(..., ge=0, le=100)
    status: str = Field(..., pattern="^(IN_PROGRESS|COMPLETED)$")
    current_milestone: Optional[str] = "Execution / Civil Work"
    description: str = Field(..., min_length=3)
    expenditure_incurred: Optional[float] = Field(default=0.0, ge=0)
    payment_notes: Optional[str] = ""


# --- API Routes ---

@app.get("/api/auth/roles")
def get_demo_roles(db: sqlite3.Connection = Depends(get_live_db)):
    """Returns available stakeholder personas for testing the MVP."""
    cursor = db.cursor()
    cursor.execute("SELECT id, username, full_name, email, role, state, district, constituency, agency_name, designation FROM users")
    users = [dict(row) for row in cursor.fetchall()]
    return {
        "roles": [
            {"key": "citizen", "label": "Citizen / Public — Demo User", "description": "Public Read-Only Transparency Access"},
            {"key": "mp", "label": "MP Portal — Demo User", "description": "Recommend & Track Constituency Works"},
            {"key": "district_authority", "label": "District Authority — Demo User", "description": "Review, Sanction & Monitor Works"},
            {"key": "implementing_agency", "label": "Implementing Agency — Demo User", "description": "Execute & Update Physical/Financial Progress"}
        ],
        "demo_users": users
    }


@app.get("/api/metadata/geography")
def get_geography_metadata(
    h_db: sqlite3.Connection = Depends(get_historical_db),
    l_db: sqlite3.Connection = Depends(get_live_db)
):
    """Provides dynamic lists of real states, districts, constituencies, MPs, and categories from datasets."""
    h_cur = h_db.cursor()
    l_cur = l_db.cursor()

    h_cur.execute("SELECT DISTINCT state FROM historical_projects WHERE state IS NOT NULL ORDER BY state ASC")
    states = [r[0] for r in h_cur.fetchall()]

    h_cur.execute("SELECT DISTINCT district, state FROM historical_projects WHERE district IS NOT NULL ORDER BY district ASC")
    districts = [{"district": r[0], "state": r[1]} for r in h_cur.fetchall()]

    h_cur.execute("SELECT DISTINCT constituency, district, state FROM historical_projects WHERE constituency IS NOT NULL ORDER BY constituency ASC")
    constituencies = [{"constituency": r[0], "district": r[1], "state": r[2]} for r in h_cur.fetchall()]

    h_cur.execute("SELECT DISTINCT mp_name, constituency, state FROM historical_projects WHERE mp_name IS NOT NULL ORDER BY mp_name ASC")
    mps = [{"mp_name": r[0], "constituency": r[1], "state": r[2]} for r in h_cur.fetchall()]

    h_cur.execute("SELECT DISTINCT work_category FROM historical_projects WHERE work_category IS NOT NULL ORDER BY work_category ASC")
    categories = [r[0] for r in h_cur.fetchall()]

    l_cur.execute("SELECT id, agency_name, full_name, designation FROM users WHERE role = 'implementing_agency'")
    agencies = [dict(r) for r in l_cur.fetchall()]

    return {
        "states": states,
        "districts": districts,
        "constituencies": constituencies,
        "mps": mps,
        "categories": categories,
        "agencies": agencies
    }


@app.get("/api/analytics/overview")
def get_analytics_overview(
    h_db: sqlite3.Connection = Depends(get_historical_db),
    l_db: sqlite3.Connection = Depends(get_live_db)
):
    """Returns real dataset summary statistics + live updates."""
    h_cur = h_db.cursor()
    l_cur = l_db.cursor()

    # Historical stats
    h_cur.execute("""
        SELECT 
            COUNT(*) as total_projects,
            SUM(sanction_amount) as total_sanction,
            SUM(CASE WHEN work_completion_status = 'COMPLETED' THEN 1 ELSE 0 END) as completed,
            SUM(CASE WHEN work_completion_status != 'COMPLETED' THEN 1 ELSE 0 END) as ongoing
        FROM historical_projects
    """)
    h_row = dict(h_cur.fetchone())

    # Historical payment stats calculated from actual payment events table
    h_cur.execute("""
        SELECT 
            COUNT(*) as total_payment_events,
            SUM(reported_fund_disbursed_amount) as total_disbursed
        FROM historical_payment_events
    """)
    h_pay_row = dict(h_cur.fetchone())

    # Live stats
    l_cur.execute("""
        SELECT 
            COUNT(*) as live_total,
            SUM(CASE WHEN status = 'COMPLETED' THEN 1 ELSE 0 END) as live_completed,
            SUM(sanction_amount) as live_sanction,
            SUM(total_disbursed) as live_disbursed
        FROM live_works
    """)
    l_row = dict(l_cur.fetchone())

    # Live payment events count
    l_cur.execute("SELECT COUNT(*) FROM live_payments")
    live_payment_events_count = l_cur.fetchone()[0]

    # State-wise distribution
    h_cur.execute("""
        SELECT 
            state, 
            COUNT(*) as project_count,
            SUM(sanction_amount) as total_sanction,
            SUM(total_disbursed) as total_disbursed,
            SUM(CASE WHEN work_completion_status = 'COMPLETED' THEN 1 ELSE 0 END) as completed_count
        FROM historical_projects
        GROUP BY state
        ORDER BY project_count DESC
    """)
    state_breakdown = [dict(r) for r in h_cur.fetchall()]

    # Execution status breakdown
    h_cur.execute("""
        SELECT portal_execution_status as status, COUNT(*) as count
        FROM historical_projects
        GROUP BY portal_execution_status
        ORDER BY count DESC
    """)
    status_breakdown = [dict(r) for r in h_cur.fetchall()]

    # Categories breakdown
    h_cur.execute("""
        SELECT work_category as category, COUNT(*) as count, SUM(sanction_amount) as total_sanction
        FROM historical_projects
        GROUP BY work_category
    """)
    category_breakdown = [dict(r) for r in h_cur.fetchall()]

    total_works = (h_row['total_projects'] or 0) + (l_row['live_total'] or 0)
    total_sanction = (h_row['total_sanction'] or 0.0) + (l_row['live_sanction'] or 0.0)
    total_disbursed = (h_pay_row['total_disbursed'] or 0.0) + (l_row['live_disbursed'] or 0.0)
    total_payment_events = (h_pay_row['total_payment_events'] or 0) + live_payment_events_count
    completed_works = (h_row['completed'] or 0) + (l_row['live_completed'] or 0)
    ongoing_works = total_works - completed_works

    return {
        "kpis": {
            "total_works": total_works,
            "total_payment_events": total_payment_events,
            "total_sanction_amount": total_sanction,
            "total_disbursed_amount": total_disbursed,
            "completed_works": completed_works,
            "ongoing_works": ongoing_works,
            "completion_rate_pct": round((completed_works / total_works * 100), 1) if total_works else 0,
            "live_works_count": l_row['live_total'] or 0
        },
        "state_breakdown": state_breakdown,
        "status_breakdown": status_breakdown,
        "category_breakdown": category_breakdown
    }


@app.get("/api/works")
@app.get("/api/public/works")
def get_works(
    q: Optional[str] = Query(None, description="Search keyword in title, work_id, description, or mp_name"),
    state: Optional[str] = Query(None),
    district: Optional[str] = Query(None),
    constituency: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    scope: str = Query("all", description="all, live, historical"),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    h_db: sqlite3.Connection = Depends(get_historical_db),
    l_db: sqlite3.Connection = Depends(get_live_db)
):
    """Unified public work search, filter & summary metrics API across connected datasets."""
    items = []
    total_count = 0
    offset = (page - 1) * limit

    def is_valid_filter(val):
        if not val or not isinstance(val, str):
            return False
        v = val.strip().lower()
        return v != "" and not v.startswith("all")

    # 1. Query Live Works if scope in ('all', 'live')
    live_records = []
    l_sum_sanc = 0.0
    l_sum_disb = 0.0
    l_cnt_comp = 0
    if scope in ("all", "live"):
        l_cur = l_db.cursor()
        l_conditions = []
        l_params = []

        if q and q.strip():
            l_conditions.append("(work_id LIKE ? OR title LIKE ? OR description LIKE ? OR recommending_mp_name LIKE ?)")
            q_pat = f"%{q.strip()}%"
            l_params.extend([q_pat, q_pat, q_pat, q_pat])
        if is_valid_filter(state):
            l_conditions.append("UPPER(state) = UPPER(?)")
            l_params.append(state.strip())
        if is_valid_filter(district):
            l_conditions.append("UPPER(district) = UPPER(?)")
            l_params.append(district.strip())
        if is_valid_filter(constituency):
            l_conditions.append("UPPER(constituency) = UPPER(?)")
            l_params.append(constituency.strip())
        if is_valid_filter(category):
            l_conditions.append("UPPER(work_category) = UPPER(?)")
            l_params.append(category.strip())
        if is_valid_filter(status):
            l_conditions.append("UPPER(status) = UPPER(?)")
            l_params.append(status.strip())

        l_where = f"WHERE {' AND '.join(l_conditions)}" if l_conditions else ""
        
        # Summary for matching live works
        l_cur.execute(f"""
            SELECT 
                COUNT(*) as cnt,
                COALESCE(SUM(sanction_amount), 0.0) as sum_sanc,
                COALESCE(SUM(total_disbursed), 0.0) as sum_disb,
                SUM(CASE WHEN status = 'COMPLETED' THEN 1 ELSE 0 END) as cnt_comp
            FROM live_works {l_where}
        """, l_params)
        l_agg = dict(l_cur.fetchone())
        l_sum_sanc = l_agg["sum_sanc"] or 0.0
        l_sum_disb = l_agg["sum_disb"] or 0.0
        l_cnt_comp = l_agg["cnt_comp"] or 0

        l_cur.execute(f"SELECT * FROM live_works {l_where} ORDER BY id DESC", l_params)
        for row in l_cur.fetchall():
            d = dict(row)
            live_records.append({
                "work_id": d["work_id"],
                "source": "live",
                "work_title": d["title"],
                "work_description": d["description"],
                "work_category": d["work_category"],
                "state": d["state"],
                "district": d["district"],
                "ida": d["ida"] or f"{d['district']} IDA",
                "constituency": d["constituency"],
                "mp_name": d["recommending_mp_name"],
                "sanction_amount": d["sanction_amount"],
                "total_disbursed": d["total_disbursed"],
                "status": d["status"],
                "physical_progress_pct": d["physical_progress_pct"],
                "sanction_date": d["sanction_date"],
                "completion_date": d["completion_date"],
                "created_at": d["created_at"]
            })

    # 2. Query Historical Works if scope in ('all', 'historical')
    hist_records = []
    hist_total = 0
    h_sum_sanc = 0.0
    h_sum_disb = 0.0
    h_cnt_comp = 0

    if scope in ("all", "historical"):
        h_cur = h_db.cursor()
        h_conditions = []
        h_params = []

        if q and q.strip():
            h_conditions.append("(work_id LIKE ? OR work_title LIKE ? OR work_description LIKE ? OR mp_name LIKE ?)")
            q_pat = f"%{q.strip()}%"
            h_params.extend([q_pat, q_pat, q_pat, q_pat])
        if is_valid_filter(state):
            h_conditions.append("UPPER(state) = UPPER(?)")
            h_params.append(state.strip())
        if is_valid_filter(district):
            h_conditions.append("UPPER(district) = UPPER(?)")
            h_params.append(district.strip())
        if is_valid_filter(constituency):
            h_conditions.append("UPPER(constituency) = UPPER(?)")
            h_params.append(constituency.strip())
        if is_valid_filter(category):
            h_conditions.append("UPPER(work_category) = UPPER(?)")
            h_params.append(category.strip())
        if is_valid_filter(status):
            st = status.strip().upper()
            if st == "COMPLETED":
                h_conditions.append("work_completion_status = 'COMPLETED'")
            elif st in ("IN_PROGRESS", "SANCTIONED", "ONGOING"):
                h_conditions.append("work_completion_status != 'COMPLETED'")
            else:
                h_conditions.append("UPPER(portal_execution_status) = UPPER(?)")
                h_params.append(st)

        h_where = f"WHERE {' AND '.join(h_conditions)}" if h_conditions else ""

        # Total count & dynamic aggregates for matching historical works
        h_cur.execute(f"""
            SELECT 
                COUNT(*) as cnt,
                COALESCE(SUM(sanction_amount), 0.0) as sum_sanc,
                COALESCE(SUM(total_disbursed), 0.0) as sum_disb,
                SUM(CASE WHEN work_completion_status = 'COMPLETED' THEN 1 ELSE 0 END) as cnt_comp
            FROM historical_projects {h_where}
        """, h_params)
        h_agg = dict(h_cur.fetchone())
        hist_total = h_agg["cnt"] or 0
        h_sum_sanc = h_agg["sum_sanc"] or 0.0
        h_sum_disb = h_agg["sum_disb"] or 0.0
        h_cnt_comp = h_agg["cnt_comp"] or 0

        hist_limit = limit
        hist_offset = max(0, offset - len(live_records))

        h_cur.execute(f"""
            SELECT 
                work_id,
                'historical' as source,
                work_title,
                work_description,
                work_category,
                state,
                district,
                ida,
                constituency,
                mp_name,
                sanction_amount,
                total_disbursed,
                work_completion_status as status,
                portal_execution_status,
                sanction_date,
                completion_date,
                CASE WHEN work_completion_status = 'COMPLETED' THEN 100 ELSE 50 END as physical_progress_pct
            FROM historical_projects
            {h_where}
            ORDER BY sanction_date DESC
            LIMIT ? OFFSET ?
        """, h_params + [hist_limit, hist_offset])
        hist_records = [dict(r) for r in h_cur.fetchall()]

    total_count = len(live_records) + hist_total
    total_sanction = l_sum_sanc + h_sum_sanc
    total_disbursed = l_sum_disb + h_sum_disb
    completed_works = l_cnt_comp + h_cnt_comp
    ongoing_works = total_count - completed_works

    # Combine paginated items
    if offset < len(live_records):
        slice_live = live_records[offset:offset + limit]
        needed_from_hist = limit - len(slice_live)
        items = slice_live + hist_records[:needed_from_hist]
    else:
        items = hist_records

    total_pages = (total_count + limit - 1) // limit if total_count > 0 else 1

    return {
        "page": page,
        "limit": limit,
        "total": total_count,
        "total_pages": total_pages,
        "summary": {
            "total_works": total_count,
            "total_sanction_amount": total_sanction,
            "total_disbursed_amount": total_disbursed,
            "completed_works": completed_works,
            "ongoing_works": ongoing_works
        },
        "items": items
    }


@app.get("/api/works/{work_id:path}")
def get_work_detail(
    work_id: str,
    h_db: sqlite3.Connection = Depends(get_historical_db),
    l_db: sqlite3.Connection = Depends(get_live_db)
):
    """Fetches comprehensive project details, milestones, and payment tranches."""
    # Check live works first
    l_cur = l_db.cursor()
    l_cur.execute("SELECT * FROM live_works WHERE work_id = ?", (work_id,))
    live_row = l_cur.fetchone()

    if live_row:
        d = dict(live_row)
        # Fetch live progress updates
        l_cur.execute("SELECT * FROM live_progress_updates WHERE work_id = ? ORDER BY submitted_at DESC", (work_id,))
        updates = [dict(r) for r in l_cur.fetchall()]

        # Fetch live payments
        l_cur.execute("SELECT * FROM live_payments WHERE work_id = ? ORDER BY expenditure_date DESC", (work_id,))
        payments = [dict(r) for r in l_cur.fetchall()]

        # Fetch audit logs
        l_cur.execute("SELECT * FROM audit_logs WHERE work_id = ? ORDER BY created_at DESC", (work_id,))
        logs = [dict(r) for r in l_cur.fetchall()]

        return {
            "work": {
                "work_id": d["work_id"],
                "source": "live",
                "title": d["title"],
                "description": d["description"],
                "work_category": d["work_category"],
                "state": d["state"],
                "district": d["district"],
                "ida": d["ida"],
                "constituency": d["constituency"],
                "mp_name": d["recommending_mp_name"],
                "location": d["location"],
                "priority": d["priority"],
                "beneficiary_purpose": d["beneficiary_purpose"],
                "estimated_amount": d["estimated_amount"],
                "sanction_amount": d["sanction_amount"],
                "total_disbursed": d["total_disbursed"],
                "status": d["status"],
                "physical_progress_pct": d["physical_progress_pct"],
                "current_milestone": d["current_milestone"],
                "assigned_agency_name": d["assigned_agency_name"],
                "recommended_date": d["recommended_date"],
                "sanction_date": d["sanction_date"],
                "completion_date": d["completion_date"],
                "review_comments": d["review_comments"]
            },
            "payments": payments,
            "progress_updates": updates,
            "audit_trail": logs
        }

    # Check historical works
    h_cur = h_db.cursor()
    h_cur.execute("SELECT * FROM historical_projects WHERE work_id = ?", (work_id,))
    hist_row = h_cur.fetchone()

    if hist_row:
        hd = dict(hist_row)
        # Fetch payment events from real CSV table
        h_cur.execute("""
            SELECT 
                expenditure_date,
                vendor_name_raw,
                vendor_name_normalized,
                payment_status,
                reported_fund_disbursed_amount,
                source_serial_number
            FROM historical_payment_events
            WHERE work_id = ?
            ORDER BY expenditure_date ASC, source_serial_number ASC
        """, (work_id,))
        pay_rows = [dict(r) for r in h_cur.fetchall()]

        is_completed = (hd["work_completion_status"] == "COMPLETED")
        return {
            "work": {
                "work_id": hd["work_id"],
                "source": "historical",
                "title": hd["work_title"],
                "description": hd["work_description"],
                "work_category": hd["work_category"],
                "state": hd["state"],
                "district": hd["district"],
                "ida": hd["ida"],
                "constituency": hd["constituency"],
                "mp_name": hd["mp_name"],
                "sanction_amount": hd["sanction_amount"],
                "total_disbursed": hd["total_disbursed"],
                "status": hd["work_completion_status"],
                "portal_execution_status": hd["portal_execution_status"],
                "physical_progress_pct": 100 if is_completed else (75 if hd["total_disbursed"] > 0 else 25),
                "recommended_date": hd["recommended_date"],
                "sanction_date": hd["sanction_date"],
                "expected_completion_date": hd["expected_completion_date_proxy"],
                "completion_date": hd["completion_date"],
                "image_reference": hd["image_reference"],
                "assigned_agency_name": hd["primary_vendor"] or "Implementing Agency"
            },
            "payments": pay_rows,
            "progress_updates": [],
            "audit_trail": [
                {
                    "actor_name": hd["mp_name"],
                    "actor_role": "Member of Parliament",
                    "action": "Recommended Work",
                    "created_at": hd["recommended_date"]
                },
                {
                    "actor_name": hd["ida"],
                    "actor_role": "District Authority",
                    "action": "Sanctioned Work",
                    "created_at": hd["sanction_date"]
                }
            ]
        }

    raise HTTPException(status_code=404, detail=f"Work with ID '{work_id}' not found.")


# --- MP Portal Endpoints ---

# --- MP Portal Endpoints ---

@app.get("/api/mp/dashboard")
def get_mp_dashboard(
    mp_name: Optional[str] = Query(None),
    h_db: sqlite3.Connection = Depends(get_historical_db),
    l_db: sqlite3.Connection = Depends(get_live_db)
):
    """Returns dashboard metrics and tracking list for the MP."""
    h_cur = h_db.cursor()
    l_cur = l_db.cursor()

    # If no MP is provided, dynamically select the first distinct MP from the real historical dataset
    if not mp_name or not mp_name.strip():
        h_cur.execute("SELECT mp_name FROM historical_projects WHERE mp_name IS NOT NULL AND TRIM(mp_name) != '' ORDER BY mp_name ASC LIMIT 1")
        row = h_cur.fetchone()
        mp_name = row[0] if row else "Demo MP"

    # Fetch constituency and state for this MP dynamically from real dataset
    h_cur.execute("SELECT constituency, state FROM historical_projects WHERE UPPER(mp_name) = UPPER(?) LIMIT 1", (mp_name,))
    meta_row = h_cur.fetchone()
    constituency = meta_row[0] if meta_row else ""
    state = meta_row[1] if meta_row else ""

    # Search MP name case-insensitively
    h_cur.execute("""
        SELECT 
            COUNT(*) as total_recommended,
            SUM(sanction_amount) as total_sanction,
            SUM(total_disbursed) as total_disbursed,
            SUM(CASE WHEN work_completion_status = 'COMPLETED' THEN 1 ELSE 0 END) as completed,
            SUM(CASE WHEN work_completion_status != 'COMPLETED' THEN 1 ELSE 0 END) as in_progress
        FROM historical_projects
        WHERE UPPER(mp_name) = UPPER(?)
    """, (mp_name,))
    h_stat = dict(h_cur.fetchone())

    # Live recommendations by this MP
    l_cur.execute("""
        SELECT * FROM live_works 
        WHERE UPPER(recommending_mp_name) = UPPER(?) 
        ORDER BY id DESC
    """, (mp_name,))
    live_works = [dict(r) for r in l_cur.fetchall()]

    # Recent historical works
    h_cur.execute("""
        SELECT work_id, work_title, work_category, state, district, constituency,
               sanction_amount, total_disbursed, work_completion_status, sanction_date
        FROM historical_projects
        WHERE UPPER(mp_name) = UPPER(?)
        ORDER BY sanction_date DESC
        LIMIT 10
    """, (mp_name,))
    recent_historical = [dict(r) for r in h_cur.fetchall()]

    live_count = len(live_works)
    live_sanction = sum(w["sanction_amount"] or 0 for w in live_works)
    live_disbursed = sum(w["total_disbursed"] or 0 for w in live_works)

    return {
        "mp_name": mp_name,
        "constituency": constituency,
        "state": state,
        "kpis": {
            "total_recommended": (h_stat["total_recommended"] or 0) + live_count,
            "sanctioned_amount": (h_stat["total_sanction"] or 0) + live_sanction,
            "total_disbursed": (h_stat["total_disbursed"] or 0) + live_disbursed,
            "completed_works": (h_stat["completed"] or 0) + sum(1 for w in live_works if w["status"] == "COMPLETED"),
            "in_progress_works": (h_stat["in_progress"] or 0) + sum(1 for w in live_works if w["status"] in ("APPROVED", "ASSIGNED", "IN_PROGRESS")),
            "pending_review": sum(1 for w in live_works if w["status"] in ("RECOMMENDED", "UNDER_REVIEW"))
        },
        "live_works": live_works,
        "recent_historical": recent_historical
    }


@app.post("/api/mp/recommend")
def recommend_work(
    req: RecommendWorkRequest,
    l_db: sqlite3.Connection = Depends(get_live_db)
):
    """MP submits a new development work recommendation."""
    l_cur = l_db.cursor()
    now_str = datetime.datetime.now().strftime("%Y-%m-%d")
    current_year = datetime.datetime.now().year
    year_str = f"{current_year}-{current_year + 1}"

    # Generate sequential unique work_id for live works
    l_cur.execute("SELECT COUNT(*) FROM live_works")
    seq = l_cur.fetchone()[0] + 1
    work_id = f"WS/LIVE/{year_str}/{seq:05d}"

    l_cur.execute("""
        INSERT INTO live_works (
            work_id, title, description, work_category, state, district, ida,
            constituency, location, priority, beneficiary_purpose,
            estimated_amount, sanction_amount, status, recommending_mp_id,
            recommending_mp_name, recommended_date, physical_progress_pct, current_milestone
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 0.0, 'RECOMMENDED', ?, ?, ?, 0, 'Planning')
    """, (
        work_id, req.title, req.description, req.work_category, req.state, req.district,
        f"{req.district.upper()}(DISTRICT MAGISTRATE {req.district.upper()}_IDA)",
        req.constituency, req.location, req.priority, req.beneficiary_purpose,
        req.estimated_amount, req.recommending_mp_id, req.recommending_mp_name, now_str
    ))

    # Insert audit entry
    l_cur.execute("""
        INSERT INTO audit_logs (work_id, actor_name, actor_role, action, old_status, new_status, comments)
        VALUES (?, ?, 'Member of Parliament', 'RECOMMENDED_WORK', NULL, 'RECOMMENDED', ?)
    """, (work_id, req.recommending_mp_name, f"Work recommended with estimated outlay of ₹{req.estimated_amount:,.2f}"))

    # Create notification for District Authority
    l_cur.execute("""
        INSERT INTO notifications (target_role, title, message, work_id)
        VALUES ('district_authority', 'New Work Recommendation', ?, ?)
    """, (f"MP {req.recommending_mp_name} recommended new work: '{req.title}'", work_id))

    l_db.commit()

    return {
        "success": True,
        "message": "Work recommendation submitted successfully to District Authority workflow.",
        "work_id": work_id,
        "status": "RECOMMENDED"
    }


@app.get("/api/metadata/districts")
def get_districts_metadata(
    state: Optional[str] = Query(None),
    h_db: sqlite3.Connection = Depends(get_historical_db)
):
    """Provides dynamic list of unique districts, optionally filtered by state."""
    h_cur = h_db.cursor()
    if state and state.strip() and not state.strip().lower().startswith("all"):
        h_cur.execute("""
            SELECT DISTINCT district 
            FROM historical_projects 
            WHERE UPPER(state) = UPPER(?) AND district IS NOT NULL AND TRIM(district) != ''
            ORDER BY district ASC
        """, (state.strip(),))
    else:
        h_cur.execute("""
            SELECT DISTINCT district 
            FROM historical_projects 
            WHERE district IS NOT NULL AND TRIM(district) != ''
            ORDER BY district ASC
        """)
    districts = [r[0] for r in h_cur.fetchall()]
    return {"state": state or "", "districts": districts}


@app.get("/api/metadata/constituencies")
def get_constituencies_metadata(
    state: Optional[str] = Query(None),
    district: Optional[str] = Query(None),
    h_db: sqlite3.Connection = Depends(get_historical_db)
):
    """Provides dynamic list of unique constituencies, optionally filtered by state and/or district."""
    h_cur = h_db.cursor()
    conditions = ["constituency IS NOT NULL", "TRIM(constituency) != ''"]
    params = []
    if state and state.strip() and not state.strip().lower().startswith("all"):
        conditions.append("UPPER(state) = UPPER(?)")
        params.append(state.strip())
    if district and district.strip() and not district.strip().lower().startswith("all"):
        conditions.append("UPPER(district) = UPPER(?)")
        params.append(district.strip())

    where_sql = f"WHERE {' AND '.join(conditions)}"
    h_cur.execute(f"SELECT DISTINCT constituency FROM historical_projects {where_sql} ORDER BY constituency ASC", params)
    constituencies = [r[0] for r in h_cur.fetchall()]
    return {"state": state or "", "district": district or "", "constituencies": constituencies}



# --- District Authority Endpoints ---

@app.get("/api/da/dashboard")
def get_da_dashboard(
    state: Optional[str] = Query(None),
    district: Optional[str] = Query(None),
    h_db: sqlite3.Connection = Depends(get_historical_db),
    l_db: sqlite3.Connection = Depends(get_live_db)
):
    """District Authority dashboard: pending recommendations and district works with full state/district filtering."""
    h_cur = h_db.cursor()
    l_cur = l_db.cursor()

    def is_valid_filter(val):
        if not val or not isinstance(val, str):
            return False
        v = val.strip().lower()
        return v != "" and not v.startswith("all")

    # Default to Agar-Malwa / Madhya Pradesh ONLY if query parameters are completely omitted (None)
    if state is None and district is None:
        state = "Madhya Pradesh"
        district = "Agar-Malwa"

    # Build SQL WHERE clause for historical DB
    h_conditions = []
    h_params = []

    if is_valid_filter(state):
        h_conditions.append("UPPER(state) = UPPER(?)")
        h_params.append(state.strip())

    if is_valid_filter(district):
        h_conditions.append("UPPER(district) = UPPER(?)")
        h_params.append(district.strip())

    h_where = f"WHERE {' AND '.join(h_conditions)}" if h_conditions else ""

    # Build SQL WHERE clause for live DB
    l_conditions_pending = ["status IN ('RECOMMENDED', 'UNDER_REVIEW')"]
    l_conditions_active = ["status NOT IN ('RECOMMENDED', 'UNDER_REVIEW')"]
    l_params_pending = []
    l_params_active = []

    if is_valid_filter(state):
        l_conditions_pending.append("UPPER(state) = UPPER(?)")
        l_params_pending.append(state.strip())
        l_conditions_active.append("UPPER(state) = UPPER(?)")
        l_params_active.append(state.strip())

    if is_valid_filter(district):
        l_conditions_pending.append("UPPER(district) = UPPER(?)")
        l_params_pending.append(district.strip())
        l_conditions_active.append("UPPER(district) = UPPER(?)")
        l_params_active.append(district.strip())

    l_where_pending = f"WHERE {' AND '.join(l_conditions_pending)}"
    l_where_active = f"WHERE {' AND '.join(l_conditions_active)}"

    # Query live DB
    l_cur.execute(f"SELECT * FROM live_works {l_where_pending} ORDER BY id DESC", l_params_pending)
    pending_recs = [dict(r) for r in l_cur.fetchall()]

    l_cur.execute(f"SELECT * FROM live_works {l_where_active} ORDER BY id DESC", l_params_active)
    active_live_works = [dict(r) for r in l_cur.fetchall()]

    # Query historical DB KPIs
    h_cur.execute(f"""
        SELECT 
            COUNT(*) as total_works,
            SUM(sanction_amount) as total_sanction,
            SUM(total_disbursed) as total_disbursed,
            SUM(CASE WHEN work_completion_status = 'COMPLETED' THEN 1 ELSE 0 END) as completed,
            SUM(CASE WHEN work_completion_status != 'COMPLETED' THEN 1 ELSE 0 END) as ongoing
        FROM historical_projects
        {h_where}
    """, h_params)
    h_stat = dict(h_cur.fetchone())

    # Query historical district works for Section B
    h_cur.execute(f"""
        SELECT work_id, work_title, work_category, state, district, constituency, mp_name,
               sanction_amount, total_disbursed, work_completion_status as status, sanction_date
        FROM historical_projects
        {h_where}
        ORDER BY sanction_date DESC
        LIMIT 50
    """, h_params)
    historical_district_works = [dict(r) for r in h_cur.fetchall()]

    # Get list of implementing agencies for assignment dropdown
    l_cur.execute("SELECT id, agency_name, full_name, email FROM users WHERE role = 'implementing_agency'")
    agencies = [dict(r) for r in l_cur.fetchall()]

    # Calculate actual state name if only district was provided
    if not is_valid_filter(state) and is_valid_filter(district):
        h_cur.execute("SELECT state FROM historical_projects WHERE UPPER(district) = UPPER(?) LIMIT 1", (district.strip(),))
        s_row = h_cur.fetchone()
        state = s_row[0] if s_row else ""

    return {
        "district": district if is_valid_filter(district) else "All Districts",
        "state": state if is_valid_filter(state) else "All States",
        "kpis": {
            "pending_recommendations": len(pending_recs),
            "active_live_works": len(active_live_works),
            "historical_district_works": h_stat["total_works"] or 0,
            "district_sanction_amount": (h_stat["total_sanction"] or 0.0),
            "district_disbursed_amount": (h_stat["total_disbursed"] or 0.0),
            "district_completed": h_stat["completed"] or 0,
            "district_ongoing": h_stat["ongoing"] or 0
        },
        "pending_recommendations": pending_recs,
        "active_live_works": active_live_works,
        "historical_district_works": historical_district_works,
        "agencies": agencies
    }


@app.post("/api/da/review")
def review_work(
    req: ReviewWorkRequest,
    l_db: sqlite3.Connection = Depends(get_live_db)
):
    """District Authority approves or returns a work recommendation."""
    l_cur = l_db.cursor()
    l_cur.execute("SELECT * FROM live_works WHERE work_id = ?", (req.work_id,))
    work = l_cur.fetchone()

    if not work:
        raise HTTPException(status_code=404, detail="Work not found.")

    work = dict(work)
    old_status = work["status"]
    now_str = datetime.datetime.now().strftime("%Y-%m-%d")

    if req.action == "APPROVE":
        new_status = "APPROVED"
        sanction_amount = req.sanction_amount or work["estimated_amount"]
        agency_id = req.assigned_agency_id or 1
        agency_name = req.assigned_agency_name or "Assigned Implementing Agency"

        l_cur.execute("""
            UPDATE live_works SET
                status = ?,
                sanction_amount = ?,
                sanction_date = ?,
                assigned_agency_id = ?,
                assigned_agency_name = ?,
                assigned_date = ?,
                review_comments = ?,
                review_date = ?
            WHERE work_id = ?
        """, (new_status, sanction_amount, now_str, agency_id, agency_name, now_str, req.review_comments, now_str, req.work_id))

        action_desc = f"Approved & Sanctioned for ₹{sanction_amount:,.2f}; Assigned to {agency_name}"

        # Notify Agency
        l_cur.execute("""
            INSERT INTO notifications (target_role, title, message, work_id)
            VALUES ('implementing_agency', 'New Work Assigned', ?, ?)
        """, (f"Work '{work['title']}' has been assigned to your agency.", req.work_id))

        # Notify MP
        l_cur.execute("""
            INSERT INTO notifications (target_role, title, message, work_id)
            VALUES ('mp', 'Work Approved & Sanctioned', ?, ?)
        """, (f"Your recommended work '{work['title']}' has been approved by District Authority.", req.work_id))

    else: # RETURN
        new_status = "RETURNED"
        l_cur.execute("""
            UPDATE live_works SET
                status = ?,
                review_comments = ?,
                review_date = ?
            WHERE work_id = ?
        """, (new_status, req.review_comments, now_str, req.work_id))

        action_desc = f"Returned recommendation to MP. Reason: {req.review_comments}"

        # Notify MP
        l_cur.execute("""
            INSERT INTO notifications (target_role, title, message, work_id)
            VALUES ('mp', 'Work Recommendation Returned', ?, ?)
        """, (f"Your recommended work '{work['title']}' was returned: {req.review_comments}", req.work_id))

    # Audit Trail
    l_cur.execute("""
        INSERT INTO audit_logs (work_id, actor_name, actor_role, action, old_status, new_status, comments)
        VALUES (?, 'District Authority', 'District Authority', ?, ?, ?, ?)
    """, (req.work_id, f"DA_{req.action}", old_status, new_status, action_desc))

    l_db.commit()

    return {
        "success": True,
        "work_id": req.work_id,
        "new_status": new_status,
        "message": f"Work successfully updated to {new_status}."
    }


# --- Implementing Agency Endpoints ---

@app.get("/api/agency/dashboard")
def get_agency_dashboard(
    l_db: sqlite3.Connection = Depends(get_live_db)
):
    """Implementing Agency dashboard: assigned works and milestone tracking."""
    l_cur = l_db.cursor()
    l_cur.execute("""
        SELECT * FROM live_works 
        WHERE status IN ('APPROVED', 'ASSIGNED', 'IN_PROGRESS', 'COMPLETED')
        ORDER BY id DESC
    """)
    assigned_works = [dict(r) for r in l_cur.fetchall()]

    in_progress = sum(1 for w in assigned_works if w["status"] == "IN_PROGRESS")
    completed = sum(1 for w in assigned_works if w["status"] == "COMPLETED")
    not_started = sum(1 for w in assigned_works if w["status"] in ("APPROVED", "ASSIGNED"))

    return {
        "kpis": {
            "total_assigned": len(assigned_works),
            "not_started": not_started,
            "in_progress": in_progress,
            "completed": completed
        },
        "assigned_works": assigned_works
    }


@app.post("/api/agency/update-progress")
def update_agency_progress(
    req: UpdateProgressRequest,
    l_db: sqlite3.Connection = Depends(get_live_db)
):
    """Agency submits physical progress, status change, and expenditure."""
    l_cur = l_db.cursor()
    l_cur.execute("SELECT * FROM live_works WHERE work_id = ?", (req.work_id,))
    work = l_cur.fetchone()

    if not work:
        raise HTTPException(status_code=404, detail="Work not found.")

    work = dict(work)
    old_status = work["status"]
    now_str = datetime.datetime.now().strftime("%Y-%m-%d")

    new_total_disbursed = (work["total_disbursed"] or 0.0) + (req.expenditure_incurred or 0.0)
    completion_date = now_str if req.status == "COMPLETED" else work["completion_date"]

    l_cur.execute("""
        UPDATE live_works SET
            physical_progress_pct = ?,
            status = ?,
            current_milestone = ?,
            total_disbursed = ?,
            completion_date = ?,
            updated_at = CURRENT_TIMESTAMP
        WHERE work_id = ?
    """, (req.physical_progress_pct, req.status, req.current_milestone, new_total_disbursed, completion_date, req.work_id))

    # Record progress update entry
    l_cur.execute("""
        INSERT INTO live_progress_updates (
            work_id, agency_id, agency_name, physical_progress_pct, milestone,
            description, expenditure_incurred, payment_notes, status
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, 'VERIFIED')
    """, (
        req.work_id, work["assigned_agency_id"], work["assigned_agency_name"],
        req.physical_progress_pct, req.current_milestone, req.description,
        req.expenditure_incurred, req.payment_notes
    ))

    # If expenditure incurred, add payment record
    if req.expenditure_incurred and req.expenditure_incurred > 0:
        l_cur.execute("""
            INSERT INTO live_payments (
                work_id, expenditure_date, vendor_name_raw, vendor_name_normalized,
                payment_status, reported_fund_disbursed_amount, remarks
            ) VALUES (?, ?, ?, ?, 'PAYMENT SUCCESS', ?, ?)
        """, (
            req.work_id, now_str, work["assigned_agency_name"] or "Contractor",
            work["assigned_agency_name"] or "Contractor",
            req.expenditure_incurred, req.payment_notes or "Tranche disbursement"
        ))

    # Audit entry
    l_cur.execute("""
        INSERT INTO audit_logs (work_id, actor_name, actor_role, action, old_status, new_status, comments)
        VALUES (?, ?, 'Implementing Agency', 'UPDATE_PROGRESS', ?, ?, ?)
    """, (
        req.work_id, work["assigned_agency_name"] or "Agency Engineer",
        old_status, req.status,
        f"Progress updated to {req.physical_progress_pct}% ({req.current_milestone}). Outlay: ₹{req.expenditure_incurred:,.2f}. Notes: {req.description}"
    ))

    # Notify DA & MP
    l_cur.execute("""
        INSERT INTO notifications (target_role, title, message, work_id)
        VALUES ('district_authority', 'Progress Update Submitted', ?, ?)
    """, (f"Progress update for work '{work['title']}': {req.physical_progress_pct}% reached.", req.work_id))

    l_cur.execute("""
        INSERT INTO notifications (target_role, title, message, work_id)
        VALUES ('mp', 'Progress Update on Recommended Work', ?, ?)
    """, (f"Work '{work['title']}' updated to {req.physical_progress_pct}% progress by {work['assigned_agency_name']}.", req.work_id))

    l_db.commit()

    return {
        "success": True,
        "work_id": req.work_id,
        "physical_progress_pct": req.physical_progress_pct,
        "status": req.status,
        "message": "Progress and expenditure successfully updated."
    }


# --- PROJECT MONITORING & ML ANOMALY DETECTION ENDPOINTS ---

from backend.monitoring_ml import init_monitoring_if_needed, run_monitoring_pipeline

@app.on_event("startup")
def startup_event():
    conn = sqlite3.connect(HISTORICAL_DB_PATH)
    try:
        init_monitoring_if_needed(conn)
    finally:
        conn.close()


@app.get("/api/monitoring/summary")
def get_monitoring_summary(
    state: Optional[str] = Query(None),
    district: Optional[str] = Query(None),
    h_db: sqlite3.Connection = Depends(get_historical_db)
):
    """Returns dynamic KPI metrics for Budget, Delay, Payment, and ML Anomaly Detection."""
    h_cur = h_db.cursor()

    def is_valid_filter(val):
        if not val or not isinstance(val, str):
            return False
        v = val.strip().lower()
        return v != "" and not v.startswith("all")

    conditions = []
    params = []
    if is_valid_filter(state):
        conditions.append("UPPER(state) = UPPER(?)")
        params.append(state.strip())
    if is_valid_filter(district):
        conditions.append("UPPER(district) = UPPER(?)")
        params.append(district.strip())

    where_sql = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    # Budget Summary
    h_cur.execute(f"""
        SELECT 
            COUNT(*) as total_projects,
            SUM(CASE WHEN budget_monitoring_status = 'WITHIN_SANCTION' THEN 1 ELSE 0 END) as within_sanction,
            SUM(CASE WHEN budget_monitoring_status = 'FULLY_DISBURSED' THEN 1 ELSE 0 END) as fully_disbursed,
            SUM(CASE WHEN budget_monitoring_status = 'POTENTIAL_BUDGET_OVERRUN' THEN 1 ELSE 0 END) as potential_budget_overruns,
            SUM(sanction_amount) as total_sanctioned,
            SUM(total_disbursed) as total_disbursed,
            AVG(budget_disbursement_ratio) as avg_disbursement_ratio
        FROM project_monitoring_features
        {where_sql}
    """, params)
    budget_row = dict(h_cur.fetchone())

    # Delay Summary
    h_cur.execute(f"""
        SELECT 
            SUM(CASE WHEN delay_status = 'ON_TIME' THEN 1 ELSE 0 END) as on_time,
            SUM(CASE WHEN delay_status = 'DELAYED' THEN 1 ELSE 0 END) as delayed,
            SUM(CASE WHEN delay_status = 'ONGOING_WITHIN_TARGET' THEN 1 ELSE 0 END) as ongoing_within_target,
            SUM(CASE WHEN delay_status = 'ONGOING_DELAYED' THEN 1 ELSE 0 END) as ongoing_delayed,
            AVG(actual_duration_days) as avg_completion_duration_days,
            AVG(schedule_delay_days) as avg_schedule_delay_days
        FROM project_monitoring_features
        {where_sql}
    """, params)
    delay_row = dict(h_cur.fetchone())

    # Payment Summary
    h_cur.execute(f"""
        SELECT 
            SUM(payment_tranche_count) as total_payment_events,
            AVG(mean_tranche_amount) as avg_payment_tranche,
            SUM(CASE WHEN payment_tranche_count >= 2 THEN 1 ELSE 0 END) as multiple_tranche_projects,
            SUM(CASE WHEN max_single_tranche_ratio >= 0.9 THEN 1 ELSE 0 END) as vendor_concentration_projects
        FROM project_monitoring_features
        {where_sql}
    """, params)
    payment_row = dict(h_cur.fetchone())

    # ML Anomaly Summary
    h_cur.execute(f"""
        SELECT 
            COUNT(*) as projects_analyzed,
            SUM(CASE WHEN anomaly_prediction = 1 THEN 1 ELSE 0 END) as normal_projects,
            SUM(CASE WHEN anomaly_prediction = -1 THEN 1 ELSE 0 END) as potential_anomalies
        FROM project_monitoring_features
        {where_sql}
    """, params)
    ml_row = dict(h_cur.fetchone())

    # Highest anomaly-score projects
    h_cur.execute(f"""
        SELECT work_id, state, district, constituency, mp_name, work_title, sanction_amount, total_disbursed, raw_anomaly_score, anomaly_risk_score, anomaly_status
        FROM project_monitoring_features
        {where_sql}
        ORDER BY anomaly_risk_score DESC
        LIMIT 5
    """, params)
    highest_anomalies = [dict(r) for r in h_cur.fetchall()]

    analyzed = ml_row['projects_analyzed'] or 0
    anomalies = ml_row['potential_anomalies'] or 0
    anomaly_pct = round((anomalies / analyzed * 100), 2) if analyzed > 0 else 0.0

    return {
        "budget_monitoring": budget_row,
        "delay_monitoring": delay_row,
        "payment_analysis": payment_row,
        "ml_anomaly_detection": {
            "projects_analyzed": analyzed,
            "normal_projects": ml_row['normal_projects'] or 0,
            "potential_anomalies": anomalies,
            "anomaly_pct": anomaly_pct,
            "highest_anomaly_score_projects": highest_anomalies
        }
    }


@app.get("/api/monitoring/works")
def get_monitoring_works(
    q: Optional[str] = Query(None),
    state: Optional[str] = Query(None),
    district: Optional[str] = Query(None),
    completion_status: Optional[str] = Query(None),
    delay_status: Optional[str] = Query(None),
    budget_status: Optional[str] = Query(None),
    anomaly_status: Optional[str] = Query(None),
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    h_db: sqlite3.Connection = Depends(get_historical_db)
):
    """Searchable & filterable monitoring dataset table with ML anomaly scores."""
    h_cur = h_db.cursor()

    def is_valid_filter(val):
        if not val or not isinstance(val, str):
            return False
        v = val.strip().lower()
        return v != "" and not v.startswith("all")

    conditions = []
    params = []

    if q and q.strip():
        conditions.append("(work_id LIKE ? OR work_title LIKE ? OR mp_name LIKE ?)")
        pat = f"%{q.strip()}%"
        params.extend([pat, pat, pat])

    if is_valid_filter(state):
        conditions.append("UPPER(state) = UPPER(?)")
        params.append(state.strip())

    if is_valid_filter(district):
        conditions.append("UPPER(district) = UPPER(?)")
        params.append(district.strip())

    if is_valid_filter(completion_status):
        conditions.append("work_completion_status = ?")
        params.append(completion_status.strip())

    if is_valid_filter(delay_status):
        conditions.append("delay_status = ?")
        params.append(delay_status.strip())

    if is_valid_filter(budget_status):
        conditions.append("budget_monitoring_status = ?")
        params.append(budget_status.strip())

    if is_valid_filter(anomaly_status):
        conditions.append("anomaly_status = ?")
        params.append(anomaly_status.strip())

    where_sql = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    h_cur.execute(f"SELECT COUNT(*) FROM project_monitoring_features {where_sql}", params)
    total_records = h_cur.fetchone()[0]

    offset = (page - 1) * limit
    h_cur.execute(f"""
        SELECT * FROM project_monitoring_features
        {where_sql}
        ORDER BY anomaly_risk_score DESC, sanction_amount DESC
        LIMIT ? OFFSET ?
    """, params + [limit, offset])

    items = [dict(r) for r in h_cur.fetchall()]
    total_pages = (total_records + limit - 1) // limit if total_records > 0 else 1

    return {
        "total": total_records,
        "page": page,
        "limit": limit,
        "total_pages": total_pages,
        "items": items
    }


@app.get("/api/monitoring/work/{work_id:path}")
def get_monitoring_work_detail(
    work_id: str,
    h_db: sqlite3.Connection = Depends(get_historical_db),
    l_db: sqlite3.Connection = Depends(get_live_db)
):
    """Returns comprehensive project inspection detail with ML anomaly features & payments."""
    h_cur = h_db.cursor()
    l_cur = l_db.cursor()

    # Query monitoring features table
    h_cur.execute("SELECT * FROM project_monitoring_features WHERE work_id = ?", (work_id,))
    row = h_cur.fetchone()

    if not row:
        # Check live DB
        l_cur.execute("SELECT * FROM live_works WHERE work_id = ?", (work_id,))
        l_row = l_cur.fetchone()
        if not l_row:
            raise HTTPException(status_code=404, detail=f"Work with ID '{work_id}' not found.")
        d = dict(l_row)
        return {
            "source": "live",
            "project_info": {
                "work_id": d["work_id"],
                "state": d["state"],
                "district": d["district"],
                "constituency": d["constituency"],
                "mp_name": d["recommending_mp_name"],
                "work_title": d["title"],
                "work_description": d["description"],
                "work_category": d["work_category"]
            },
            "financial_info": {
                "sanction_amount": d["sanction_amount"] or d["estimated_amount"],
                "total_disbursed": d["total_disbursed"],
                "remaining_sanction": (d["sanction_amount"] or d["estimated_amount"]) - (d["total_disbursed"] or 0),
                "disbursement_ratio": (d["total_disbursed"] or 0) / (d["sanction_amount"] or d["estimated_amount"]) if (d["sanction_amount"] or d["estimated_amount"]) > 0 else 0,
                "budget_monitoring_status": "POTENTIAL_BUDGET_OVERRUN" if (d["total_disbursed"] or 0) > (d["sanction_amount"] or d["estimated_amount"]) else "WITHIN_SANCTION"
            },
            "timeline": {
                "recommended_date": d["recommended_date"],
                "sanction_date": d["sanction_date"],
                "expected_completion_date_proxy": "N/A",
                "completion_date": d["completion_date"],
                "delay_status": d["status"]
            },
            "payments": [],
            "ml_monitoring": {
                "anomaly_score": 0.0,
                "anomaly_status": "LIVE RECORD (NOT IN HISTORICAL MODEL)",
                "anomaly_risk_score": 0.0,
                "disclaimer": "Live application records are processed in the real-time workflow database."
            }
        }

    p = dict(row)

    # Fetch payment events for this work_id
    h_cur.execute("""
        SELECT expenditure_date, vendor_name_raw, vendor_name_normalized, payment_status, reported_fund_disbursed_amount, source_serial_number
        FROM historical_payment_events
        WHERE work_id = ?
        ORDER BY expenditure_date ASC
    """, (work_id,))
    payments = [dict(r) for r in h_cur.fetchall()]

    return {
        "source": "historical",
        "project_info": {
            "work_id": p["work_id"],
            "state": p["state"],
            "district": p["district"],
            "constituency": p["constituency"],
            "mp_name": p["mp_name"],
            "work_title": p["work_title"],
            "work_description": p["work_description"],
            "work_category": p["work_category"]
        },
        "financial_info": {
            "sanction_amount": p["sanction_amount"],
            "total_disbursed": p["total_disbursed"],
            "remaining_sanction": p["budget_variance_amount"],
            "disbursement_ratio": round(p["budget_disbursement_ratio"], 4),
            "budget_monitoring_status": p["budget_monitoring_status"]
        },
        "timeline": {
            "recommended_date": p["recommended_date"],
            "sanction_date": p["sanction_date"],
            "expected_completion_date_proxy": p["expected_completion_date_proxy"],
            "completion_date": p["completion_date"],
            "sanction_lead_time_days": p["sanction_lead_time_days"],
            "expected_duration_days": p["expected_duration_days"],
            "actual_duration_days": p["actual_duration_days"],
            "schedule_delay_days": p["schedule_delay_days"],
            "delay_status": p["delay_status"]
        },
        "payment_info": {
            "payment_tranche_count": p["payment_tranche_count"],
            "first_payment_date": p["first_payment_date"],
            "latest_payment_date": p["latest_payment_date"],
            "payment_span_days": p["payment_span_days"],
            "mean_tranche_amount": p["mean_tranche_amount"],
            "max_single_tranche_ratio": round(p["max_single_tranche_ratio"], 4),
            "vendor_unique_count": p["vendor_unique_count"],
            "payments_list": payments
        },
        "ml_monitoring": {
            "raw_anomaly_score": round(p["raw_anomaly_score"], 4),
            "anomaly_prediction": p["anomaly_prediction"],
            "anomaly_status": p["anomaly_status"],
            "anomaly_risk_score": p["anomaly_risk_score"],
            "features_contributing": {
                "sanction_amount": p["sanction_amount"],
                "total_disbursed": p["total_disbursed"],
                "disbursement_ratio": round(p["budget_disbursement_ratio"], 4),
                "sanction_lead_time_days": p["sanction_lead_time_days"],
                "payment_tranches": p["payment_tranche_count"],
                "max_tranche_ratio": round(p["max_single_tranche_ratio"], 4),
                "description_length": p["work_description_length"]
            },
            "disclaimer": "Potential anomaly indicates that the project's feature pattern differs statistically from other projects in the dataset. It is a screening signal, not proof of wrongdoing."
        }
    }


@app.get("/api/monitoring/alerts")
def get_monitoring_alerts(
    state: Optional[str] = Query(None),
    district: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    h_db: sqlite3.Connection = Depends(get_historical_db)
):
    """Returns deterministic alerts for potential budget overruns, schedule delays, ML anomalies, and payment spikes."""
    h_cur = h_db.cursor()

    def is_valid_filter(val):
        if not val or not isinstance(val, str):
            return False
        v = val.strip().lower()
        return v != "" and not v.startswith("all")

    conditions = []
    params = []
    if is_valid_filter(state):
        conditions.append("UPPER(state) = UPPER(?)")
        params.append(state.strip())
    if is_valid_filter(district):
        conditions.append("UPPER(district) = UPPER(?)")
        params.append(district.strip())

    where_sql = f"WHERE {' AND '.join(conditions)}" if conditions else ""

    h_cur.execute(f"""
        SELECT work_id, state, district, constituency, mp_name, work_title, sanction_amount, total_disbursed,
               budget_monitoring_status, delay_status, payment_tranche_count, max_single_tranche_ratio,
               anomaly_status, anomaly_risk_score
        FROM project_monitoring_features
        {where_sql}
        ORDER BY anomaly_risk_score DESC, schedule_delay_days DESC
        LIMIT ?
    """, params + [limit])

    rows = [dict(r) for r in h_cur.fetchall()]
    alerts = []

    for r in rows:
        # 1. Budget Alert
        if r["budget_monitoring_status"] == "POTENTIAL_BUDGET_OVERRUN":
            alerts.append({
                "work_id": r["work_id"],
                "state": r["state"],
                "district": r["district"],
                "work_title": r["work_title"],
                "alert_type": "Potential Budget Overrun",
                "severity": "HIGH",
                "measured_value": f"Disbursed {r['total_disbursed']} > Sanctioned {r['sanction_amount']}",
                "anomaly_risk_score": r["anomaly_risk_score"]
            })
        # 2. Delay Alert
        if r["delay_status"] in ("DELAYED", "ONGOING_DELAYED"):
            alerts.append({
                "work_id": r["work_id"],
                "state": r["state"],
                "district": r["district"],
                "work_title": r["work_title"],
                "alert_type": "Delayed Project",
                "severity": "MEDIUM",
                "measured_value": f"Status: {r['delay_status']}",
                "anomaly_risk_score": r["anomaly_risk_score"]
            })
        # 3. ML Anomaly Alert
        if r["anomaly_status"] == "POTENTIAL ANOMALY":
            alerts.append({
                "work_id": r["work_id"],
                "state": r["state"],
                "district": r["district"],
                "work_title": r["work_title"],
                "alert_type": "Potential ML Anomaly",
                "severity": "HIGH" if r["anomaly_risk_score"] >= 80 else "MEDIUM",
                "measured_value": f"Anomaly Risk Score: {r['anomaly_risk_score']}/100",
                "anomaly_risk_score": r["anomaly_risk_score"]
            })
        # 4. Payment Concentration Alert
        if r["max_single_tranche_ratio"] >= 0.95 and r["payment_tranche_count"] > 1:
            alerts.append({
                "work_id": r["work_id"],
                "state": r["state"],
                "district": r["district"],
                "work_title": r["work_title"],
                "alert_type": "Unusual Payment Pattern",
                "severity": "MEDIUM",
                "measured_value": f"Single payment ratio {round(r['max_single_tranche_ratio']*100, 1)}%",
                "anomaly_risk_score": r["anomaly_risk_score"]
            })

    return {"total_alerts": len(alerts), "alerts": alerts[:limit]}


@app.get("/api/analytics/monitoring")
def get_analytics_monitoring(
    h_db: sqlite3.Connection = Depends(get_historical_db)
):
    """Provides backend data for 10 dynamic charts in the Analytics section."""
    h_cur = h_db.cursor()

    # 1. State-wise project count
    h_cur.execute("""
        SELECT state, COUNT(*) as project_count, SUM(sanction_amount) as total_sanction, SUM(total_disbursed) as total_disbursed
        FROM project_monitoring_features
        GROUP BY state
        ORDER BY project_count DESC
    """)
    state_metrics = [dict(r) for r in h_cur.fetchall()]

    # 2. Completion status distribution
    h_cur.execute("SELECT work_completion_status as status, COUNT(*) as count FROM project_monitoring_features GROUP BY work_completion_status")
    completion_dist = [dict(r) for r in h_cur.fetchall()]

    # 3. Delay status distribution
    h_cur.execute("SELECT delay_status as status, COUNT(*) as count FROM project_monitoring_features GROUP BY delay_status")
    delay_dist = [dict(r) for r in h_cur.fetchall()]

    # 4. Budget monitoring distribution
    h_cur.execute("SELECT budget_monitoring_status as status, COUNT(*) as count FROM project_monitoring_features GROUP BY budget_monitoring_status")
    budget_dist = [dict(r) for r in h_cur.fetchall()]

    # 5. Payment tranche distribution
    h_cur.execute("""
        SELECT 
            CASE 
                WHEN payment_tranche_count = 0 THEN '0 Tranches'
                WHEN payment_tranche_count = 1 THEN '1 Tranche'
                WHEN payment_tranche_count BETWEEN 2 AND 3 THEN '2-3 Tranches'
                WHEN payment_tranche_count BETWEEN 4 AND 5 THEN '4-5 Tranches'
                ELSE '6+ Tranches'
            END as category,
            COUNT(*) as count
        FROM project_monitoring_features
        GROUP BY category
    """)
    tranche_dist = [dict(r) for r in h_cur.fetchall()]

    # 6. ML anomaly distribution
    h_cur.execute("SELECT anomaly_status as status, COUNT(*) as count FROM project_monitoring_features GROUP BY anomaly_status")
    anomaly_dist = [dict(r) for r in h_cur.fetchall()]

    # 7. Monthly payment trend using expenditure_date
    h_cur.execute("""
        SELECT 
            substr(expenditure_date, 1, 7) as month_str,
            COUNT(*) as payment_count,
            SUM(reported_fund_disbursed_amount) as total_disbursed
        FROM historical_payment_events
        WHERE expenditure_date IS NOT NULL AND TRIM(expenditure_date) != ''
        GROUP BY month_str
        ORDER BY month_str ASC
    """)
    monthly_payments = [dict(r) for r in h_cur.fetchall()]

    return {
        "state_metrics": state_metrics,
        "completion_dist": completion_dist,
        "delay_dist": delay_dist,
        "budget_dist": budget_dist,
        "tranche_dist": tranche_dist,
        "anomaly_dist": anomaly_dist,
        "monthly_payments": monthly_payments
    }


@app.post("/api/ml/retrain")
def retrain_ml_model(
    contamination: float = Query(0.05, ge=0.01, le=0.2),
    h_db: sqlite3.Connection = Depends(get_historical_db)
):
    """Triggers ML Isolation Forest retraining with configurable contamination rate."""
    try:
        run_monitoring_pipeline(h_db, contamination=contamination)
        return {
            "success": True,
            "message": f"ML Isolation Forest successfully retrained with contamination rate = {contamination}.",
            "contamination": contamination
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"ML retraining failed: {str(e)}")


# Mount static assets directory
STATIC_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static")
app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
