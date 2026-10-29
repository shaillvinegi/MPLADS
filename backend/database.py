"""
Database connection and initialization module.
Manages both the Historical Read Layer and the Live Application Layer.
"""
import os
import sqlite3
from typing import Generator

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
HISTORICAL_DB_PATH = os.path.join(DATA_DIR, "mplads_historical.db")
LIVE_DB_PATH = os.path.join(DATA_DIR, "mplads_live.db")


def get_historical_db() -> Generator[sqlite3.Connection, None, None]:
    conn = sqlite3.connect(HISTORICAL_DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def get_live_db() -> Generator[sqlite3.Connection, None, None]:
    conn = sqlite3.connect(LIVE_DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def init_live_db():
    """Initializes tables in mplads_live.db."""
    conn = sqlite3.connect(LIVE_DB_PATH)
    cursor = conn.cursor()

    cursor.executescript("""
    CREATE TABLE IF NOT EXISTS users (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        username TEXT UNIQUE NOT NULL,
        password_hash TEXT NOT NULL,
        full_name TEXT NOT NULL,
        email TEXT NOT NULL,
        role TEXT NOT NULL, -- 'admin', 'mp', 'district_authority', 'implementing_agency', 'citizen'
        state TEXT,
        district TEXT,
        constituency TEXT,
        agency_id INTEGER,
        agency_name TEXT,
        designation TEXT,
        is_active INTEGER DEFAULT 1,
        failed_login_attempts INTEGER DEFAULT 0,
        locked_until TIMESTAMP,
        last_login_at TIMESTAMP,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS sessions (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        session_token TEXT UNIQUE NOT NULL,
        user_id INTEGER NOT NULL,
        csrf_token TEXT NOT NULL,
        ip_address TEXT,
        user_agent TEXT,
        expires_at TIMESTAMP NOT NULL,
        last_activity_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        FOREIGN KEY (user_id) REFERENCES users(id) ON DELETE CASCADE
    );

    CREATE TABLE IF NOT EXISTS security_audit_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        actor_id INTEGER,
        actor_username TEXT,
        actor_role TEXT,
        action TEXT NOT NULL,
        resource_type TEXT,
        resource_id TEXT,
        status TEXT NOT NULL,
        ip_address TEXT,
        details TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS live_works (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        work_id TEXT UNIQUE NOT NULL,
        source TEXT DEFAULT 'live',
        title TEXT NOT NULL,
        description TEXT,
        work_category TEXT NOT NULL,
        state TEXT NOT NULL,
        district TEXT NOT NULL,
        ida TEXT,
        constituency TEXT NOT NULL,
        location TEXT,
        priority TEXT DEFAULT 'Medium',
        beneficiary_purpose TEXT,
        estimated_amount REAL NOT NULL,
        sanction_amount REAL DEFAULT 0.0,
        status TEXT NOT NULL, -- 'RECOMMENDED', 'UNDER_REVIEW', 'APPROVED', 'ASSIGNED', 'IN_PROGRESS', 'COMPLETION_SUBMITTED', 'VERIFIED', 'COMPLETED', 'RETURNED', 'REJECTED', 'ON_HOLD'
        recommending_mp_id INTEGER,
        recommending_mp_name TEXT,
        recommended_date TEXT,
        review_date TEXT,
        review_comments TEXT,
        reviewed_by TEXT,
        sanction_date TEXT,
        assigned_agency_id INTEGER,
        assigned_agency_name TEXT,
        assigned_date TEXT,
        physical_progress_pct INTEGER DEFAULT 0,
        current_milestone TEXT DEFAULT 'Planning',
        expected_completion_date TEXT,
        completion_date TEXT,
        total_disbursed REAL DEFAULT 0.0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS live_progress_updates (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        work_id TEXT NOT NULL,
        agency_id INTEGER,
        agency_name TEXT,
        physical_progress_pct INTEGER NOT NULL,
        milestone TEXT NOT NULL,
        description TEXT NOT NULL,
        expenditure_incurred REAL DEFAULT 0.0,
        payment_notes TEXT,
        document_reference TEXT,
        status TEXT DEFAULT 'SUBMITTED', -- 'SUBMITTED', 'VERIFIED', 'REVISION_REQUESTED'
        review_comments TEXT,
        submitted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        reviewed_at TIMESTAMP,
        reviewed_by TEXT
    );

    CREATE TABLE IF NOT EXISTS live_payments (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        work_id TEXT NOT NULL,
        expenditure_date TEXT NOT NULL,
        vendor_name_raw TEXT NOT NULL,
        vendor_name_normalized TEXT NOT NULL,
        payment_status TEXT DEFAULT 'PAYMENT SUCCESS',
        reported_fund_disbursed_amount REAL NOT NULL,
        remarks TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS notifications (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        target_role TEXT, -- 'mp', 'district_authority', 'implementing_agency', 'all'
        title TEXT NOT NULL,
        message TEXT NOT NULL,
        work_id TEXT,
        is_read INTEGER DEFAULT 0,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS audit_logs (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        work_id TEXT NOT NULL,
        actor_id INTEGER,
        actor_name TEXT NOT NULL,
        actor_role TEXT NOT NULL,
        action TEXT NOT NULL,
        old_status TEXT,
        new_status TEXT,
        comments TEXT,
        created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
    );

    CREATE TABLE IF NOT EXISTS project_evidence (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        work_id TEXT NOT NULL,
        evidence_type TEXT NOT NULL,
        milestone TEXT,
        file_name TEXT NOT NULL,
        stored_file_name TEXT NOT NULL,
        file_path TEXT NOT NULL,
        file_size INTEGER,
        mime_type TEXT,
        description TEXT,
        submitted_by TEXT NOT NULL,
        submitted_by_name TEXT,
        submitted_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
        verification_status TEXT DEFAULT 'PENDING_VERIFICATION',
        verified_by TEXT,
        verified_by_name TEXT,
        verified_at TIMESTAMP,
        verification_comments TEXT,
        resubmission_count INTEGER DEFAULT 0,
        previous_evidence_id INTEGER,
        file_hash TEXT,
        screening_results TEXT
    );

    CREATE INDEX IF NOT EXISTS idx_users_username ON users(username);
    CREATE INDEX IF NOT EXISTS idx_users_role ON users(role);
    CREATE INDEX IF NOT EXISTS idx_sessions_token ON sessions(session_token);
    CREATE INDEX IF NOT EXISTS idx_sessions_user_id ON sessions(user_id);
    CREATE INDEX IF NOT EXISTS idx_sec_audit_user ON security_audit_logs(actor_username);
    CREATE INDEX IF NOT EXISTS idx_sec_audit_action ON security_audit_logs(action);
    CREATE INDEX IF NOT EXISTS idx_lw_work_id ON live_works(work_id);
    CREATE INDEX IF NOT EXISTS idx_lw_status ON live_works(status);
    CREATE INDEX IF NOT EXISTS idx_lw_mp ON live_works(recommending_mp_name);
    CREATE INDEX IF NOT EXISTS idx_lw_agency ON live_works(assigned_agency_id);
    CREATE INDEX IF NOT EXISTS idx_pu_work ON live_progress_updates(work_id);
    CREATE INDEX IF NOT EXISTS idx_notif_role ON notifications(target_role, is_read);
    CREATE INDEX IF NOT EXISTS idx_audit_work ON audit_logs(work_id);
    CREATE INDEX IF NOT EXISTS idx_evidence_work_id ON project_evidence(work_id);
    CREATE INDEX IF NOT EXISTS idx_evidence_status ON project_evidence(verification_status);
    """)

    # Safe Schema Migrations for users table (if table pre-existed with older columns)
    cursor.execute("PRAGMA table_info(users)")
    existing_cols = {col[1] for col in cursor.fetchall()}
    migrations = [
        ("agency_id", "INTEGER"),
        ("is_active", "INTEGER DEFAULT 1"),
        ("failed_login_attempts", "INTEGER DEFAULT 0"),
        ("locked_until", "TIMESTAMP"),
        ("last_login_at", "TIMESTAMP")
    ]
    for col_name, col_type in migrations:
        if col_name not in existing_cols:
            cursor.execute(f"ALTER TABLE users ADD COLUMN {col_name} {col_type};")

    # Argon2id Password Hasher for secure credential hashing
    from argon2 import PasswordHasher
    hasher = PasswordHasher(time_cost=2, memory_cost=65536, parallelism=1, hash_len=32, salt_len=16)

    # Seed / Update default stakeholder credentials with Argon2id hashes
    demo_accounts = [
        {
            "username": "admin_demo",
            "password": "Admin@MPLADS2026!",
            "full_name": "National Portal Administrator",
            "email": "admin.mplads@gov.in",
            "role": "admin",
            "state": "National",
            "district": "National",
            "constituency": "National",
            "agency_id": None,
            "agency_name": "Ministry of Statistics & Programme Implementation",
            "designation": "System Administrator",
            "is_active": 1
        },
        {
            "username": "mp_demo",
            "password": "MP@Sansad2026!",
            "full_name": "Mahendra Singh Solanky",
            "email": "solanky.mp@sansad.nic.in",
            "role": "mp",
            "state": "Madhya Pradesh",
            "district": "Agar-Malwa",
            "constituency": "DEWAS(SC)",
            "agency_id": None,
            "agency_name": None,
            "designation": "Member of Parliament (Lok Sabha)",
            "is_active": 1
        },
        {
            "username": "da_demo",
            "password": "DA@District2026!",
            "full_name": "District Magistrate / Collector (Agar-Malwa)",
            "email": "dm.agarmalwa@mp.gov.in",
            "role": "district_authority",
            "state": "Madhya Pradesh",
            "district": "Agar-Malwa",
            "constituency": "DEWAS(SC)",
            "agency_id": None,
            "agency_name": None,
            "designation": "District Authority & Collector",
            "is_active": 1
        },
        {
            "username": "da_jaipur",
            "password": "DA@Jaipur2026!",
            "full_name": "District Magistrate / Collector (Jaipur)",
            "email": "dm.jaipur@rajasthan.gov.in",
            "role": "district_authority",
            "state": "Rajasthan",
            "district": "Jaipur",
            "constituency": "JAIPUR RURAL",
            "agency_id": None,
            "agency_name": None,
            "designation": "District Authority & Collector (Jaipur)",
            "is_active": 1
        },
        {
            "username": "ia_demo",
            "password": "Agency@Field2026!",
            "full_name": "Executive Engineer - PWD",
            "email": "ee.pwd.agarmalwa@mp.gov.in",
            "role": "implementing_agency",
            "state": "Madhya Pradesh",
            "district": "Agar-Malwa",
            "constituency": "DEWAS(SC)",
            "agency_id": 1,
            "agency_name": "Public Works Department (PWD)",
            "designation": "Superintending Engineer (PWD)",
            "is_active": 1
        },
        {
            "username": "ia_rural",
            "password": "Agency@Rural2026!",
            "full_name": "Executive Engineer - MPRRDA",
            "email": "ee.mprrda.agarmalwa@mp.gov.in",
            "role": "implementing_agency",
            "state": "Madhya Pradesh",
            "district": "Agar-Malwa",
            "constituency": "DEWAS(SC)",
            "agency_id": 101,
            "agency_name": "MP Rural Road Development Authority",
            "designation": "Executive Engineer (MPRRDA)",
            "is_active": 1
        },
        {
            "username": "citizen_demo",
            "password": "Citizen@Public2026!",
            "full_name": "Citizen / Public User",
            "email": "citizen.demo@nic.in",
            "role": "citizen",
            "state": "Madhya Pradesh",
            "district": "Agar-Malwa",
            "constituency": "DEWAS(SC)",
            "agency_id": None,
            "agency_name": None,
            "designation": "Verified Citizen Observer",
            "is_active": 1
        },
        {
            "username": "anshikapathania@2702",
            "password": "Anshika@2702!",
            "full_name": "Anshika Pathania",
            "email": "anshikapathania@nic.in",
            "role": "citizen",
            "state": "Madhya Pradesh",
            "district": "Agar-Malwa",
            "constituency": "DEWAS(SC)",
            "agency_id": None,
            "agency_name": None,
            "designation": "Citizen Observer",
            "is_active": 1
        }
    ]

    print("[DB] Ensuring stakeholder credentials with Argon2id hashes...")
    for acc in demo_accounts:
        cursor.execute("SELECT id FROM users WHERE username = ?", (acc["username"],))
        existing = cursor.fetchone()
        hashed_pw = hasher.hash(acc["password"])
        
        if existing:
            cursor.execute("""
                UPDATE users SET
                    password_hash = ?,
                    full_name = ?,
                    email = ?,
                    role = ?,
                    state = ?,
                    district = ?,
                    constituency = ?,
                    agency_id = ?,
                    agency_name = ?,
                    designation = ?,
                    is_active = ?
                WHERE username = ?
            """, (
                hashed_pw,
                acc["full_name"],
                acc["email"],
                acc["role"],
                acc["state"],
                acc["district"],
                acc["constituency"],
                acc["agency_id"],
                acc["agency_name"],
                acc["designation"],
                acc["is_active"],
                acc["username"]
            ))
        else:
            cursor.execute("""
                INSERT INTO users (
                    username, password_hash, full_name, email, role,
                    state, district, constituency, agency_id, agency_name, designation, is_active
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                acc["username"],
                hashed_pw,
                acc["full_name"],
                acc["email"],
                acc["role"],
                acc["state"],
                acc["district"],
                acc["constituency"],
                acc["agency_id"],
                acc["agency_name"],
                acc["designation"],
                acc["is_active"]
            ))

    conn.commit()
    conn.close()
    print("[DB] Live database schema, migrations & secure users successfully initialized!")


if __name__ == "__main__":
    init_live_db()
