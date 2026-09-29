import sqlite3
import pandas as pd
import numpy as np
from datetime import datetime
from sklearn.ensemble import IsolationForest

def run_monitoring_pipeline(conn: sqlite3.Connection, contamination: float = 0.05):
    """
    Executes real project-level feature engineering and Isolation Forest anomaly detection.
    Persists feature matrix into project_monitoring_features table in SQLite.
    """
    projects_df = pd.read_sql_query("SELECT * FROM historical_projects", conn)
    payments_df = pd.read_sql_query("SELECT * FROM historical_payment_events", conn)

    if projects_df.empty:
        return

    # Drop existing payment summary columns if present in projects_df to prevent merge collisions
    cols_to_drop = ['total_disbursed', 'payment_events_count', 'last_payment_date', 'first_payment_date', 'primary_vendor']
    for col in cols_to_drop:
        if col in projects_df.columns:
            projects_df.drop(columns=[col], inplace=True)

    # 1. Aggregate payments by work_id
    if not payments_df.empty:
        payments_df['exp_dt'] = pd.to_datetime(payments_df['expenditure_date'], errors='coerce')
        pay_agg = payments_df.groupby('work_id').agg(
            total_disbursed=('reported_fund_disbursed_amount', 'sum'),
            max_payment=('reported_fund_disbursed_amount', 'max'),
            mean_tranche_amount=('reported_fund_disbursed_amount', 'mean'),
            payment_tranche_count=('reported_fund_disbursed_amount', 'count'),
            vendor_unique_count=('vendor_name_normalized', 'nunique'),
            first_payment_date=('expenditure_date', 'min'),
            latest_payment_date=('expenditure_date', 'max'),
            first_dt=('exp_dt', 'min'),
            latest_dt=('exp_dt', 'max')
        ).reset_index()
        pay_agg['payment_span_days'] = (pay_agg['latest_dt'] - pay_agg['first_dt']).dt.days.fillna(0).astype(int)
        pay_agg.drop(columns=['first_dt', 'latest_dt'], inplace=True)
    else:
        pay_agg = pd.DataFrame(columns=['work_id', 'total_disbursed', 'max_payment', 'mean_tranche_amount', 'payment_tranche_count', 'vendor_unique_count', 'first_payment_date', 'latest_payment_date', 'payment_span_days'])

    # Merge projects with aggregated payments
    df = pd.merge(projects_df, pay_agg, on='work_id', how='left')

    # Fill missing payment values safely
    df['total_disbursed'] = df['total_disbursed'].fillna(0.0)
    df['max_payment'] = df['max_payment'].fillna(0.0)
    df['mean_tranche_amount'] = df['mean_tranche_amount'].fillna(0.0)
    df['payment_tranche_count'] = df['payment_tranche_count'].fillna(0).astype(int)
    df['vendor_unique_count'] = df['vendor_unique_count'].fillna(0).astype(int)
    df['first_payment_date'] = df['first_payment_date'].fillna('')
    df['latest_payment_date'] = df['latest_payment_date'].fillna('')
    df['payment_span_days'] = df['payment_span_days'].fillna(0).astype(int)

    # 2. Budget Features & Rules
    df['sanction_amount'] = df['sanction_amount'].fillna(0.0)
    df['budget_disbursement_ratio'] = np.where(df['sanction_amount'] > 0, df['total_disbursed'] / df['sanction_amount'], 0.0)
    df['budget_variance_amount'] = df['total_disbursed'] - df['sanction_amount']

    def get_budget_status(row):
        if row['total_disbursed'] > row['sanction_amount']:
            return 'POTENTIAL_BUDGET_OVERRUN'
        elif abs(row['total_disbursed'] - row['sanction_amount']) < 1.0 or row['total_disbursed'] == row['sanction_amount']:
            return 'FULLY_DISBURSED'
        else:
            return 'WITHIN_SANCTION'

    df['budget_monitoring_status'] = df.apply(get_budget_status, axis=1)

    # 3. Delay Features & Rules
    ref_now = pd.to_datetime('2026-09-29')
    df['rec_dt'] = pd.to_datetime(df['recommended_date'], errors='coerce')
    df['sanc_dt'] = pd.to_datetime(df['sanction_date'], errors='coerce')
    df['exp_comp_dt'] = pd.to_datetime(df['expected_completion_date_proxy'], errors='coerce')
    df['act_comp_dt'] = pd.to_datetime(df['completion_date'], errors='coerce')

    df['sanction_lead_time_days'] = (df['sanc_dt'] - df['rec_dt']).dt.days.fillna(0).astype(int)
    df['expected_duration_days'] = (df['exp_comp_dt'] - df['sanc_dt']).dt.days.fillna(365).astype(int)

    is_completed = df['work_completion_status'] == 'COMPLETED'
    df['actual_duration_days'] = np.where(is_completed & df['act_comp_dt'].notna(), (df['act_comp_dt'] - df['sanc_dt']).dt.days, None)

    df['schedule_delay_days'] = np.where(
        is_completed & df['act_comp_dt'].notna(),
        (df['act_comp_dt'] - df['exp_comp_dt']).dt.days,
        (ref_now - df['exp_comp_dt']).dt.days
    )
    df['schedule_delay_days'] = df['schedule_delay_days'].fillna(0).astype(int)

    def get_delay_status(row):
        completed = (row['work_completion_status'] == 'COMPLETED')
        delay = row['schedule_delay_days']
        if completed:
            return 'DELAYED' if delay > 0 else 'ON_TIME'
        else:
            return 'ONGOING_DELAYED' if delay > 0 else 'ONGOING_WITHIN_TARGET'

    df['delay_status'] = df.apply(get_delay_status, axis=1)

    # 4. Payment Ratios & Description Length
    df['max_single_tranche_ratio'] = np.where(df['sanction_amount'] > 0, df['max_payment'] / df['sanction_amount'], 0.0)
    df['work_description_length'] = df['work_description'].fillna('').str.len()

    # 5. ML Isolation Forest Training
    feature_cols = [
        'sanction_amount',
        'total_disbursed',
        'budget_disbursement_ratio',
        'sanction_lead_time_days',
        'payment_tranche_count',
        'max_single_tranche_ratio',
        'work_description_length'
    ]

    X = df[feature_cols].copy()
    X = X.fillna(0.0)
    X = np.nan_to_num(X, nan=0.0, posinf=0.0, neginf=0.0)

    iso = IsolationForest(n_estimators=100, contamination=contamination, random_state=42)
    iso.fit(X)

    raw_scores = iso.decision_function(X) # lower score = more anomalous
    preds = iso.predict(X) # -1 = anomaly, 1 = normal

    df['raw_anomaly_score'] = raw_scores
    df['anomaly_prediction'] = preds
    df['anomaly_status'] = np.where(preds == -1, 'POTENTIAL ANOMALY', 'NORMAL')

    min_s = raw_scores.min()
    max_s = raw_scores.max()
    if max_s > min_s:
        df['anomaly_risk_score'] = np.round((1.0 - (raw_scores - min_s) / (max_s - min_s)) * 100.0, 1)
    else:
        df['anomaly_risk_score'] = 0.0

    df_db = df[[
        'work_id', 'state', 'district', 'constituency', 'mp_name', 'work_category', 'work_title', 'work_description',
        'recommended_date', 'sanction_date', 'sanction_amount', 'expected_completion_date_proxy', 'completion_date',
        'work_completion_status', 'portal_execution_status', 'total_disbursed', 'budget_disbursement_ratio',
        'budget_variance_amount', 'budget_monitoring_status', 'sanction_lead_time_days', 'expected_duration_days',
        'actual_duration_days', 'schedule_delay_days', 'delay_status', 'payment_tranche_count', 'max_single_tranche_ratio',
        'mean_tranche_amount', 'vendor_unique_count', 'first_payment_date', 'latest_payment_date', 'payment_span_days',
        'work_description_length', 'raw_anomaly_score', 'anomaly_prediction', 'anomaly_status', 'anomaly_risk_score'
    ]].copy()

    df_db.to_sql('project_monitoring_features', conn, if_exists='replace', index=False)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_pmf_state_dist ON project_monitoring_features(state, district);")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_pmf_work_id ON project_monitoring_features(work_id);")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_pmf_anomaly ON project_monitoring_features(anomaly_status);")
    conn.commit()

def init_monitoring_if_needed(conn: sqlite3.Connection):
    cur = conn.cursor()
    cur.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='project_monitoring_features'")
    if not cur.fetchone():
        run_monitoring_pipeline(conn)
