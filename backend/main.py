"""
FastAPI Backend Application for MPLADS Management, Monitoring & Transparency Platform.
Serves API endpoints and static frontend for the MVP prototype.
"""
import os
import sqlite3
import datetime
import json
import uuid
from typing import Optional, List, Dict, Any
from fastapi import FastAPI, Query, HTTPException, Depends, File, Form, UploadFile, Request, Response, status
from fastapi.responses import FileResponse
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
from backend.evidence_screening import run_evidence_screening
from backend.security import (
    hash_password,
    verify_password,
    check_rate_limit,
    record_failed_login,
    record_successful_login,
    create_user_session,
    invalidate_user_session,
    get_session_user,
    log_security_event,
    extract_token_from_request,
    get_current_user_optional,
    get_current_user,
    require_role,
    enforce_mp_scope,
    enforce_da_scope,
    enforce_ia_scope,
    SESSION_COOKIE_NAME,
    SESSION_EXPIRY_HOURS,
    SECURE_COOKIES
)

EVIDENCE_UPLOAD_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "uploads", "evidence")
os.makedirs(EVIDENCE_UPLOAD_DIR, exist_ok=True)

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

# Security Headers Middleware
@app.middleware("http")
async def add_security_headers(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["X-XSS-Protection"] = "1; mode=block"
    response.headers["Referrer-Policy"] = "strict-origin-when-cross-origin"
    return response

# Initialize live database tables and demo seed data on startup
init_live_db()

# --- Pydantic Request Models ---
class LoginRequest(BaseModel):
    username: str = Field(..., min_length=2, max_length=100)
    password: str = Field(..., min_length=3, max_length=200)

class CreateUserRequest(BaseModel):
    username: str = Field(..., min_length=3, max_length=50)
    password: str = Field(..., min_length=6, max_length=100)
    full_name: str = Field(..., min_length=2, max_length=150)
    email: str = Field(..., min_length=5, max_length=150)
    role: str = Field(..., pattern="^(admin|mp|district_authority|implementing_agency|citizen)$")
    state: Optional[str] = None
    district: Optional[str] = None
    constituency: Optional[str] = None
    agency_id: Optional[int] = None
    agency_name: Optional[str] = None
    designation: Optional[str] = None

class UpdateUserStatusRequest(BaseModel):
    is_active: int = Field(..., ge=0, le=1)

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
    recommending_mp_name: Optional[str] = None
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


# --- Authentication & User Management Routes ---

@app.post("/api/auth/login")
def login(
    req: LoginRequest,
    request: Request,
    response: Response,
    db: sqlite3.Connection = Depends(get_live_db)
):
    """Authenticates stakeholder using Argon2id password verification and establishes secure session."""
    client_ip = request.client.host if request.client else "unknown"
    client_key = f"{client_ip}:{req.username.strip().lower()}"
    
    # 1. Rate limiting check against brute-force attacks
    check_rate_limit(client_key)
    
    # 2. Query user by username (parameterized query)
    cursor = db.cursor()
    cursor.execute("""
        SELECT id, username, password_hash, full_name, email, role,
               state, district, constituency, agency_id, agency_name,
               designation, is_active
        FROM users
        WHERE LOWER(username) = LOWER(?)
    """, (req.username.strip(),))
    row = cursor.fetchone()
    
    if not row:
        record_failed_login(client_key)
        log_security_event(
            db, action="LOGIN_FAILED", status_code="401",
            actor_username=req.username.strip(),
            ip_address=client_ip, details="User account does not exist"
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password."
        )

    user = dict(row)

    # 3. Check account active status
    if not user.get("is_active", 1):
        record_failed_login(client_key)
        log_security_event(
            db, action="LOGIN_BLOCKED_INACTIVE", status_code="403",
            actor_id=user["id"], actor_username=user["username"], actor_role=user["role"],
            ip_address=client_ip, details="Attempted login on deactivated account"
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="This account has been deactivated. Please contact the administrator."
        )

    # 4. Password verification using Argon2id
    if not verify_password(user["password_hash"], req.password):
        record_failed_login(client_key)
        log_security_event(
            db, action="LOGIN_FAILED_CREDENTIALS", status_code="401",
            actor_id=user["id"], actor_username=user["username"], actor_role=user["role"],
            ip_address=client_ip, details="Argon2id password verification failure"
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid username or password."
        )

    # 5. Clear failed attempts & create session
    record_successful_login(client_key)
    session = create_user_session(
        db, user_id=user["id"], ip_address=client_ip,
        user_agent=request.headers.get("user-agent")
    )

    # Update last login timestamp
    cursor.execute("UPDATE users SET last_login_at = CURRENT_TIMESTAMP WHERE id = ?", (user["id"],))
    db.commit()

    # Log security audit success
    log_security_event(
        db, action="LOGIN_SUCCESS", status_code="200",
        actor_id=user["id"], actor_username=user["username"], actor_role=user["role"],
        ip_address=client_ip, details=f"Stakeholder '{user['username']}' authenticated as '{user['role']}'"
    )

    # Set secure HTTP-only cookie
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=session["session_token"],
        httponly=True,
        samesite="lax",
        secure=SECURE_COOKIES,
        max_age=SESSION_EXPIRY_HOURS * 3600,
        path="/"
    )

    safe_user = {k: v for k, v in user.items() if k != "password_hash"}
    return {
        "status": "success",
        "message": "Login successful.",
        "user": safe_user,
        "session_token": session["session_token"],
        "csrf_token": session["csrf_token"],
        "expires_at": session["expires_at"]
    }


@app.post("/api/auth/logout")
def logout(
    request: Request,
    response: Response,
    db: sqlite3.Connection = Depends(get_live_db)
):
    """Revokes session and clears HTTP-only authentication cookie."""
    token = extract_token_from_request(request)
    client_ip = request.client.host if request.client else "unknown"
    if token:
        user = get_session_user(db, token)
        invalidate_user_session(db, token)
        if user:
            log_security_event(
                db, action="LOGOUT", status_code="200",
                actor_id=user["id"], actor_username=user["username"], actor_role=user["role"],
                ip_address=client_ip, details="Session terminated"
            )
    response.delete_cookie(key=SESSION_COOKIE_NAME, path="/")
    return {"status": "success", "message": "Successfully logged out."}


@app.get("/api/auth/me")
def get_current_user_profile(
    current_user: Optional[Dict[str, Any]] = Depends(get_current_user_optional)
):
    """Returns currently authenticated user profile or public citizen guest state."""
    if current_user:
        safe_user = {k: v for k, v in current_user.items() if k not in ("session_token", "password_hash")}
        return {
            "authenticated": True,
            "user": safe_user,
            "csrf_token": current_user.get("csrf_token")
        }
    return {
        "authenticated": False,
        "user": {
            "id": None,
            "username": "anonymous",
            "full_name": "Public Citizen",
            "role": "citizen",
            "is_active": 1,
            "state": "National",
            "district": "National",
            "constituency": "National",
            "agency_id": None,
            "agency_name": None,
            "designation": "Citizen / Public Observer"
        },
        "csrf_token": None
    }


# --- Admin User & Security Audit Routes ---

@app.get("/api/admin/users")
def get_admin_users(
    current_user: Dict[str, Any] = Depends(require_role("admin")),
    db: sqlite3.Connection = Depends(get_live_db)
):
    """Admin: lists all system users with roles and status."""
    cursor = db.cursor()
    cursor.execute("""
        SELECT id, username, full_name, email, role, state, district,
               constituency, agency_id, agency_name, designation,
               is_active, last_login_at, created_at
        FROM users
        ORDER BY id ASC
    """)
    return {"users": [dict(r) for r in cursor.fetchall()]}


@app.post("/api/admin/users")
def create_admin_user(
    req: CreateUserRequest,
    current_user: Dict[str, Any] = Depends(require_role("admin")),
    db: sqlite3.Connection = Depends(get_live_db)
):
    """Admin: provisions a new stakeholder user with Argon2id hashed password."""
    cursor = db.cursor()
    cursor.execute("SELECT id FROM users WHERE LOWER(username) = LOWER(?)", (req.username.strip(),))
    if cursor.fetchone():
        raise HTTPException(status_code=400, detail=f"Username '{req.username}' already exists.")

    hashed_pw = hash_password(req.password)
    cursor.execute("""
        INSERT INTO users (
            username, password_hash, full_name, email, role,
            state, district, constituency, agency_id, agency_name, designation, is_active
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 1)
    """, (
        req.username.strip(), hashed_pw, req.full_name.strip(), req.email.strip(), req.role,
        req.state, req.district, req.constituency, req.agency_id, req.agency_name, req.designation
    ))
    db.commit()
    new_user_id = cursor.lastrowid
    log_security_event(
        db, action="ADMIN_CREATE_USER", status_code="201",
        actor_id=current_user["id"], actor_username=current_user["username"], actor_role=current_user["role"],
        resource_type="user", resource_id=str(new_user_id), details=f"Created user '{req.username}' with role '{req.role}'"
    )
    return {"success": True, "message": f"User '{req.username}' created successfully.", "user_id": new_user_id}


@app.patch("/api/admin/users/{user_id}/status")
def update_user_status(
    user_id: int,
    req: UpdateUserStatusRequest,
    current_user: Dict[str, Any] = Depends(require_role("admin")),
    db: sqlite3.Connection = Depends(get_live_db)
):
    """Admin: activates or deactivates a user account."""
    cursor = db.cursor()
    cursor.execute("SELECT id, username, role FROM users WHERE id = ?", (user_id,))
    target = cursor.fetchone()
    if not target:
        raise HTTPException(status_code=404, detail="User not found.")
    
    target_user = dict(target)
    if target_user["id"] == current_user["id"] and req.is_active == 0:
        raise HTTPException(status_code=400, detail="Administrators cannot deactivate their own account.")

    cursor.execute("UPDATE users SET is_active = ? WHERE id = ?", (req.is_active, user_id))
    # If deactivating user, invalidate their active sessions
    if req.is_active == 0:
        cursor.execute("DELETE FROM sessions WHERE user_id = ?", (user_id,))
    db.commit()

    log_security_event(
        db, action="ADMIN_UPDATE_USER_STATUS", status_code="200",
        actor_id=current_user["id"], actor_username=current_user["username"], actor_role=current_user["role"],
        resource_type="user", resource_id=str(user_id),
        details=f"Changed active status of '{target_user['username']}' to {req.is_active}"
    )
    return {"success": True, "message": f"User status updated to {'active' if req.is_active else 'inactive'}."}


@app.get("/api/admin/security-logs")
def get_security_audit_logs(
    limit: int = Query(50, ge=1, le=200),
    current_user: Dict[str, Any] = Depends(require_role("admin")),
    db: sqlite3.Connection = Depends(get_live_db)
):
    """Admin: retrieves persistent security audit trail."""
    cursor = db.cursor()
    cursor.execute("""
        SELECT id, actor_id, actor_username, actor_role, action,
               resource_type, resource_id, status, ip_address, details, created_at
        FROM security_audit_logs
        ORDER BY id DESC
        LIMIT ?
    """, (limit,))
    return {"logs": [dict(r) for r in cursor.fetchall()]}


@app.get("/api/auth/roles")
def get_demo_roles(db: sqlite3.Connection = Depends(get_live_db)):
    """Returns available stakeholder personas for testing the MVP."""
    cursor = db.cursor()
    cursor.execute("SELECT id, username, full_name, email, role, state, district, constituency, agency_name, designation FROM users WHERE is_active = 1")
    users = [dict(row) for row in cursor.fetchall()]
    return {
        "roles": [
            {"key": "citizen", "label": "Citizen / Public — Demo User", "description": "Public Read-Only Transparency Access"},
            {"key": "mp", "label": "MP Portal — Demo User", "description": "Recommend & Track Constituency Works"},
            {"key": "district_authority", "label": "District Authority — Demo User", "description": "Review, Sanction & Monitor Works"},
            {"key": "implementing_agency", "label": "Implementing Agency — Demo User", "description": "Execute & Update Physical/Financial Progress"},
            {"key": "admin", "label": "System Administrator", "description": "National Security & Portal Administration"}
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
            if st in ("COMPLETED", "WORK COMPLETED"):
                h_conditions.append("work_completion_status = 'COMPLETED'")
            elif st in ("IN_PROGRESS", "ONGOING"):
                h_conditions.append("work_completion_status != 'COMPLETED' AND portal_execution_status != 'Sanction'")
            elif st in ("SANCTIONED", "APPROVED", "SANCTION"):
                h_conditions.append("portal_execution_status = 'Sanction'")
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
                work_completion_status,
                portal_execution_status,
                sanction_date,
                completion_date,
                CASE WHEN work_completion_status = 'COMPLETED' THEN 100 ELSE 50 END as physical_progress_pct
            FROM historical_projects
            {h_where}
            ORDER BY sanction_date DESC
            LIMIT ? OFFSET ?
        """, h_params + [hist_limit, hist_offset])
        raw_hist = [dict(r) for r in h_cur.fetchall()]
        hist_records = []
        for r in raw_hist:
            if r["work_completion_status"] == "COMPLETED":
                r["status"] = "COMPLETED"
            elif r["portal_execution_status"] == "Sanction":
                r["status"] = "SANCTIONED"
            else:
                r["status"] = "IN_PROGRESS"
            hist_records.append(r)

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
    """Fetches comprehensive project details, milestones, payment tranches, ML monitoring metrics, and active alerts."""
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

        # Fetch project evidence
        l_cur.execute("SELECT * FROM project_evidence WHERE work_id = ? ORDER BY id DESC", (work_id,))
        ev_items = [dict(r) for r in l_cur.fetchall()]
        for item in ev_items:
            if item.get("screening_results") and isinstance(item["screening_results"], str):
                try:
                    item["screening_results"] = json.loads(item["screening_results"])
                except Exception:
                    pass

        ev_summary = {
            "total": len(ev_items),
            "verified": sum(1 for i in ev_items if i.get("verification_status") == "VERIFIED"),
            "pending": sum(1 for i in ev_items if i.get("verification_status") == "PENDING_VERIFICATION"),
            "rejected": sum(1 for i in ev_items if i.get("verification_status") == "REJECTED")
        }

        sanction_amt = d["sanction_amount"] or 0.0
        disb_amt = d["total_disbursed"] or 0.0

        alerts_list = []
        if disb_amt > sanction_amt and sanction_amt > 0:
            alerts_list.append({
                "alert_type": "Potential Budget Overrun",
                "severity": "HIGH",
                "reason": f"Disbursed funds (INR {disb_amt:,.2f}) exceed sanctioned outlay (INR {sanction_amt:,.2f}).",
                "explanation": "Reported cumulative disbursements exceed initial sanctioned budget allocation."
            })

        monitoring_data = {
            "anomaly_risk_score": 0.0,
            "anomaly_status": "NORMAL",
            "delay_status": "ONGOING_WITHIN_TARGET" if d["status"] != "COMPLETED" else "ON_TIME",
            "schedule_delay_days": 0,
            "budget_monitoring_status": "POTENTIAL_BUDGET_OVERRUN" if (disb_amt > sanction_amt and sanction_amt > 0) else ("FULLY_DISBURSED" if (disb_amt == sanction_amt and sanction_amt > 0) else "WITHIN_SANCTION"),
            "payment_tranche_count": len(payments),
            "max_single_tranche_ratio": max([(p.get("reported_fund_disbursed_amount", 0) / sanction_amt) for p in payments], default=0.0) if sanction_amt > 0 else 0.0,
            "vendor_unique_count": len(set(p.get("vendor_name_normalized") or p.get("vendor_name_raw") for p in payments if p.get("vendor_name_normalized") or p.get("vendor_name_raw")))
        }

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
            "audit_trail": logs,
            "monitoring": monitoring_data,
            "alerts": alerts_list,
            "evidence": ev_items,
            "evidence_summary": ev_summary
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

        # Query project_monitoring_features for ML screening & delay/budget metrics
        h_cur.execute("SELECT * FROM project_monitoring_features WHERE work_id = ?", (work_id,))
        mon_row = h_cur.fetchone()

        monitoring_data = {}
        alerts_list = []

        if mon_row:
            m = dict(mon_row)
            monitoring_data = {
                "anomaly_risk_score": m.get("anomaly_risk_score", 0.0),
                "anomaly_status": m.get("anomaly_status", "NORMAL"),
                "raw_anomaly_score": m.get("raw_anomaly_score", 0.0),
                "anomaly_prediction": m.get("anomaly_prediction", 1),
                "delay_status": m.get("delay_status", "ON_TIME"),
                "schedule_delay_days": m.get("schedule_delay_days", 0),
                "sanction_lead_time_days": m.get("sanction_lead_time_days", 0),
                "expected_duration_days": m.get("expected_duration_days", 0),
                "actual_duration_days": m.get("actual_duration_days"),
                "budget_monitoring_status": m.get("budget_monitoring_status", "WITHIN_SANCTION"),
                "budget_variance_amount": m.get("budget_variance_amount", 0.0),
                "budget_disbursement_ratio": m.get("budget_disbursement_ratio", 0.0),
                "payment_tranche_count": m.get("payment_tranche_count", 0),
                "max_single_tranche_ratio": m.get("max_single_tranche_ratio", 0.0),
                "vendor_unique_count": m.get("vendor_unique_count", 0),
                "first_payment_date": m.get("first_payment_date", ""),
                "latest_payment_date": m.get("latest_payment_date", "")
            }

            sanc_val = m.get("sanction_amount") or hd.get("sanction_amount") or 0.0
            disb_val = m.get("total_disbursed") or hd.get("total_disbursed") or 0.0

            if m.get("budget_monitoring_status") == "POTENTIAL_BUDGET_OVERRUN" or (disb_val > sanc_val and sanc_val > 0):
                alerts_list.append({
                    "alert_type": "Potential Budget Overrun",
                    "severity": "HIGH",
                    "reason": f"Disbursed funds (INR {disb_val:,.2f}) exceed sanctioned outlay (INR {sanc_val:,.2f}).",
                    "explanation": "Reported cumulative disbursements exceed initial sanctioned budget allocation."
                })
            if m.get("delay_status") in ("DELAYED", "ONGOING_DELAYED"):
                alerts_list.append({
                    "alert_type": "Delayed Project",
                    "severity": "HIGH" if m.get("delay_status") == "DELAYED" else "MEDIUM",
                    "reason": f"Schedule delay recorded: {m.get('schedule_delay_days', 0)} days past expected completion target.",
                    "explanation": "Recorded completion date or current timestamp exceeds expected completion timeline."
                })
            if m.get("anomaly_status") == "POTENTIAL ANOMALY":
                alerts_list.append({
                    "alert_type": "Potential ML Anomaly",
                    "severity": "HIGH" if m.get("anomaly_risk_score", 0) >= 80 else "MEDIUM",
                    "reason": f"Isolation Forest Anomaly Risk Score: {m.get('anomaly_risk_score', 0)}/100.",
                    "explanation": "Statistical feature pattern differs significantly from standard project baseline."
                })
            if m.get("max_single_tranche_ratio", 0) >= 0.95 and m.get("payment_tranche_count", 0) > 1:
                alerts_list.append({
                    "alert_type": "Payment Concentration",
                    "severity": "MEDIUM",
                    "reason": f"Single tranche concentration: {round(m.get('max_single_tranche_ratio', 0)*100, 1)}% of sanction in one payment.",
                    "explanation": "A high proportion of total sanctioned funds was released in a single expenditure event."
                })

        is_completed = (hd["work_completion_status"] == "COMPLETED")

        audit_trail = []
        if hd.get("recommended_date"):
            audit_trail.append({
                "actor_name": hd["mp_name"] or "Member of Parliament",
                "actor_role": "Member of Parliament",
                "action": "Recommended Work",
                "created_at": hd["recommended_date"]
            })
        if hd.get("sanction_date"):
            audit_trail.append({
                "actor_name": hd["ida"] or "District Authority",
                "actor_role": "District Authority",
                "action": "Sanctioned Work Outlay",
                "created_at": hd["sanction_date"]
            })
        if hd.get("completion_date") and is_completed:
            audit_trail.append({
                "actor_name": hd["primary_vendor"] or "Implementing Agency",
                "actor_role": "Implementing Agency",
                "action": "Civil Work Marked Completed",
                "created_at": hd["completion_date"]
            })

        # Fetch project evidence for historical works
        l_cur.execute("SELECT * FROM project_evidence WHERE work_id = ? ORDER BY id DESC", (work_id,))
        hev_items = [dict(r) for r in l_cur.fetchall()]
        for item in hev_items:
            if item.get("screening_results") and isinstance(item["screening_results"], str):
                try:
                    item["screening_results"] = json.loads(item["screening_results"])
                except Exception:
                    pass

        hev_summary = {
            "total": len(hev_items),
            "verified": sum(1 for i in hev_items if i.get("verification_status") == "VERIFIED"),
            "pending": sum(1 for i in hev_items if i.get("verification_status") == "PENDING_VERIFICATION"),
            "rejected": sum(1 for i in hev_items if i.get("verification_status") == "REJECTED")
        }

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
                "status": "COMPLETED" if is_completed else ("SANCTIONED" if hd.get("portal_execution_status") == "Sanction" else "IN_PROGRESS"),
                "portal_execution_status": hd["portal_execution_status"],
                "physical_progress_pct": 100 if is_completed else None,
                "recommended_date": hd["recommended_date"],
                "sanction_date": hd["sanction_date"],
                "expected_completion_date": hd["expected_completion_date_proxy"],
                "completion_date": hd["completion_date"],
                "image_reference": hd["image_reference"],
                "assigned_agency_name": hd["primary_vendor"] or "Implementing Agency"
            },
            "payments": pay_rows,
            "progress_updates": [],
            "audit_trail": audit_trail,
            "monitoring": monitoring_data,
            "alerts": alerts_list,
            "evidence": hev_items,
            "evidence_summary": hev_summary
        }

    raise HTTPException(status_code=404, detail=f"Work with ID '{work_id}' not found.")


# --- MP Portal Endpoints ---

# --- MP Portal Endpoints ---

@app.get("/api/mp/dashboard")
def get_mp_dashboard(
    mp_name: Optional[str] = Query(None),
    current_user: Dict[str, Any] = Depends(require_role("mp", "admin")),
    h_db: sqlite3.Connection = Depends(get_historical_db),
    l_db: sqlite3.Connection = Depends(get_live_db)
):
    """Returns dashboard metrics and tracking list for the MP."""
    h_cur = h_db.cursor()
    l_cur = l_db.cursor()

    # Scope validation: if role is 'mp', lock to current_user's identity and prevent unauthorized inspection
    if current_user["role"] == "mp":
        enforce_mp_scope(current_user, mp_name)
        mp_name = current_user.get("full_name") or current_user.get("username")
    elif not mp_name or not mp_name.strip():
        # If admin without specified MP, dynamically select first distinct MP from historical dataset
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
    current_user: Dict[str, Any] = Depends(require_role("mp", "admin")),
    l_db: sqlite3.Connection = Depends(get_live_db)
):
    """MP submits a new development work recommendation with server-side identity binding."""
    l_cur = l_db.cursor()
    now_str = datetime.datetime.now().strftime("%Y-%m-%d")
    current_year = datetime.datetime.now().year
    year_str = f"{current_year}-{current_year + 1}"

    # Server-side identity & jurisdiction binding
    mp_name = current_user["full_name"] if current_user["role"] == "mp" else (req.recommending_mp_name or current_user["full_name"])
    mp_id = current_user["id"]
    state = current_user["state"] if (current_user["role"] == "mp" and current_user.get("state")) else req.state
    district = current_user["district"] if (current_user["role"] == "mp" and current_user.get("district")) else req.district
    constituency = current_user["constituency"] if (current_user["role"] == "mp" and current_user.get("constituency")) else req.constituency

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
        work_id, req.title, req.description, req.work_category, state, district,
        f"{district.upper()}(DISTRICT MAGISTRATE {district.upper()}_IDA)",
        constituency, req.location, req.priority, req.beneficiary_purpose,
        req.estimated_amount, mp_id, mp_name, now_str
    ))

    # Insert audit entry
    l_cur.execute("""
        INSERT INTO audit_logs (work_id, actor_id, actor_name, actor_role, action, old_status, new_status, comments)
        VALUES (?, ?, ?, 'Member of Parliament', 'RECOMMENDED_WORK', NULL, 'RECOMMENDED', ?)
    """, (work_id, current_user["id"], mp_name, f"Work recommended with estimated outlay of ₹{req.estimated_amount:,.2f}"))

    # Create notification for District Authority
    l_cur.execute("""
        INSERT INTO notifications (target_role, title, message, work_id)
        VALUES ('district_authority', 'New Work Recommendation', ?, ?)
    """, (f"MP {mp_name} recommended new work: '{req.title}'", work_id))

    l_db.commit()

    log_security_event(
        l_db, action="WORK_RECOMMENDED", status_code="201",
        actor_id=current_user["id"], actor_username=current_user["username"], actor_role=current_user["role"],
        resource_type="work", resource_id=work_id, details=f"MP recommended work '{work_id}' with outlay ₹{req.estimated_amount}"
    )

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
    current_user: Dict[str, Any] = Depends(require_role("district_authority", "admin")),
    h_db: sqlite3.Connection = Depends(get_historical_db),
    l_db: sqlite3.Connection = Depends(get_live_db)
):
    """District Authority dashboard: scoped to jurisdiction with mandatory district access control."""
    h_cur = h_db.cursor()
    l_cur = l_db.cursor()

    def is_valid_filter(val):
        if not val or not isinstance(val, str):
            return False
        v = val.strip().lower()
        return v != "" and not v.startswith("all")

    # Scope enforcement: District Authority users are locked to their assigned district & state
    if current_user["role"] == "district_authority":
        user_state = current_user.get("state") or "Madhya Pradesh"
        user_district = current_user.get("district") or "Agar-Malwa"
        # If user queries a specific state/district, enforce that it matches their assigned jurisdiction
        if is_valid_filter(state) or is_valid_filter(district):
            enforce_da_scope(current_user, state or user_state, district or user_district)
        state = user_state
        district = user_district
    elif state is None and district is None:
        # Default for admin when not specified
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
    current_user: Dict[str, Any] = Depends(require_role("district_authority", "admin")),
    l_db: sqlite3.Connection = Depends(get_live_db)
):
    """District Authority approves or returns a work recommendation with jurisdiction enforcement."""
    l_cur = l_db.cursor()
    l_cur.execute("SELECT * FROM live_works WHERE work_id = ?", (req.work_id,))
    work = l_cur.fetchone()

    if not work:
        raise HTTPException(status_code=404, detail="Work not found.")

    work = dict(work)

    # Data-level scope enforcement: DA can only act on works within their assigned district
    enforce_da_scope(current_user, work["state"], work["district"])

    old_status = work["status"]
    now_str = datetime.datetime.now().strftime("%Y-%m-%d")
    reviewer_name = current_user.get("full_name") or current_user.get("username")

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
        INSERT INTO audit_logs (work_id, actor_id, actor_name, actor_role, action, old_status, new_status, comments)
        VALUES (?, ?, ?, 'District Authority', ?, ?, ?, ?)
    """, (req.work_id, current_user["id"], reviewer_name, f"DA_{req.action}", old_status, new_status, action_desc))

    l_db.commit()

    log_security_event(
        l_db, action=f"DA_WORK_{req.action}", status_code="200",
        actor_id=current_user["id"], actor_username=current_user["username"], actor_role=current_user["role"],
        resource_type="work", resource_id=req.work_id,
        details=f"DA {req.action} work {req.work_id} in {work['district']}, {work['state']}"
    )

    return {
        "success": True,
        "work_id": req.work_id,
        "new_status": new_status,
        "message": f"Work successfully updated to {new_status}."
    }


# --- Implementing Agency Endpoints ---

@app.get("/api/agency/dashboard")
def get_agency_dashboard(
    current_user: Dict[str, Any] = Depends(require_role("implementing_agency", "admin")),
    l_db: sqlite3.Connection = Depends(get_live_db)
):
    """Implementing Agency dashboard: displays works scoped strictly to the assigned agency."""
    l_cur = l_db.cursor()

    if current_user["role"] == "implementing_agency":
        user_agency_name = current_user.get("agency_name") or ""
        user_agency_id = current_user.get("agency_id")
        user_id = current_user.get("id")

        l_cur.execute("""
            SELECT * FROM live_works 
            WHERE status IN ('APPROVED', 'ASSIGNED', 'IN_PROGRESS', 'COMPLETED')
              AND (
                  assigned_agency_id = ?
                  OR assigned_agency_id = ?
                  OR LOWER(assigned_agency_name) = LOWER(?)
              )
            ORDER BY id DESC
        """, (user_agency_id, user_id, user_agency_name))
    else:
        # Admin can view all assigned agency works
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
    current_user: Dict[str, Any] = Depends(require_role("implementing_agency", "admin")),
    l_db: sqlite3.Connection = Depends(get_live_db)
):
    """Agency submits physical progress, status change, and expenditure with agency ownership validation."""
    l_cur = l_db.cursor()
    l_cur.execute("SELECT * FROM live_works WHERE work_id = ?", (req.work_id,))
    work = l_cur.fetchone()

    if not work:
        raise HTTPException(status_code=404, detail="Work not found.")

    work = dict(work)

    # Data-level scope enforcement: agency can only update projects assigned to them
    enforce_ia_scope(current_user, work.get("assigned_agency_id"), work.get("assigned_agency_name"))

    old_status = work["status"]
    now_str = datetime.datetime.now().strftime("%Y-%m-%d")
    actor_name = current_user.get("full_name") or current_user.get("username")

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
        INSERT INTO audit_logs (work_id, actor_id, actor_name, actor_role, action, old_status, new_status, comments)
        VALUES (?, ?, ?, 'Implementing Agency', 'UPDATE_PROGRESS', ?, ?, ?)
    """, (
        req.work_id, current_user["id"], actor_name,
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

    log_security_event(
        l_db, action="AGENCY_UPDATE_PROGRESS", status_code="200",
        actor_id=current_user["id"], actor_username=current_user["username"], actor_role=current_user["role"],
        resource_type="work", resource_id=req.work_id,
        details=f"Agency updated work {req.work_id} to {req.physical_progress_pct}%"
    )

    return {
        "success": True,
        "work_id": req.work_id,
        "physical_progress_pct": req.physical_progress_pct,
        "status": req.status,
        "message": "Progress and expenditure successfully updated."
    }


# --- PROJECT MONITORING & ML ANOMALY DETECTION ENDPOINTS ---

from backend.monitoring_ml import init_monitoring_if_needed, run_monitoring_pipeline
from backend.delay_prediction_ml import init_delay_prediction_if_needed, train_delay_model, get_model_status

@app.on_event("startup")
def startup_event():
    conn = sqlite3.connect(HISTORICAL_DB_PATH)
    try:
        init_monitoring_if_needed(conn)
        init_delay_prediction_if_needed(conn)
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
    """Returns deterministic alerts for potential budget overruns, schedule delays, ML anomalies, and payment concentration spikes."""
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

    # Evaluate alert conditions across ALL matching project records to determine true total_alerts
    h_cur.execute(f"""
        SELECT work_id, state, district, constituency, mp_name, work_title, sanction_amount, total_disbursed,
               budget_monitoring_status, delay_status, payment_tranche_count, max_single_tranche_ratio,
               anomaly_status, anomaly_risk_score
        FROM project_monitoring_features
        {where_sql}
        ORDER BY anomaly_risk_score DESC, schedule_delay_days DESC
    """, params)

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
                "severity": "HIGH" if r["delay_status"] == "DELAYED" else "MEDIUM",
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
                "alert_type": "Payment Concentration",
                "severity": "MEDIUM",
                "measured_value": f"Payment Concentration: Single tranche ratio {round(r['max_single_tranche_ratio']*100, 1)}% of sanctioned amount",
                "anomaly_risk_score": r["anomaly_risk_score"]
            })

    # 5. Early Warning: High Predicted Delay Risk for Ongoing Projects Approaching Deadline
    try:
        dp_cur = h_db.cursor()
        dp_cur.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='project_delay_predictions'")
        if dp_cur.fetchone():
            dp_conditions = ["work_completion_status != 'COMPLETED'", "risk_level = 'HIGH'", "approaching_deadline = 1"]
            dp_params = []
            if is_valid_filter(state):
                dp_conditions.append("state = ?")
                dp_params.append(state.strip())
            if is_valid_filter(district):
                dp_conditions.append("district = ?")
                dp_params.append(district.strip())
            dp_where_sql = "WHERE " + " AND ".join(dp_conditions)
            dp_cur.execute(f"""
                SELECT work_id, state, district, work_title, predicted_delay_prob, days_to_deadline, delay_risk_score
                FROM project_delay_predictions
                {dp_where_sql}
                ORDER BY predicted_delay_prob DESC, days_to_deadline ASC
                LIMIT 25
            """, dp_params)
            for dr in dp_cur.fetchall():
                alerts.append({
                    "work_id": dr["work_id"],
                    "state": dr["state"],
                    "district": dr["district"],
                    "work_title": dr["work_title"],
                    "alert_type": "High Delay Risk Early Warning",
                    "severity": "HIGH",
                    "measured_value": f"Predicted Delay Probability: {round(dr['predicted_delay_prob']*100, 1)}% | Due in {dr['days_to_deadline']} days",
                    "anomaly_risk_score": dr["delay_risk_score"]
                })
    except Exception:
        pass

    # Sort alerts: High delay early warnings and HIGH severity first, then by risk score descending
    alerts.sort(key=lambda x: (
        0 if x.get("alert_type") == "High Delay Risk Early Warning" else (1 if x.get("severity") == "HIGH" else 2),
        -float(x.get("anomaly_risk_score") or 0.0)
    ))

    return {"total_alerts": len(alerts), "alerts": alerts[:limit]}


@app.get("/api/analytics/monitoring")
def get_analytics_monitoring(
    h_db: sqlite3.Connection = Depends(get_historical_db)
):
    """Provides backend data for 8 dynamic charts in the Analytics section."""
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


@app.get("/api/analytics/risk-map")
def get_analytics_risk_map(
    metric: Optional[str] = Query("avg_risk"),
    state: Optional[str] = Query(None),
    h_db: sqlite3.Connection = Depends(get_historical_db)
):
    """Provides aggregated ML risk metrics and anomaly distributions for state and district heat maps."""
    h_cur = h_db.cursor()

    if state and state.strip() and not state.strip().lower().startswith("all"):
        # District level breakdown for selected state
        h_cur.execute("""
            SELECT 
                district,
                COUNT(*) as project_count,
                COALESCE(SUM(sanction_amount), 0.0) as total_sanction,
                COALESCE(SUM(total_disbursed), 0.0) as total_disbursed,
                AVG(anomaly_risk_score) as avg_risk,
                SUM(CASE WHEN anomaly_risk_score >= 50 OR anomaly_status = 'POTENTIAL ANOMALY' THEN 1 ELSE 0 END) as high_risk_count,
                SUM(CASE WHEN anomaly_status = 'POTENTIAL ANOMALY' THEN 1 ELSE 0 END) as anomaly_count,
                SUM(CASE WHEN delay_status IN ('DELAYED', 'ONGOING_DELAYED') THEN 1 ELSE 0 END) as delayed_count
            FROM project_monitoring_features
            WHERE UPPER(state) = UPPER(?) AND district IS NOT NULL AND TRIM(district) != ''
            GROUP BY district
            ORDER BY avg_risk DESC, project_count DESC
        """, (state.strip(),))
        raw_districts = [dict(r) for r in h_cur.fetchall()]
        districts = []
        for r in raw_districts:
            cnt = r["project_count"] or 0
            sanc = r["total_sanction"] or 0.0
            disb = r["total_disbursed"] or 0.0
            avg_r = round(r["avg_risk"] or 0.0, 1)
            high_risk = r["high_risk_count"] or 0
            anom_cnt = r["anomaly_count"] or 0
            del_cnt = r["delayed_count"] or 0

            disb_rate = round((disb / sanc * 100), 1) if sanc > 0 else 0.0
            anom_rate = round((anom_cnt / cnt * 100), 1) if cnt > 0 else 0.0
            delay_rate = round((del_cnt / cnt * 100), 1) if cnt > 0 else 0.0

            if avg_r < 20.0:
                risk_level = "LOWER"
                risk_label = "Lower Statistical Risk"
                color = "#107C41"
            elif avg_r < 40.0:
                risk_level = "MODERATE"
                risk_label = "Moderate Statistical Risk"
                color = "#F58220"
            else:
                risk_level = "HIGHER"
                risk_label = "Higher Statistical Risk"
                color = "#DC2626"

            districts.append({
                "district": r["district"],
                "project_count": cnt,
                "total_sanction": sanc,
                "total_disbursed": disb,
                "disbursement_rate": disb_rate,
                "avg_risk": avg_r,
                "high_risk_count": high_risk,
                "anomaly_count": anom_cnt,
                "anomaly_rate": anom_rate,
                "delayed_count": del_cnt,
                "delay_rate": delay_rate,
                "risk_level": risk_level,
                "risk_label": risk_label,
                "color": color
            })

        total_proj = sum(d["project_count"] for d in districts)
        total_sanc = sum(d["total_sanction"] for d in districts)
        total_disb = sum(d["total_disbursed"] for d in districts)
        sum_risk = sum(d["avg_risk"] * d["project_count"] for d in districts)
        high_risk = sum(d["high_risk_count"] for d in districts)
        anom_cnt = sum(d["anomaly_count"] for d in districts)
        del_cnt = sum(d["delayed_count"] for d in districts)

        avg_risk_val = round((sum_risk / total_proj), 1) if total_proj > 0 else 0.0
        disb_rate_val = round((total_disb / total_sanc * 100), 1) if total_sanc > 0 else 0.0

        return {
            "level": "state",
            "state": state.strip(),
            "selected_metric": metric or "avg_risk",
            "state_summary": {
                "state": state.strip(),
                "project_count": total_proj,
                "total_sanction": total_sanc,
                "total_disbursed": total_disb,
                "disbursement_rate": disb_rate_val,
                "avg_risk": avg_risk_val,
                "high_risk_count": high_risk,
                "anomaly_count": anom_cnt,
                "delayed_count": del_cnt
            },
            "districts": districts
        }
    else:
        # National level breakdown (States)
        h_cur.execute("""
            SELECT 
                state,
                COUNT(*) as project_count,
                COALESCE(SUM(sanction_amount), 0.0) as total_sanction,
                COALESCE(SUM(total_disbursed), 0.0) as total_disbursed,
                AVG(anomaly_risk_score) as avg_risk,
                SUM(CASE WHEN anomaly_risk_score >= 50 OR anomaly_status = 'POTENTIAL ANOMALY' THEN 1 ELSE 0 END) as high_risk_count,
                SUM(CASE WHEN anomaly_status = 'POTENTIAL ANOMALY' THEN 1 ELSE 0 END) as anomaly_count,
                SUM(CASE WHEN delay_status IN ('DELAYED', 'ONGOING_DELAYED') THEN 1 ELSE 0 END) as delayed_count
            FROM project_monitoring_features
            WHERE state IS NOT NULL AND TRIM(state) != ''
            GROUP BY state
            ORDER BY avg_risk DESC, project_count DESC
        """)
        raw_states = [dict(r) for r in h_cur.fetchall()]
        states = []
        for r in raw_states:
            cnt = r["project_count"] or 0
            sanc = r["total_sanction"] or 0.0
            disb = r["total_disbursed"] or 0.0
            avg_r = round(r["avg_risk"] or 0.0, 1)
            high_risk = r["high_risk_count"] or 0
            anom_cnt = r["anomaly_count"] or 0
            del_cnt = r["delayed_count"] or 0

            disb_rate = round((disb / sanc * 100), 1) if sanc > 0 else 0.0
            anom_rate = round((anom_cnt / cnt * 100), 1) if cnt > 0 else 0.0
            delay_rate = round((del_cnt / cnt * 100), 1) if cnt > 0 else 0.0

            if avg_r < 18.0:
                risk_level = "LOWER"
                risk_label = "Lower Statistical Risk"
                color = "#107C41"
            elif avg_r < 23.0:
                risk_level = "MODERATE"
                risk_label = "Moderate Statistical Risk"
                color = "#F58220"
            else:
                risk_level = "HIGHER"
                risk_label = "Higher Statistical Risk"
                color = "#DC2626"

            states.append({
                "state": r["state"],
                "project_count": cnt,
                "total_sanction": sanc,
                "total_disbursed": disb,
                "disbursement_rate": disb_rate,
                "avg_risk": avg_r,
                "high_risk_count": high_risk,
                "anomaly_count": anom_cnt,
                "anomaly_rate": anom_rate,
                "delayed_count": del_cnt,
                "delay_rate": delay_rate,
                "risk_level": risk_level,
                "risk_label": risk_label,
                "color": color
            })

        total_proj = sum(s["project_count"] for s in states)
        total_sanc = sum(s["total_sanction"] for s in states)
        total_disb = sum(s["total_disbursed"] for s in states)
        sum_risk = sum(s["avg_risk"] * s["project_count"] for s in states)
        high_risk = sum(s["high_risk_count"] for s in states)
        anom_cnt = sum(s["anomaly_count"] for s in states)
        del_cnt = sum(s["delayed_count"] for s in states)

        avg_risk_val = round((sum_risk / total_proj), 1) if total_proj > 0 else 0.0
        disb_rate_val = round((total_disb / total_sanc * 100), 1) if total_sanc > 0 else 0.0

        return {
            "level": "national",
            "selected_metric": metric or "avg_risk",
            "national_summary": {
                "project_count": total_proj,
                "total_sanction": total_sanc,
                "total_disbursed": total_disb,
                "disbursement_rate": disb_rate_val,
                "avg_risk": avg_risk_val,
                "high_risk_count": high_risk,
                "anomaly_count": anom_cnt,
                "delayed_count": del_cnt
            },
            "states": states
        }


@app.get("/api/analytics/risk-map/projects")
def get_analytics_risk_map_projects(
    state: str = Query(...),
    district: str = Query(...),
    limit: int = Query(50, ge=1, le=100),
    page: int = Query(1, ge=1),
    h_db: sqlite3.Connection = Depends(get_historical_db)
):
    """Returns compact project list for selected state & district to inspect in Project 360 view."""
    h_cur = h_db.cursor()
    offset = (page - 1) * limit

    h_cur.execute("""
        SELECT COUNT(*) FROM project_monitoring_features
        WHERE TRIM(UPPER(state)) = TRIM(UPPER(?)) AND TRIM(UPPER(district)) = TRIM(UPPER(?))
    """, (state.strip(), district.strip()))
    total_count = h_cur.fetchone()[0] or 0

    h_cur.execute("""
        SELECT 
            work_id,
            work_title,
            constituency,
            mp_name,
            work_completion_status,
            portal_execution_status,
            sanction_amount,
            total_disbursed,
            anomaly_risk_score,
            anomaly_status,
            delay_status
        FROM project_monitoring_features
        WHERE TRIM(UPPER(state)) = TRIM(UPPER(?)) AND TRIM(UPPER(district)) = TRIM(UPPER(?))
        ORDER BY anomaly_risk_score DESC, sanction_amount DESC
        LIMIT ? OFFSET ?
    """, (state.strip(), district.strip(), limit, offset))
    
    rows = [dict(r) for r in h_cur.fetchall()]
    items = []
    for r in rows:
        is_comp = (r["work_completion_status"] == "COMPLETED")
        status = "COMPLETED" if is_comp else ("SANCTIONED" if r.get("portal_execution_status") == "Sanction" else "IN_PROGRESS")
        sanc = r["sanction_amount"] or 0.0
        disb = r["total_disbursed"] or 0.0
        disb_rate = round((disb / sanc * 100), 1) if sanc > 0 else 0.0
        
        items.append({
            "work_id": r["work_id"],
            "work_title": r["work_title"],
            "constituency": r["constituency"],
            "mp_name": r["mp_name"],
            "status": status,
            "sanction_amount": sanc,
            "total_disbursed": disb,
            "disbursement_rate": disb_rate,
            "anomaly_risk_score": round(r["anomaly_risk_score"] or 0.0, 1),
            "anomaly_status": r["anomaly_status"] or "NORMAL",
            "delay_status": r["delay_status"] or "ON_TIME"
        })

    return {
        "state": state.strip(),
        "district": district.strip(),
        "total": total_count,
        "page": page,
        "limit": limit,
        "items": items
    }


@app.post("/api/ml/retrain")
def retrain_ml_model(
    contamination: float = Query(0.05, ge=0.01, le=0.2),
    current_user: Dict[str, Any] = Depends(require_role("admin")),
    h_db: sqlite3.Connection = Depends(get_historical_db)
):
    """Triggers ML Isolation Forest retraining with admin-only authorization."""
    try:
        run_monitoring_pipeline(h_db, contamination=contamination)
        log_security_event(
            h_db, action="ML_RETRAIN", status_code="200",
            actor_id=current_user["id"], actor_username=current_user["username"], actor_role=current_user["role"],
            resource_type="ml_model", details=f"Retrained Isolation Forest with contamination={contamination}"
        )
        return {
            "success": True,
            "message": f"ML Isolation Forest successfully retrained with contamination rate = {contamination}.",
            "contamination": contamination
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"ML retraining failed: {str(e)}")


# --- AI-POWERED DELAY PREDICTION & EARLY WARNING ENDPOINTS ---

@app.get("/api/delay-prediction/readiness")
def get_delay_model_readiness(
    h_db: sqlite3.Connection = Depends(get_historical_db)
):
    """Returns model operational readiness and data eligibility audit."""
    try:
        status = get_model_status(h_db)
        return status
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to check delay model readiness: {str(e)}")


@app.get("/api/delay-prediction/metrics")
def get_delay_model_metrics(
    h_db: sqlite3.Connection = Depends(get_historical_db)
):
    """Returns supervised Random Forest evaluation metrics, confusion matrix, and feature importances."""
    status = get_model_status(h_db)
    if not status.get("ready"):
        return {
            "ready": False,
            "message": "Model is not ready. Train the model using the administrative retrain action.",
            "data_eligibility": status.get("data_eligibility")
        }
    return status.get("manifest", {})


@app.get("/api/delay-prediction/summary")
def get_delay_prediction_summary(
    state: Optional[str] = Query(None),
    district: Optional[str] = Query(None),
    h_db: sqlite3.Connection = Depends(get_historical_db)
):
    """Returns summary KPI card statistics for assessed projects, risk levels, and approaching deadlines."""
    h_cur = h_db.cursor()
    h_cur.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='project_delay_predictions'")
    if not h_cur.fetchone():
        return {
            "ready": False,
            "total_assessed": 0,
            "high_risk_count": 0,
            "medium_risk_count": 0,
            "low_risk_count": 0,
            "approaching_deadline_count": 0
        }

    conditions = []
    params = []

    def is_valid_filter(val):
        if not val or not isinstance(val, str):
            return False
        v = val.strip().lower()
        return v != "" and not v.startswith("all")

    if is_valid_filter(state):
        conditions.append("state = ?")
        params.append(state.strip())
    if is_valid_filter(district):
        conditions.append("district = ?")
        params.append(district.strip())

    where_sql = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    h_cur.execute(f"""
        SELECT
            COUNT(*) as total_assessed,
            SUM(CASE WHEN risk_level = 'HIGH' THEN 1 ELSE 0 END) as high_risk_count,
            SUM(CASE WHEN risk_level = 'MEDIUM' THEN 1 ELSE 0 END) as medium_risk_count,
            SUM(CASE WHEN risk_level = 'LOW' THEN 1 ELSE 0 END) as low_risk_count,
            SUM(CASE WHEN approaching_deadline = 1 THEN 1 ELSE 0 END) as approaching_deadline_count,
            SUM(CASE WHEN work_completion_status = 'COMPLETED' THEN 1 ELSE 0 END) as completed_training_count,
            SUM(CASE WHEN work_completion_status != 'COMPLETED' THEN 1 ELSE 0 END) as ongoing_monitored_count
        FROM project_delay_predictions
        {where_sql}
    """, params)

    res = dict(h_cur.fetchone())
    return {
        "ready": True,
        "total_assessed": res["total_assessed"] or 0,
        "high_risk_count": res["high_risk_count"] or 0,
        "medium_risk_count": res["medium_risk_count"] or 0,
        "low_risk_count": res["low_risk_count"] or 0,
        "approaching_deadline_count": res["approaching_deadline_count"] or 0,
        "completed_training_count": res["completed_training_count"] or 0,
        "ongoing_monitored_count": res["ongoing_monitored_count"] or 0
    }


@app.get("/api/delay-prediction/projects")
def get_delay_prediction_projects(
    page: int = Query(1, ge=1),
    limit: int = Query(20, ge=1, le=100),
    q: Optional[str] = Query(None),
    state: Optional[str] = Query(None),
    district: Optional[str] = Query(None),
    constituency: Optional[str] = Query(None),
    work_category: Optional[str] = Query(None),
    risk_level: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    approaching_deadline: Optional[int] = Query(None),
    h_db: sqlite3.Connection = Depends(get_historical_db)
):
    """Searchable & filterable project delay predictions table."""
    h_cur = h_db.cursor()
    h_cur.execute("SELECT 1 FROM sqlite_master WHERE type='table' AND name='project_delay_predictions'")
    if not h_cur.fetchone():
        return {"items": [], "total": 0, "page": page, "total_pages": 1, "ready": False}

    conditions = []
    params = []

    def is_valid_filter(val):
        if not val or not isinstance(val, str):
            return False
        v = val.strip().lower()
        return v != "" and not v.startswith("all")

    if q and q.strip():
        term = f"%{q.strip()}%"
        conditions.append("(work_id LIKE ? OR work_title LIKE ? OR mp_name LIKE ? OR constituency LIKE ?)")
        params.extend([term, term, term, term])

    if is_valid_filter(state):
        conditions.append("state = ?")
        params.append(state.strip())

    if is_valid_filter(district):
        conditions.append("district = ?")
        params.append(district.strip())

    if is_valid_filter(constituency):
        conditions.append("constituency = ?")
        params.append(constituency.strip())

    if is_valid_filter(work_category):
        conditions.append("work_category = ?")
        params.append(work_category.strip())

    if is_valid_filter(risk_level):
        conditions.append("risk_level = ?")
        params.append(risk_level.strip().upper())

    if is_valid_filter(status):
        st = status.strip().upper()
        if st == "COMPLETED":
            conditions.append("work_completion_status = 'COMPLETED'")
        elif st in ("ONGOING", "IN_PROGRESS", "NOT_COMPLETED"):
            conditions.append("work_completion_status != 'COMPLETED'")
        else:
            conditions.append("(work_completion_status = ? OR execution_status = ?)")
            params.extend([st, st])

    if approaching_deadline is not None:
        conditions.append("approaching_deadline = ?")
        params.append(int(approaching_deadline))

    where_sql = ("WHERE " + " AND ".join(conditions)) if conditions else ""

    # Total matching records
    h_cur.execute(f"SELECT COUNT(*) FROM project_delay_predictions {where_sql}", params)
    total_records = h_cur.fetchone()[0]
    total_pages = max(1, (total_records + limit - 1) // limit)

    offset = (page - 1) * limit
    h_cur.execute(f"""
        SELECT work_id, work_title, state, district, constituency, mp_name,
               work_category, sanction_date, expected_completion_date, completion_date,
               execution_status, work_completion_status, sanction_amount,
               early_disbursed_amount, early_disbursement_ratio, sanction_lead_time_days,
               predicted_delay_prob, delay_risk_score, risk_level, days_to_deadline,
               approaching_deadline, contributing_factors, was_delayed
        FROM project_delay_predictions
        {where_sql}
        ORDER BY predicted_delay_prob DESC, sanction_amount DESC
        LIMIT ? OFFSET ?
    """, params + [limit, offset])

    items = [dict(r) for r in h_cur.fetchall()]

    return {
        "ready": True,
        "items": items,
        "total": total_records,
        "page": page,
        "limit": limit,
        "total_pages": total_pages
    }


@app.get("/api/delay-prediction/project/{work_id:path}")
def get_project_delay_detail(
    work_id: str,
    h_db: sqlite3.Connection = Depends(get_historical_db)
):
    """Returns comprehensive delay prediction inspection detail for a single project."""
    h_cur = h_db.cursor()
    h_cur.execute("""
        SELECT * FROM project_delay_predictions WHERE work_id = ?
    """, (work_id.strip(),))
    row = h_cur.fetchone()
    if not row:
        raise HTTPException(status_code=404, detail=f"No delay prediction record found for Work ID: '{work_id}'.")

    p = dict(row)

    # Fetch recorded payment events
    h_cur.execute("""
        SELECT rowid as payment_event_id, source_serial_number, expenditure_date,
               reported_fund_disbursed_amount, payment_status, vendor_name_normalized
        FROM historical_payment_events
        WHERE work_id = ?
        ORDER BY expenditure_date ASC
    """, (work_id.strip(),))
    payments = [dict(r) for r in h_cur.fetchall()]

    return {
        "work_id": p["work_id"],
        "metadata": {
            "work_title": p["work_title"],
            "state": p["state"],
            "district": p["district"],
            "constituency": p["constituency"],
            "mp_name": p["mp_name"],
            "work_category": p["work_category"],
            "execution_status": p["execution_status"],
            "work_completion_status": p["work_completion_status"]
        },
        "timeline": {
            "sanction_date": p["sanction_date"],
            "expected_completion_date": p["expected_completion_date"],
            "completion_date": p["completion_date"],
            "days_to_deadline": p["days_to_deadline"],
            "approaching_deadline": bool(p["approaching_deadline"]),
            "was_delayed_actual": p["was_delayed"]
        },
        "financials": {
            "sanction_amount": p["sanction_amount"],
            "early_disbursed_amount": p["early_disbursed_amount"],
            "early_disbursement_ratio_pct": round(p["early_disbursement_ratio"] * 100, 2),
            "sanction_lead_time_days": p["sanction_lead_time_days"]
        },
        "prediction": {
            "predicted_delay_prob": p["predicted_delay_prob"],
            "delay_risk_score": p["delay_risk_score"],
            "risk_level": p["risk_level"],
            "contributing_factors": p["contributing_factors"]
        },
        "payments": payments,
        "disclaimer": (
            "The predicted delay probability represents the statistical likelihood that this project will exceed its "
            "statutory 1-year completion deadline based on historical patterns of sanction outlay, early disbursement, "
            "and approval lead times. It is a monitoring prioritization signal, not proof of negligence, corruption, or wrongdoing."
        )
    }


@app.post("/api/delay-prediction/retrain")
def retrain_delay_prediction_model(
    current_user: Dict[str, Any] = Depends(require_role("admin")),
    h_db: sqlite3.Connection = Depends(get_historical_db),
    l_db: sqlite3.Connection = Depends(get_live_db)
):
    """Retrains the supervised Random Forest delay prediction model (Admin-only)."""
    try:
        manifest = train_delay_model(h_db)
        log_security_event(
            l_db, action="DELAY_MODEL_RETRAIN", status_code="200",
            actor_id=current_user["id"], actor_username=current_user["username"], actor_role=current_user["role"],
            resource_type="delay_model", details=f"Retrained Random Forest: accuracy={manifest['metrics']['accuracy']}, roc_auc={manifest['metrics']['roc_auc']}"
        )
        return {
            "success": True,
            "message": "Supervised Random Forest Delay Prediction model retrained successfully.",
            "metrics": manifest["metrics"],
            "training_records": manifest["training_records"]
        }
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Delay model retraining failed: {str(e)}")


# --- Evidence & Verification Workflow Endpoints ---

@app.get("/api/projects/{work_id:path}/evidence")
def get_project_evidence(
    work_id: str,
    l_db: sqlite3.Connection = Depends(get_live_db)
):
    """Fetches evidence history and screening metrics for a project (public transparency)."""
    l_cur = l_db.cursor()
    l_cur.execute("SELECT * FROM project_evidence WHERE work_id = ? ORDER BY id DESC", (work_id,))
    items = [dict(r) for r in l_cur.fetchall()]

    for item in items:
        if item.get("screening_results") and isinstance(item["screening_results"], str):
            try:
                item["screening_results"] = json.loads(item["screening_results"])
            except Exception:
                pass

    summary = {
        "total": len(items),
        "verified": sum(1 for i in items if i.get("verification_status") == "VERIFIED"),
        "pending": sum(1 for i in items if i.get("verification_status") == "PENDING_VERIFICATION"),
        "rejected": sum(1 for i in items if i.get("verification_status") == "REJECTED")
    }

    return {
        "work_id": work_id,
        "summary": summary,
        "evidence": items
    }


@app.post("/api/projects/{work_id:path}/evidence")
async def submit_project_evidence(
    work_id: str,
    evidence_type: str = Form(...),
    milestone: Optional[str] = Form("Planning"),
    description: Optional[str] = Form(""),
    resubmit_of_id: Optional[int] = Form(None),
    file: UploadFile = File(...),
    current_user: Dict[str, Any] = Depends(require_role("implementing_agency", "admin")),
    l_db: sqlite3.Connection = Depends(get_live_db),
    h_db: sqlite3.Connection = Depends(get_historical_db)
):
    """Submits new evidence or resubmission for a project with automated screening and agency ownership enforcement."""
    filename = file.filename or "evidence_file.jpg"
    ext = os.path.splitext(filename)[1].lower()
    allowed_exts = [".jpg", ".jpeg", ".png", ".pdf"]
    if ext not in allowed_exts:
        raise HTTPException(status_code=400, detail=f"File extension '{ext}' is not supported. Allowed extensions: {', '.join(allowed_exts)}")

    file_bytes = await file.read()
    if len(file_bytes) > 10 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="File size exceeds maximum 10MB limit.")

    # Fetch work details for screening checks & agency ownership verification
    l_cur = l_db.cursor()
    l_cur.execute("SELECT * FROM live_works WHERE work_id = ?", (work_id,))
    work_row = l_cur.fetchone()

    work_data = {}
    if work_row:
        work_data = dict(work_row)
        # Data-level scope enforcement: ensure agency is assigned to this project
        enforce_ia_scope(current_user, work_data.get("assigned_agency_id"), work_data.get("assigned_agency_name"))
    else:
        h_cur = h_db.cursor()
        h_cur.execute("SELECT * FROM historical_projects WHERE work_id = ?", (work_id,))
        h_row = h_cur.fetchone()
        if h_row:
            work_data = dict(h_row)

    stored_filename = f"ev_{uuid.uuid4().hex}_{os.path.basename(filename)}"
    file_path = os.path.join(EVIDENCE_UPLOAD_DIR, stored_filename)

    with open(file_path, "wb") as f:
        f.write(file_bytes)

    # Fetch existing hashes for duplicate check
    l_cur.execute("SELECT file_hash FROM project_evidence WHERE file_hash IS NOT NULL")
    existing_hashes = [r[0] for r in l_cur.fetchall() if r[0]]

    screening_dict = run_evidence_screening(file_bytes, filename, work_data, existing_hashes)
    screening_json = json.dumps(screening_dict)

    resub_count = 0
    prev_id = None
    if resubmit_of_id:
        l_cur.execute("SELECT * FROM project_evidence WHERE id = ?", (resubmit_of_id,))
        prev_row = l_cur.fetchone()
        if prev_row:
            prev_data = dict(prev_row)
            resub_count = (prev_data.get("resubmission_count") or 0) + 1
            prev_id = prev_data["id"]

    mime_type = file.content_type or ("application/pdf" if ext == ".pdf" else "image/jpeg")
    submitted_by = current_user.get("username") or "agency"
    submitted_by_name = current_user.get("full_name") or current_user.get("agency_name") or "Implementing Agency"

    l_cur.execute("""
        INSERT INTO project_evidence (
            work_id, evidence_type, milestone, file_name, stored_file_name,
            file_path, file_size, mime_type, description, submitted_by,
            submitted_by_name, verification_status, resubmission_count,
            previous_evidence_id, file_hash, screening_results
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'PENDING_VERIFICATION', ?, ?, ?, ?)
    """, (
        work_id, evidence_type, milestone or "Planning", filename, stored_filename,
        file_path, len(file_bytes), mime_type, description, submitted_by,
        submitted_by_name, resub_count, prev_id, screening_dict["file_hash"], screening_json
    ))

    evidence_id = l_cur.lastrowid

    action_name = "EVIDENCE_RESUBMITTED" if prev_id else "EVIDENCE_SUBMITTED"
    action_desc = f"Submitted {evidence_type} ({milestone or 'N/A'}) for verification." + (f" [Resubmission #{resub_count}]" if prev_id else "")

    l_cur.execute("""
        INSERT INTO audit_logs (work_id, actor_id, actor_name, actor_role, action, old_status, new_status, comments)
        VALUES (?, ?, ?, 'Implementing Agency', ?, 'SUBMITTED', 'PENDING_VERIFICATION', ?)
    """, (work_id, current_user["id"], submitted_by_name, action_name, action_desc))

    l_cur.execute("""
        INSERT INTO notifications (target_role, title, message, work_id)
        VALUES ('district_authority', 'New Evidence Submitted', ?, ?)
    """, (f"Evidence ({evidence_type}) submitted for work '{work_data.get('title', work_id)}'.", work_id))

    l_db.commit()

    log_security_event(
        l_db, action=action_name, status_code="201",
        actor_id=current_user["id"], actor_username=current_user["username"], actor_role=current_user["role"],
        resource_type="evidence", resource_id=str(evidence_id),
        details=f"Agency submitted evidence for {work_id}"
    )

    return {
        "success": True,
        "message": "Evidence submitted successfully and queued for District Authority verification.",
        "evidence_id": evidence_id,
        "work_id": work_id,
        "verification_status": "PENDING_VERIFICATION",
        "screening": screening_dict
    }


@app.post("/api/evidence/{evidence_id}/verify")
def verify_evidence(
    evidence_id: int,
    comments: Optional[str] = Form(""),
    current_user: Dict[str, Any] = Depends(require_role("district_authority", "admin")),
    l_db: sqlite3.Connection = Depends(get_live_db)
):
    """District Authority verifies evidence submission with jurisdiction check."""
    l_cur = l_db.cursor()
    l_cur.execute("SELECT * FROM project_evidence WHERE id = ?", (evidence_id,))
    ev_row = l_cur.fetchone()

    if not ev_row:
        raise HTTPException(status_code=404, detail="Evidence item not found.")

    ev = dict(ev_row)

    # Enforce DA jurisdiction over the work's state and district
    l_cur.execute("SELECT state, district FROM live_works WHERE work_id = ?", (ev["work_id"],))
    work_row = l_cur.fetchone()
    if work_row:
        enforce_da_scope(current_user, work_row[0], work_row[1])

    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    verified_by = current_user.get("username")
    verified_by_name = current_user.get("full_name") or "District Authority"

    l_cur.execute("""
        UPDATE project_evidence SET
            verification_status = 'VERIFIED',
            verified_by = ?,
            verified_by_name = ?,
            verified_at = ?,
            verification_comments = ?
        WHERE id = ?
    """, (verified_by, verified_by_name, now_str, comments or "Verified by District Authority", evidence_id))

    l_cur.execute("""
        INSERT INTO audit_logs (work_id, actor_id, actor_name, actor_role, action, old_status, new_status, comments)
        VALUES (?, ?, ?, 'District Authority', 'EVIDENCE_VERIFIED', 'PENDING_VERIFICATION', 'VERIFIED', ?)
    """, (ev["work_id"], current_user["id"], verified_by_name, f"Verified {ev['evidence_type']} ({ev['milestone']}). Remarks: {comments or 'Approved'}"))

    l_cur.execute("""
        INSERT INTO notifications (target_role, title, message, work_id)
        VALUES ('implementing_agency', 'Evidence Verified', ?, ?)
    """, (f"Your evidence submission ({ev['evidence_type']}) for work '{ev['work_id']}' has been VERIFIED.", ev["work_id"]))

    l_db.commit()

    log_security_event(
        l_db, action="EVIDENCE_VERIFIED", status_code="200",
        actor_id=current_user["id"], actor_username=current_user["username"], actor_role=current_user["role"],
        resource_type="evidence", resource_id=str(evidence_id),
        details=f"DA verified evidence {evidence_id} for {ev['work_id']}"
    )

    return {
        "success": True,
        "message": "Evidence verified successfully.",
        "evidence_id": evidence_id,
        "status": "VERIFIED"
    }


@app.post("/api/evidence/{evidence_id}/reject")
def reject_evidence(
    evidence_id: int,
    reason: str = Form(...),
    current_user: Dict[str, Any] = Depends(require_role("district_authority", "admin")),
    l_db: sqlite3.Connection = Depends(get_live_db)
):
    """District Authority rejects evidence submission with mandatory reason and jurisdiction check."""
    if not reason or not reason.strip():
        raise HTTPException(status_code=400, detail="Rejection reason is mandatory.")

    l_cur = l_db.cursor()
    l_cur.execute("SELECT * FROM project_evidence WHERE id = ?", (evidence_id,))
    ev_row = l_cur.fetchone()

    if not ev_row:
        raise HTTPException(status_code=404, detail="Evidence item not found.")

    ev = dict(ev_row)

    # Enforce DA jurisdiction
    l_cur.execute("SELECT state, district FROM live_works WHERE work_id = ?", (ev["work_id"],))
    work_row = l_cur.fetchone()
    if work_row:
        enforce_da_scope(current_user, work_row[0], work_row[1])

    now_str = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    rejected_by = current_user.get("username")
    rejected_by_name = current_user.get("full_name") or "District Authority"

    l_cur.execute("""
        UPDATE project_evidence SET
            verification_status = 'REJECTED',
            verified_by = ?,
            verified_by_name = ?,
            verified_at = ?,
            verification_comments = ?
        WHERE id = ?
    """, (rejected_by, rejected_by_name, now_str, reason.strip(), evidence_id))

    l_cur.execute("""
        INSERT INTO audit_logs (work_id, actor_id, actor_name, actor_role, action, old_status, new_status, comments)
        VALUES (?, ?, ?, 'District Authority', 'EVIDENCE_REJECTED', 'PENDING_VERIFICATION', 'REJECTED', ?)
    """, (ev["work_id"], current_user["id"], rejected_by_name, f"Rejected {ev['evidence_type']}. Reason: {reason.strip()}"))

    l_cur.execute("""
        INSERT INTO notifications (target_role, title, message, work_id)
        VALUES ('implementing_agency', 'Evidence Rejected', ?, ?)
    """, (f"Your evidence ({ev['evidence_type']}) for work '{ev['work_id']}' was REJECTED: {reason.strip()}", ev["work_id"]))

    l_db.commit()

    log_security_event(
        l_db, action="EVIDENCE_REJECTED", status_code="200",
        actor_id=current_user["id"], actor_username=current_user["username"], actor_role=current_user["role"],
        resource_type="evidence", resource_id=str(evidence_id),
        details=f"DA rejected evidence {evidence_id}: {reason.strip()}"
    )

    return {
        "success": True,
        "message": "Evidence rejected with reason.",
        "evidence_id": evidence_id,
        "status": "REJECTED",
        "reason": reason.strip()
    }


@app.post("/api/evidence/{evidence_id}/resubmit")
async def resubmit_evidence_alias(
    evidence_id: int,
    file: UploadFile = File(...),
    description: Optional[str] = Form(""),
    current_user: Dict[str, Any] = Depends(require_role("implementing_agency", "admin")),
    l_db: sqlite3.Connection = Depends(get_live_db),
    h_db: sqlite3.Connection = Depends(get_historical_db)
):
    """Resubmits evidence for a previously rejected item with agency validation."""
    l_cur = l_db.cursor()
    l_cur.execute("SELECT * FROM project_evidence WHERE id = ?", (evidence_id,))
    ev_row = l_cur.fetchone()

    if not ev_row:
        raise HTTPException(status_code=404, detail="Target evidence item not found.")

    ev = dict(ev_row)
    return await submit_project_evidence(
        work_id=ev["work_id"],
        evidence_type=ev["evidence_type"],
        milestone=ev.get("milestone"),
        description=description or ev.get("description"),
        resubmit_of_id=evidence_id,
        file=file,
        current_user=current_user,
        l_db=l_db,
        h_db=h_db
    )


@app.get("/api/evidence/{evidence_id}/file")
def serve_evidence_file(
    evidence_id: int,
    l_db: sqlite3.Connection = Depends(get_live_db)
):
    """Serves evidence file safely with path traversal protection."""
    l_cur = l_db.cursor()
    l_cur.execute("SELECT stored_file_name, mime_type, file_name FROM project_evidence WHERE id = ?", (evidence_id,))
    row = l_cur.fetchone()

    if not row:
        raise HTTPException(status_code=404, detail="Evidence record not found.")

    stored_filename = row[0]
    mime_type = row[1] or "application/octet-stream"

    safe_name = os.path.basename(stored_filename)
    file_path = os.path.join(EVIDENCE_UPLOAD_DIR, safe_name)

    if not os.path.isfile(file_path):
        raise HTTPException(status_code=404, detail="Evidence file not found on server storage.")

    return FileResponse(file_path, media_type=mime_type, filename=row[2] or safe_name)


@app.get("/api/da/evidence-pending")
def get_da_pending_evidence(
    current_user: Dict[str, Any] = Depends(require_role("district_authority", "admin")),
    l_db: sqlite3.Connection = Depends(get_live_db)
):
    """Fetches all pending evidence submissions for District Authority review queue scoped to jurisdiction."""
    l_cur = l_db.cursor()

    if current_user["role"] == "district_authority":
        da_district = current_user.get("district") or ""
        l_cur.execute("""
            SELECT e.*, w.title as work_title, w.state, w.district, w.constituency
            FROM project_evidence e
            LEFT JOIN live_works w ON e.work_id = w.work_id
            WHERE e.verification_status = 'PENDING_VERIFICATION'
              AND (w.district IS NULL OR UPPER(w.district) = UPPER(?))
            ORDER BY e.id DESC
        """, (da_district,))
    else:
        l_cur.execute("""
            SELECT e.*, w.title as work_title, w.state, w.district, w.constituency
            FROM project_evidence e
            LEFT JOIN live_works w ON e.work_id = w.work_id
            WHERE e.verification_status = 'PENDING_VERIFICATION'
            ORDER BY e.id DESC
        """)

    rows = [dict(r) for r in l_cur.fetchall()]

    for r in rows:
        if r.get("screening_results") and isinstance(r["screening_results"], str):
            try:
                r["screening_results"] = json.loads(r["screening_results"])
            except Exception:
                pass

    return {
        "count": len(rows),
        "items": rows
    }


# Mount static assets directory
STATIC_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static")
app.mount("/", StaticFiles(directory=STATIC_DIR, html=True), name="static")
