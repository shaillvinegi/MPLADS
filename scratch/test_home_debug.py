import os
import sys
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.abspath(os.path.dirname(os.path.dirname(__file__))))
from backend.main import app

def test_home_calls():
    client = TestClient(app)

    endpoints = [
        "/api/metadata/geography",
        "/api/analytics/overview",
        "/api/metadata/districts?state=Madhya%20Pradesh",
        "/api/da/dashboard?state=Madhya%20Pradesh&district=Agar-Malwa"
    ]

    for ep in endpoints:
        res = client.get(ep)
        print(f"Testing {ep} -> Status: {res.status_code}")
        if res.status_code != 200:
            print(f"  ERROR BODY: {res.text}")
        else:
            json_data = res.json()
            if isinstance(json_data, dict):
                print(f"  KEYS: {list(json_data.keys())}")
            elif isinstance(json_data, list):
                print(f"  LIST LENGTH: {len(json_data)}")

if __name__ == "__main__":
    test_home_calls()
