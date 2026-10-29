"""
Supervised Machine Learning Module: AI-Powered Project Delay Prediction & Early Warning.

Uses scikit-learn RandomForestClassifier trained on historical MPLADS projects with
verified completion outcomes to estimate the likelihood that a project will miss its
statutory expected completion deadline.

Data Eligibility & Leakage Prevention:
- 19,304 completed projects with verified dates are eligible for target definition.
- 21,782 ongoing/unlisted projects are excluded from training to prevent label fabrication.
- Target: was_delayed = 1 if completion_date > expected_completion_date_proxy else 0.
- Zero Data Leakage: Only sanction-time metadata and early payment activity (up to 90 days)
  are used as features. Actual completion date, status, and future payments are strictly excluded.
"""

import os
import json
import sqlite3
import joblib
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, Tuple, Optional, List

import numpy as np
import pandas as pd
from sklearn.ensemble import RandomForestClassifier
from sklearn.compose import ColumnTransformer
from sklearn.preprocessing import OneHotEncoder
from sklearn.pipeline import Pipeline
from sklearn.model_selection import train_test_split
from sklearn.metrics import (
    precision_score, recall_score, f1_score, accuracy_score,
    roc_auc_score, confusion_matrix, classification_report
)

# Paths
MODULE_DIR = Path(__file__).resolve().parent
ROOT_DIR = MODULE_DIR.parent
DATA_DIR = ROOT_DIR / "data"
MODELS_DIR = MODULE_DIR / "models"
MODEL_FILE = MODELS_DIR / "delay_prediction_rf.joblib"
MANIFEST_FILE = MODELS_DIR / "delay_prediction_manifest.json"

FEATURES_NUM = [
    "sanction_amount",
    "sanction_lead_time_days",
    "early_disbursed_amount",
    "early_payment_count",
    "early_disbursement_ratio",
    "work_description_length",
    "sanction_month"
]
FEATURES_CAT = [
    "state",
    "work_category"
]
ALL_FEATURES = FEATURES_NUM + FEATURES_CAT


def get_data_eligibility_report(conn: sqlite3.Connection) -> Dict[str, Any]:
    """Inspects historical projects and returns a detailed data eligibility audit."""
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM historical_projects")
    total_projects = cur.fetchone()[0]

    cur.execute("""
        SELECT work_completion_status, COUNT(*),
               COUNT(completion_date),
               COUNT(sanction_date),
               COUNT(expected_completion_date_proxy)
        FROM historical_projects
        GROUP BY work_completion_status
    """)
    rows = cur.fetchall()

    status_breakdown = {}
    completed_eligible = 0
    excluded_ongoing = 0

    for r in rows:
        st, total_st, comp_cnt, sanc_cnt, exp_cnt = r
        status_breakdown[st] = {
            "total_records": total_st,
            "has_completion_date": comp_cnt,
            "has_sanction_date": sanc_cnt,
            "has_expected_deadline": exp_cnt
        }
        if st == "COMPLETED" and comp_cnt > 0 and sanc_cnt > 0 and exp_cnt > 0:
            completed_eligible += total_st
        else:
            excluded_ongoing += total_st

    return {
        "total_source_projects": total_projects,
        "eligible_training_records": completed_eligible,
        "excluded_records": excluded_ongoing,
        "exclusion_reason": (
            "Projects marked NOT_LISTED_COMPLETED / ongoing lack verified completion dates. "
            "To prevent label fabrication and scientific bias, only historical projects with "
            "verified completion dates are used to define the supervised training target."
        ),
        "status_breakdown": status_breakdown
    }


def prepare_feature_dataset(conn: sqlite3.Connection, include_ongoing: bool = False) -> pd.DataFrame:
    """
    Extracts project records and early payment event features (up to 90 days post-sanction).
    Strictly prevents data leakage by ignoring all events after the 90-day milestone.
    """
    if include_ongoing:
        projects_query = "SELECT * FROM historical_projects"
    else:
        projects_query = "SELECT * FROM historical_projects WHERE work_completion_status = 'COMPLETED'"

    projects = pd.read_sql_query(projects_query, conn)
    payments = pd.read_sql_query("SELECT * FROM historical_payment_events", conn)

    projects["sanc_dt"] = pd.to_datetime(projects["sanction_date"], errors="coerce")
    projects["rec_dt"] = pd.to_datetime(projects["recommended_date"], errors="coerce")
    projects["exp_dt"] = pd.to_datetime(projects["expected_completion_date_proxy"], errors="coerce")

    if not include_ongoing:
        projects["comp_dt"] = pd.to_datetime(projects["completion_date"], errors="coerce")
        # Target: 1 = delayed past deadline, 0 = on-time
        projects["was_delayed"] = (projects["comp_dt"] > projects["exp_dt"]).astype(int)

    # Feature 1: Sanction approval lead time (days)
    projects["sanction_lead_time_days"] = (projects["sanc_dt"] - projects["rec_dt"]).dt.days.fillna(60).clip(lower=0)

    # Feature 2: Work description text length
    projects["work_description_length"] = projects["work_description"].fillna("").astype(str).str.len()

    # Feature 3: Sanction seasonality
    projects["sanction_month"] = projects["sanc_dt"].dt.month.fillna(6).astype(int)

    # Early payments within 90 days of sanction (Zero Leakage Milestone)
    if not payments.empty:
        payments["exp_dt_pay"] = pd.to_datetime(payments["expenditure_date"], errors="coerce")
        merged_pay = pd.merge(
            payments,
            projects[["work_id", "sanc_dt"]],
            on="work_id",
            how="inner"
        )
        early_pay = merged_pay[
            (merged_pay["exp_dt_pay"] >= merged_pay["sanc_dt"]) &
            (merged_pay["exp_dt_pay"] <= (merged_pay["sanc_dt"] + pd.Timedelta(days=90)))
        ]

        agg_pay = early_pay.groupby("work_id").agg(
            early_disbursed_amount=("reported_fund_disbursed_amount", "sum"),
            early_payment_count=("reported_fund_disbursed_amount", "count")
        ).reset_index()

        df = pd.merge(projects, agg_pay, on="work_id", how="left")
    else:
        df = projects.copy()
        df["early_disbursed_amount"] = 0.0
        df["early_payment_count"] = 0

    df["early_disbursed_amount"] = df["early_disbursed_amount"].fillna(0.0)
    df["early_payment_count"] = df["early_payment_count"].fillna(0).astype(int)
    df["sanction_amount"] = pd.to_numeric(df["sanction_amount"], errors="coerce").fillna(0.0)

    # Feature 4: Early disbursement ratio
    df["early_disbursement_ratio"] = np.where(
        df["sanction_amount"] > 0,
        df["early_disbursed_amount"] / df["sanction_amount"],
        0.0
    ).clip(0.0, 2.0)

    # Clean categorical features
    df["state"] = df["state"].fillna("Unknown").astype(str)
    df["work_category"] = df["work_category"].fillna("Normal/Others").astype(str)

    return df


def train_delay_model(conn: sqlite3.Connection) -> Dict[str, Any]:
    """
    Trains the supervised Random Forest classifier, evaluates on holdout set,
    saves model artifacts, and populates project_delay_predictions table.
    """
    MODELS_DIR.mkdir(parents=True, exist_ok=True)
    eligibility = get_data_eligibility_report(conn)

    df_eligible = prepare_feature_dataset(conn, include_ongoing=False)
    if len(df_eligible) < 500:
        raise ValueError(f"Insufficient completed records for training: {len(df_eligible)}")

    X = df_eligible[ALL_FEATURES]
    y = df_eligible["was_delayed"]

    # 80:20 Stratified Split
    X_train, X_test, y_train, y_test = train_test_split(
        X, y, test_size=0.20, random_state=42, stratify=y
    )

    preprocessor = ColumnTransformer(
        transformers=[
            ("num", "passthrough", FEATURES_NUM),
            ("cat", OneHotEncoder(handle_unknown="ignore", sparse_output=False), FEATURES_CAT)
        ]
    )

    rf_clf = RandomForestClassifier(
        n_estimators=150,
        max_depth=12,
        min_samples_split=10,
        min_samples_leaf=5,
        class_weight="balanced",
        random_state=42,
        n_jobs=-1
    )

    pipeline = Pipeline([
        ("preprocessor", preprocessor),
        ("classifier", rf_clf)
    ])

    training_start = datetime.now(timezone.utc)
    pipeline.fit(X_train, y_train)
    fit_duration_sec = (datetime.now(timezone.utc) - training_start).total_seconds()

    # Evaluation on holdout test set
    y_pred = pipeline.predict(X_test)
    y_prob = pipeline.predict_proba(X_test)[:, 1]

    cm = confusion_matrix(y_test, y_pred).tolist()
    prec = float(precision_score(y_test, y_pred, zero_division=0))
    rec = float(recall_score(y_test, y_pred, zero_division=0))
    f1 = float(f1_score(y_test, y_pred, zero_division=0))
    acc = float(accuracy_score(y_test, y_pred))
    roc_auc = float(roc_auc_score(y_test, y_prob))

    # Feature Importances
    classifier_step = pipeline.named_steps["classifier"]
    encoder_step = pipeline.named_steps["preprocessor"].named_transformers_["cat"]
    cat_feature_names = list(encoder_step.get_feature_names_out(FEATURES_CAT))
    all_feature_names = FEATURES_NUM + cat_feature_names

    raw_importances = classifier_step.feature_importances_
    feat_imp = [
        {"feature": name, "importance": round(float(imp), 4)}
        for name, imp in sorted(zip(all_feature_names, raw_importances), key=lambda x: x[1], reverse=True)
    ]

    manifest = {
        "model_name": "RandomForestClassifier",
        "feature_set": ALL_FEATURES,
        "numeric_features": FEATURES_NUM,
        "categorical_features": FEATURES_CAT,
        "prediction_point": "Project Sanction to Early-Stage Monitoring Milestone (Day 90 post-sanction)",
        "target_variable": "was_delayed (1=Completed after statutory deadline, 0=On-time)",
        "training_date_utc": training_start.isoformat(),
        "training_records": len(X_train),
        "test_records": len(X_test),
        "dataset_eligible_total": len(df_eligible),
        "dataset_excluded_ongoing": eligibility["excluded_records"],
        "class_balance_training": {
            "on_time_count": int(np.sum(y_train == 0)),
            "delayed_count": int(np.sum(y_train == 1)),
            "delayed_pct": round(float(np.mean(y_train == 1) * 100), 2)
        },
        "metrics": {
            "accuracy": round(acc, 4),
            "precision": round(prec, 4),
            "recall": round(rec, 4),
            "f1_score": round(f1, 4),
            "roc_auc": round(roc_auc, 4),
            "confusion_matrix": {
                "true_negatives": cm[0][0],
                "false_positives": cm[0][1],
                "false_negatives": cm[1][0],
                "true_positives": cm[1][1]
            }
        },
        "hyperparameters": {
            "n_estimators": 150,
            "max_depth": 12,
            "min_samples_split": 10,
            "min_samples_leaf": 5,
            "class_weight": "balanced",
            "random_state": 42
        },
        "top_feature_importances": feat_imp[:12],
        "data_eligibility": eligibility,
        "disclaimer": (
            "Predicted delay probability is a statistical estimate of project completion timeliness. "
            "It does NOT detect or imply fraud, corruption, contractor negligence, or misconduct."
        )
    }

    # Save model and manifest
    joblib.dump(pipeline, MODEL_FILE)
    with open(MANIFEST_FILE, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)

    # Score all projects in database and populate persistent table
    populate_delay_predictions(conn, pipeline)

    return manifest


def populate_delay_predictions(conn: sqlite3.Connection, pipeline: Pipeline):
    """Scores all 41,086 projects and persists results in project_delay_predictions table."""
    df_all = prepare_feature_dataset(conn, include_ongoing=True)
    X_all = df_all[ALL_FEATURES]

    probabilities = pipeline.predict_proba(X_all)[:, 1]
    now_ts = pd.Timestamp.now().normalize()
    exp_dates = pd.to_datetime(df_all["expected_completion_date_proxy"], errors="coerce")

    days_to_deadline = (exp_dates - now_ts).dt.days.fillna(365).astype(int)

    df_all["predicted_delay_prob"] = np.round(probabilities, 4)
    df_all["delay_risk_score"] = np.round(probabilities * 100.0, 1)

    # Risk tiers
    def assign_risk_level(prob):
        if prob >= 0.70:
            return "HIGH"
        elif prob >= 0.35:
            return "MEDIUM"
        else:
            return "LOW"

    df_all["risk_level"] = [assign_risk_level(p) for p in probabilities]
    df_all["days_to_deadline"] = days_to_deadline
    df_all["approaching_deadline"] = (
        (df_all["work_completion_status"] != "COMPLETED") &
        (days_to_deadline >= 0) &
        (days_to_deadline <= 90)
    ).astype(int)

    # Top contributing factor explanations for each project
    factor_explanations = []
    for idx, row in df_all.iterrows():
        reasons = []
        if row["sanction_amount"] >= 500000:
            reasons.append("High capital expenditure magnitude")
        if row["sanction_lead_time_days"] >= 90:
            reasons.append("Lengthy recommendation-to-sanction approval lead time")
        if row["early_disbursement_ratio"] < 0.10:
            reasons.append("Low early fund mobilization within first 90 days")
        if row["early_payment_count"] == 0:
            reasons.append("Zero early payment tranches released")
        if row["work_description_length"] >= 100:
            reasons.append("Complex project scope specification")
        if not reasons:
            reasons.append("Standard administrative feature profile")
        factor_explanations.append("; ".join(reasons))

    df_all["contributing_factors"] = factor_explanations

    # Write to SQLite
    cur = conn.cursor()
    cur.execute("DROP TABLE IF EXISTS project_delay_predictions")
    cur.execute("""
        CREATE TABLE project_delay_predictions (
            work_id TEXT PRIMARY KEY,
            work_title TEXT,
            state TEXT,
            district TEXT,
            constituency TEXT,
            mp_name TEXT,
            work_category TEXT,
            sanction_date TEXT,
            expected_completion_date TEXT,
            completion_date TEXT,
            execution_status TEXT,
            work_completion_status TEXT,
            sanction_amount REAL,
            early_disbursed_amount REAL,
            early_disbursement_ratio REAL,
            sanction_lead_time_days INTEGER,
            predicted_delay_prob REAL,
            delay_risk_score REAL,
            risk_level TEXT,
            days_to_deadline INTEGER,
            approaching_deadline INTEGER,
            contributing_factors TEXT,
            was_delayed INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    insert_rows = []
    for idx, r in df_all.iterrows():
        was_del = int(r["was_delayed"]) if "was_delayed" in r and pd.notna(r["was_delayed"]) else None
        insert_rows.append((
            r["work_id"],
            r.get("work_title", "N/A"),
            r.get("state", "N/A"),
            r.get("district", "N/A"),
            r.get("constituency", "N/A"),
            r.get("mp_name", "N/A"),
            r.get("work_category", "N/A"),
            r.get("sanction_date", ""),
            r.get("expected_completion_date_proxy", ""),
            r.get("completion_date", "") if pd.notna(r.get("completion_date")) else None,
            r.get("portal_execution_status", "SANCTION"),
            r.get("work_completion_status", "NOT_LISTED_COMPLETED"),
            float(r.get("sanction_amount", 0.0)),
            float(r.get("early_disbursed_amount", 0.0)),
            float(r.get("early_disbursement_ratio", 0.0)),
            int(r.get("sanction_lead_time_days", 0)),
            float(r.get("predicted_delay_prob", 0.0)),
            float(r.get("delay_risk_score", 0.0)),
            r.get("risk_level", "LOW"),
            int(r.get("days_to_deadline", 365)),
            int(r.get("approaching_deadline", 0)),
            r.get("contributing_factors", ""),
            was_del
        ))

    cur.executemany("""
        INSERT INTO project_delay_predictions (
            work_id, work_title, state, district, constituency, mp_name,
            work_category, sanction_date, expected_completion_date, completion_date,
            execution_status, work_completion_status, sanction_amount,
            early_disbursed_amount, early_disbursement_ratio, sanction_lead_time_days,
            predicted_delay_prob, delay_risk_score, risk_level, days_to_deadline,
            approaching_deadline, contributing_factors, was_delayed
        ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
    """, insert_rows)

    cur.execute("CREATE INDEX IF NOT EXISTS idx_pdp_risk ON project_delay_predictions(risk_level);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_pdp_state ON project_delay_predictions(state);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_pdp_prob ON project_delay_predictions(predicted_delay_prob DESC);")
    cur.execute("CREATE INDEX IF NOT EXISTS idx_pdp_deadline ON project_delay_predictions(approaching_deadline);")
    conn.commit()


def get_model_status(conn: sqlite3.Connection) -> Dict[str, Any]:
    """Returns current model readiness, evaluation metrics, or model-not-ready state."""
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='project_delay_predictions'")
    table_exists = bool(cur.fetchone())

    model_exists = MODEL_FILE.exists() and MANIFEST_FILE.exists()

    if not model_exists or not table_exists:
        eligibility = get_data_eligibility_report(conn)
        return {
            "status": "NOT_READY",
            "ready": False,
            "message": "Delay prediction model has not been trained yet. Click Train Model to initialize.",
            "data_eligibility": eligibility
        }

    with open(MANIFEST_FILE, "r", encoding="utf-8") as f:
        manifest = json.load(f)

    # Get live summary counts
    cur.execute("""
        SELECT
            COUNT(*) as total_scored,
            SUM(CASE WHEN risk_level = 'HIGH' THEN 1 ELSE 0 END) as high_risk,
            SUM(CASE WHEN risk_level = 'MEDIUM' THEN 1 ELSE 0 END) as medium_risk,
            SUM(CASE WHEN risk_level = 'LOW' THEN 1 ELSE 0 END) as low_risk,
            SUM(CASE WHEN approaching_deadline = 1 THEN 1 ELSE 0 END) as approaching_deadline
        FROM project_delay_predictions
    """)
    res = cur.fetchone()
    if isinstance(res, sqlite3.Row):
        row = dict(res)
    else:
        cols = [c[0] for c in cur.description]
        row = dict(zip(cols, res))

    return {
        "status": "OPERATIONAL",
        "ready": True,
        "manifest": manifest,
        "live_summary": row
    }


def init_delay_prediction_if_needed(conn: sqlite3.Connection):
    """Auto-trains and initializes model on startup if table or model artifacts are absent."""
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='project_delay_predictions'")
    table_exists = bool(cur.fetchone())

    if not table_exists or not MODEL_FILE.exists() or not MANIFEST_FILE.exists():
        print("[DelayPredictionML] Initializing Random Forest delay prediction pipeline...")
        train_delay_model(conn)
        print("[DelayPredictionML] Successfully initialized delay prediction pipeline.")
