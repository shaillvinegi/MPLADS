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
        role TEXT NOT NULL, -- 'mp', 'district_authority', 'implementing_agency', 'citizen'
        state TEXT,
        district TEXT,
        constituency TEXT,
        agency_name TEXT,
        designation TEXT,
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

    CREATE INDEX IF NOT EXISTS idx_lw_work_id ON live_works(work_id);
    CREATE INDEX IF NOT EXISTS idx_lw_status ON live_works(status);
    CREATE INDEX IF NOT EXISTS idx_lw_mp ON live_works(recommending_mp_name);
    CREATE INDEX IF NOT EXISTS idx_lw_agency ON live_works(assigned_agency_id);
    CREATE INDEX IF NOT EXISTS idx_pu_work ON live_progress_updates(work_id);
    CREATE INDEX IF NOT EXISTS idx_notif_role ON notifications(target_role, is_read);
    CREATE INDEX IF NOT EXISTS idx_audit_work ON audit_logs(work_id);
    """)

    # Seed initial test/demo stakeholder users if empty
    cursor.execute("SELECT COUNT(*) FROM users;")
    if cursor.fetchone()[0] == 0:
        print("[DB] Seeding default stakeholder credentials...")
        demo_users = [
            ('citizen_demo', 'password123', 'Citizen / Public — Demo User', 'citizen.demo@nic.in', 'citizen', None, None, None, None, 'Public Citizen (Demo)'),
            ('mp_demo', 'password123', 'MP Portal — Demo User', 'mp.demo@sansad.nic.in', 'mp', None, None, None, None, 'Member of Parliament (Demo)'),
            ('da_demo', 'password123', 'District Authority — Demo User', 'da.demo@nic.in', 'district_authority', None, None, None, None, 'District Authority (Demo)'),
            ('ia_demo', 'password123', 'Implementing Agency — Demo User', 'agency.demo@nic.in', 'implementing_agency', None, None, None, 'Infrastructure Execution Agency (Demo)', 'Executive Engineer (Demo)'),
        ]
        cursor.executemany("""
            INSERT INTO users (username, password_hash, full_name, email, role, state, district, constituency, agency_name, designation)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, demo_users)

    conn.commit()
    conn.close()
    print("[DB] Live database schema & users successfully initialized!")


if __name__ == "__main__":
    init_live_db()
