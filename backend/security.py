"""
Security, Authentication, and Role-Based Authorization Module for Nirakshan-AI.
Enforces:
- Argon2id password hashing and verification
- Secure session token generation & verification (stored in SQLite)
- Fast, secure cookie and Bearer token parsing
- Centralized role-based access control (RBAC) dependencies
- Data-level jurisdiction and tenant scope enforcement
- In-memory rate limiting against brute-force login attempts
- Security audit logging for auth and privilege events
"""

import os
import secrets
import sqlite3
import time
from datetime import datetime, timedelta
from typing import Optional, List, Dict, Any
from argon2 import PasswordHasher
from argon2.exceptions import VerifyMismatchError, VerificationError, InvalidHash
from fastapi import Request, HTTPException, Depends, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from backend.database import get_live_db

# Initialize Argon2id password hasher with secure parameters
hasher = PasswordHasher(
    time_cost=2,
    memory_cost=65536,  # 64 MB
    parallelism=1,
    hash_len=32,
    salt_len=16
)

# Configuration from Environment Variables with secure defaults
SESSION_COOKIE_NAME = "mplads_session"
SESSION_EXPIRY_HOURS = int(os.environ.get("SESSION_EXPIRY_HOURS", "24"))
RATE_LIMIT_MAX_ATTEMPTS = int(os.environ.get("RATE_LIMIT_MAX_ATTEMPTS", "5"))
RATE_LIMIT_LOCKOUT_MINUTES = int(os.environ.get("RATE_LIMIT_LOCKOUT_MINUTES", "15"))
SECURE_COOKIES = os.environ.get("SECURE_COOKIES", "false").lower() == "true"

# In-memory brute force rate-limiter: ip_or_username -> [attempt_timestamps]
_login_failed_attempts: Dict[str, List[float]] = {}
_account_lockouts: Dict[str, float] = {}

http_bearer = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    """Hashes a password using Argon2id."""
    return hasher.hash(password)


def verify_password(stored_hash: str, password: str) -> bool:
    """Verifies a plaintext password against an Argon2id hash."""
    if not stored_hash or not password:
        return False
    try:
        return hasher.verify(stored_hash, password)
    except (VerifyMismatchError, VerificationError, InvalidHash):
        return False


def check_rate_limit(key: str) -> None:
    """Checks if a user/IP is rate limited due to repeated failed login attempts."""
    now = time.time()
    
    # Check if locked out
    if key in _account_lockouts:
        lock_until = _account_lockouts[key]
        if now < lock_until:
            remaining_mins = int((lock_until - now) / 60) + 1
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Too many failed login attempts. Account temporarily locked. Try again in {remaining_mins} minutes."
            )
        else:
            del _account_lockouts[key]
            _login_failed_attempts[key] = []

    # Clean old attempts (> 15 minutes)
    window = RATE_LIMIT_LOCKOUT_MINUTES * 60
    attempts = _login_failed_attempts.get(key, [])
    attempts = [t for t in attempts if now - t < window]
    _login_failed_attempts[key] = attempts

    if len(attempts) >= RATE_LIMIT_MAX_ATTEMPTS:
        _account_lockouts[key] = now + window
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail=f"Too many failed login attempts. Account temporarily locked for {RATE_LIMIT_LOCKOUT_MINUTES} minutes."
        )


def record_failed_login(key: str) -> None:
    """Records a failed login attempt for rate limiting."""
    now = time.time()
    if key not in _login_failed_attempts:
        _login_failed_attempts[key] = []
    _login_failed_attempts[key].append(now)


def record_successful_login(key: str) -> None:
    """Clears failed login attempts after a successful login."""
    if key in _login_failed_attempts:
        del _login_failed_attempts[key]
    if key in _account_lockouts:
        del _account_lockouts[key]


# --- Session Management in SQLite ---

def create_user_session(
    db: sqlite3.Connection,
    user_id: int,
    ip_address: Optional[str] = None,
    user_agent: Optional[str] = None
) -> Dict[str, Any]:
    """Creates a new session in the database and returns token & expiry."""
    token = secrets.token_urlsafe(32)
    csrf_token = secrets.token_hex(16)
    expires_at = datetime.utcnow() + timedelta(hours=SESSION_EXPIRY_HOURS)
    expires_str = expires_at.strftime("%Y-%m-%d %H:%M:%S")

    cursor = db.cursor()
    cursor.execute("""
        INSERT INTO sessions (session_token, user_id, csrf_token, ip_address, user_agent, expires_at)
        VALUES (?, ?, ?, ?, ?, ?)
    """, (token, user_id, csrf_token, ip_address or "unknown", user_agent or "unknown", expires_str))
    db.commit()

    return {
        "session_token": token,
        "csrf_token": csrf_token,
        "expires_at": expires_str,
        "expires_in_seconds": SESSION_EXPIRY_HOURS * 3600
    }


def invalidate_user_session(db: sqlite3.Connection, token: str) -> None:
    """Revokes a session token immediately."""
    cursor = db.cursor()
    cursor.execute("DELETE FROM sessions WHERE session_token = ?", (token,))
    db.commit()


def get_session_user(db: sqlite3.Connection, token: str) -> Optional[Dict[str, Any]]:
    """Retrieves authenticated user details from a valid active session token."""
    if not token:
        return None

    now_str = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    cursor = db.cursor()

    cursor.execute("""
        SELECT s.session_token, s.csrf_token, s.expires_at,
               u.id, u.username, u.full_name, u.email, u.role,
               u.state, u.district, u.constituency, u.agency_id, u.agency_name,
               u.designation, u.is_active
        FROM sessions s
        JOIN users u ON s.user_id = u.id
        WHERE s.session_token = ? AND s.expires_at > ?
    """, (token, now_str))

    row = cursor.fetchone()
    if not row:
        return None

    user = dict(row)
    if not user.get("is_active", 1):
        # Account is deactivated
        return None

    # Update last activity
    cursor.execute("UPDATE sessions SET last_activity_at = CURRENT_TIMESTAMP WHERE session_token = ?", (token,))
    db.commit()

    return user


# --- Security Audit Logging ---

def log_security_event(
    db: sqlite3.Connection,
    action: str,
    status_code: str,
    actor_id: Optional[int] = None,
    actor_username: Optional[str] = None,
    actor_role: Optional[str] = None,
    resource_type: Optional[str] = None,
    resource_id: Optional[str] = None,
    ip_address: Optional[str] = None,
    details: Optional[str] = None
) -> None:
    """Logs a security-critical event into security_audit_logs table."""
    try:
        cursor = db.cursor()
        cursor.execute("""
            INSERT INTO security_audit_logs (
                actor_id, actor_username, actor_role, action,
                resource_type, resource_id, status, ip_address, details
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, (
            actor_id,
            actor_username or "anonymous",
            actor_role or "guest",
            action,
            resource_type,
            resource_id,
            status_code,
            ip_address or "unknown",
            details
        ))
        db.commit()
    except Exception as e:
        # Never crash the main request because of audit log failure
        print(f"[SECURITY AUDIT LOG ERROR] Failed to record audit log: {e}")


# --- FastAPI Dependency Injectors for Authentication & RBAC ---

def extract_token_from_request(request: Request) -> Optional[str]:
    """Extracts session token from HTTP-only cookie or Authorization Bearer header."""
    # 1. Check HTTP-only cookie
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if token:
        return token

    # 2. Check Authorization Header (Bearer <token>)
    auth_header = request.headers.get("Authorization")
    if auth_header and auth_header.startswith("Bearer "):
        return auth_header[7:].strip()

    return None


def get_current_user_optional(
    request: Request,
    db: sqlite3.Connection = Depends(get_live_db)
) -> Optional[Dict[str, Any]]:
    """Dependency that returns the current authenticated user or None if anonymous/public."""
    token = extract_token_from_request(request)
    if not token:
        return None
    return get_session_user(db, token)


def get_current_user(
    request: Request,
    user: Optional[Dict[str, Any]] = Depends(get_current_user_optional)
) -> Dict[str, Any]:
    """Dependency that strictly requires authentication (returns 401 if not authenticated)."""
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication required. Please log in to access this resource.",
            headers={"WWW-Authenticate": "Bearer"}
        )
    if not user.get("is_active", 1):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Your account has been deactivated. Please contact the administrator."
        )
    return user


def require_role(*allowed_roles: str):
    """
    Dependency factory that enforces Role-Based Access Control (RBAC).
    Admins are granted access to all administrative and operational views.
    """
    normalized_allowed = [r.lower() for r in allowed_roles]
    if "admin" not in normalized_allowed:
        normalized_allowed.append("admin")

    def role_checker(
        request: Request,
        current_user: Dict[str, Any] = Depends(get_current_user),
        db: sqlite3.Connection = Depends(get_live_db)
    ) -> Dict[str, Any]:
        user_role = (current_user.get("role") or "").lower()
        if user_role not in normalized_allowed:
            # Log unauthorized access attempt
            client_ip = request.client.host if request.client else "unknown"
            log_security_event(
                db=db,
                action="UNAUTHORIZED_ROLE_ACCESS",
                status_code="DENIED",
                actor_id=current_user.get("id"),
                actor_username=current_user.get("username"),
                actor_role=current_user.get("role"),
                resource_type="API_ROUTE",
                resource_id=request.url.path,
                ip_address=client_ip,
                details=f"Required roles: {allowed_roles}, but user had role: {user_role}"
            )
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access denied: This action requires one of the following roles: {', '.join(allowed_roles)}."
            )
        return current_user

    return role_checker


# --- Data-Level Scope Enforcement Helpers ---

def enforce_mp_scope(current_user: Dict[str, Any], requested_mp_name: Optional[str] = None) -> None:
    """Ensures an MP user cannot act as or inspect another MP's private workflow."""
    if (current_user.get("role") or "").lower() == "admin":
        return
    
    mp_user_name = current_user.get("full_name") or current_user.get("username")
    if requested_mp_name and requested_mp_name.strip():
        if requested_mp_name.strip().lower() != mp_user_name.strip().lower():
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="Access denied: You are only authorized to manage your own constituency works."
            )


def enforce_da_scope(current_user: Dict[str, Any], state: str, district: str) -> None:
    """Ensures a District Authority user can only review/approve works in their assigned district."""
    if (current_user.get("role") or "").lower() == "admin":
        return

    da_district = (current_user.get("district") or "").strip().lower()
    da_state = (current_user.get("state") or "").strip().lower()
    target_district = (district or "").strip().lower()
    target_state = (state or "").strip().lower()

    if da_district and target_district and da_district != target_district:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Access denied: You are assigned to district '{current_user.get('district')}' and cannot act on district '{district}'."
        )
    if da_state and target_state and da_state != target_state:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail=f"Access denied: You are assigned to state '{current_user.get('state')}' and cannot act on state '{state}'."
        )


def enforce_ia_scope(current_user: Dict[str, Any], assigned_agency_id: Optional[int], assigned_agency_name: Optional[str]) -> None:
    """Ensures an Implementing Agency can only update works assigned to them."""
    if (current_user.get("role") or "").lower() == "admin":
        return

    user_agency_name = (current_user.get("agency_name") or "").strip().lower()
    user_agency_id = current_user.get("agency_id")
    user_id = current_user.get("id")

    # Match on agency ID or user ID or agency name
    id_match = (
        (assigned_agency_id is not None and user_agency_id is not None and assigned_agency_id == user_agency_id) or
        (assigned_agency_id is not None and user_id is not None and assigned_agency_id == user_id)
    )
    name_match = (assigned_agency_name and user_agency_name and assigned_agency_name.strip().lower() == user_agency_name)

    if not (id_match or name_match):
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Access denied: This project is not assigned to your implementing agency."
        )
