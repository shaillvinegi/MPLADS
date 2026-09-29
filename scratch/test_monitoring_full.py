import os
import sys
import sqlite3
import pandas as pd
from fastapi.testclient import TestClient

# Ensure root directory is on sys.path
sys.path.insert(0, os.path.abspath(os.path.dirname(os.path.dirname(__file__))))

from backend.main import app
from backend.database import HISTORICAL_DB_PATH, get_historical_db
from backend.monitoring_ml import run_monitoring_pipeline

def run_tests():
    print("==================================================")
    print("RUNNING AUTOMATED TEST SUITE: PROJECT MONITORING & ML ANOMALY DETECTION")
    print("==================================================")

    # 1. DB Integrity Check
    conn = sqlite3.connect(HISTORICAL_DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT COUNT(*) FROM project_monitoring_features")
    total_count = cur.fetchone()[0]
    print(f"1. Table 'project_monitoring_features' count: {total_count}")
    assert total_count == 41086, f"Expected 41086 rows, got {total_count}"

    # 2. Check Feature Non-Null & Range Constraints
    cur.execute("""
        SELECT 
            COUNT(CASE WHEN raw_anomaly_score IS NULL THEN 1 END),
            COUNT(CASE WHEN anomaly_risk_score IS NULL THEN 1 END),
            COUNT(CASE WHEN anomaly_prediction NOT IN (1, -1) THEN 1 END),
            COUNT(CASE WHEN anomaly_risk_score < 0 OR anomaly_risk_score > 100 THEN 1 END)
        FROM project_monitoring_features
    """)
    null_raw, null_risk, invalid_pred, out_of_bounds_risk = cur.fetchone()
    print(f"2. ML Feature Integrity: Null raw={null_raw}, Null risk={null_risk}, Invalid pred={invalid_pred}, Risk out of bounds={out_of_bounds_risk}")
    assert null_raw == 0 and null_risk == 0 and invalid_pred == 0 and out_of_bounds_risk == 0, "ML Feature constraint check failed!"

    # 3. Delay Classification Statistics
    cur.execute("""
        SELECT delay_status, COUNT(*) 
        FROM project_monitoring_features 
        GROUP BY delay_status
    """)
    delay_stats = dict(cur.fetchall())
    print(f"3. Delay Status Breakdown: {delay_stats}")
    assert "ON_TIME" in delay_stats and "DELAYED" in delay_stats, "Missing delay status categories!"

    # 4. Budget Status Breakdown
    cur.execute("""
        SELECT budget_monitoring_status, COUNT(*) 
        FROM project_monitoring_features 
        GROUP BY budget_monitoring_status
    """)
    budget_stats = dict(cur.fetchall())
    print(f"4. Budget Status Breakdown: {budget_stats}")

    # 5. Payment Events Join Verification
    cur.execute("""
        SELECT COUNT(*) 
        FROM project_monitoring_features 
        WHERE payment_tranche_count > 0 AND total_disbursed > 0
    """)
    paid_works_count = cur.fetchone()[0]
    print(f"5. Projects Joined with Payment Events (>0 payments): {paid_works_count}")
    assert paid_works_count > 0, "No projects joined with payments!"

    conn.close()

    # 6. Test FastAPI Client Endpoints
    client = TestClient(app)

    # API Summary
    res = client.get("/api/monitoring/summary")
    assert res.status_code == 200, f"GET /api/monitoring/summary status {res.status_code}"
    sum_data = res.json()
    print("6. GET /api/monitoring/summary OK")
    print(f"   Analyzed Projects: {sum_data['ml_anomaly_detection']['projects_analyzed']}")
    print(f"   Potential Anomalies: {sum_data['ml_anomaly_detection']['potential_anomalies']} ({sum_data['ml_anomaly_detection']['anomaly_pct']}%)")

    # API Works Filtering: All States
    res = client.get("/api/monitoring/works?page=1&limit=5")
    assert res.status_code == 200
    works_all = res.json()
    print(f"   GET /api/monitoring/works (All States) total: {works_all['total']}")

    # API Works Filtering: Madhya Pradesh
    res = client.get("/api/monitoring/works?state=Madhya%20Pradesh&page=1&limit=5")
    assert res.status_code == 200
    works_mp = res.json()
    print(f"   GET /api/monitoring/works (State=Madhya Pradesh) total: {works_mp['total']}")

    # API Works Filtering: Madhya Pradesh + Agar-Malwa
    res = client.get("/api/monitoring/works?state=Madhya%20Pradesh&district=Agar-Malwa&page=1&limit=5")
    assert res.status_code == 200
    works_agar = res.json()
    print(f"   GET /api/monitoring/works (State=MP, District=Agar-Malwa) total: {works_agar['total']}")

    # API Single Work Inspection Profile
    sample_wid = works_all['items'][0]['work_id']
    res = client.get(f"/api/monitoring/work/{sample_wid}")
    assert res.status_code == 200
    work_detail = res.json()
    print(f"7. GET /api/monitoring/work/{sample_wid} OK")
    print(f"   Risk Score: {work_detail['ml_monitoring']['anomaly_risk_score']}/100")
    print(f"   Disclaimer Present: {'screening signal' in work_detail['ml_monitoring']['disclaimer']}")

    # API Alerts
    res = client.get("/api/monitoring/alerts?limit=10")
    assert res.status_code == 200
    alerts_data = res.json()
    print(f"8. GET /api/monitoring/alerts OK (Total alerts: {alerts_data['total_alerts']})")

    # API Analytics Monitoring
    res = client.get("/api/analytics/monitoring")
    assert res.status_code == 200
    analytics_data = res.json()
    print(f"9. GET /api/analytics/monitoring OK (States count: {len(analytics_data['state_metrics'])})")

    print("\nALL AUTOMATED TESTS PASSED CLEANLY!\n")

if __name__ == "__main__":
    run_tests()
