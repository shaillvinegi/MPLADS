import requests
import sys

BASE_URL = "http://127.0.0.1:8000"

def test_public_explorer():
    print("==================================================")
    print("RUNNING PUBLIC WORKS EXPLORER VALIDATION TESTS")
    print("==================================================")
    
    # 1. Mandatory Agar-Malwa Validation Test
    url_agar = f"{BASE_URL}/api/works?state=Madhya%20Pradesh&district=Agar-Malwa&limit=50"
    res = requests.get(url_agar)
    assert res.status_code == 200, f"Expected 200, got {res.status_code}"
    data_agar = res.json()
    
    print("\n--- TEST 1: Madhya Pradesh + Agar-Malwa Filter ---")
    print(f"Total Works Returned: {data_agar['total']}")
    print(f"Summary: {data_agar.get('summary')}")
    
    assert data_agar['total'] == 9, f"Expected 9 works for Agar-Malwa, got {data_agar['total']}"
    summary = data_agar['summary']
    assert summary['total_works'] == 9, f"Expected summary.total_works == 9, got {summary['total_works']}"
    assert abs(summary['total_sanction_amount'] - 7600000.0) < 1.0, f"Expected 76,00,000 sanctioned, got {summary['total_sanction_amount']}"
    assert abs(summary['total_disbursed_amount'] - 4850294.0) < 1.0, f"Expected 48,50,294 disbursed, got {summary['total_disbursed_amount']}"
    
    item = data_agar['items'][0]
    print(f"Sample Work ID: {item['work_id']}")
    print(f"MP Name: {item['mp_name']}")
    print(f"Constituency: {item['constituency']}")
    assert "MAHENDRA SINGH SOLANKY" in item['mp_name'].upper(), f"Expected Mahendra Singh Solanky, got {item['mp_name']}"
    assert "DEWAS" in item['constituency'].upper(), f"Expected DEWAS constituency, got {item['constituency']}"
    print("[PASS] Test 1 PASSED: Agar-Malwa filter matches exact expected dataset values.")

    # 2. All States Test
    print("\n--- TEST 2: All States Query ---")
    url_all = f"{BASE_URL}/api/works?page=1&limit=20"
    res_all = requests.get(url_all)
    assert res_all.status_code == 200
    data_all = res_all.json()
    print(f"Total All States Works: {data_all['total']}")
    assert data_all['total'] >= 41086, f"Expected >= 41086, got {data_all['total']}"
    print("[PASS] Test 2 PASSED: All States query returned all dataset works.")

    # 3. Madhya Pradesh Test
    print("\n--- TEST 3: State = Madhya Pradesh ---")
    url_mp = f"{BASE_URL}/api/works?state=Madhya%20Pradesh&limit=20"
    res_mp = requests.get(url_mp)
    assert res_mp.status_code == 200
    data_mp = res_mp.json()
    print(f"Total MP Works: {data_mp['total']}")
    assert data_mp['total'] == 5660, f"Expected 5660, got {data_mp['total']}"
    print("[PASS] Test 3 PASSED: Madhya Pradesh query returned 5,660 works.")

    # 4. Indore District Test
    print("\n--- TEST 4: District = Indore ---")
    url_indore = f"{BASE_URL}/api/works?state=Madhya%20Pradesh&district=Indore&limit=20"
    res_indore = requests.get(url_indore)
    assert res_indore.status_code == 200
    data_indore = res_indore.json()
    print(f"Total Indore Works: {data_indore['total']}")
    assert data_indore['total'] == 280, f"Expected 280, got {data_indore['total']}"
    print("[PASS] Test 4 PASSED: Indore query returned 280 works.")

    # 5. Search Keyword Test
    print("\n--- TEST 5: Search Query (q='Solanky') ---")
    url_q = f"{BASE_URL}/api/works?q=Solanky&limit=20"
    res_q = requests.get(url_q)
    assert res_q.status_code == 200
    data_q = res_q.json()
    print(f"Total works matching 'Solanky': {data_q['total']}")
    assert data_q['total'] > 0, "Expected matching works for 'Solanky'"
    print("[PASS] Test 5 PASSED: Search query matched MP Name.")

    # 6. Non-Existent Filter Empty State Test
    print("\n--- TEST 6: Non-Existent Filter ---")
    url_empty = f"{BASE_URL}/api/works?state=NonExistentStateName&limit=20"
    res_empty = requests.get(url_empty)
    assert res_empty.status_code == 200
    data_empty = res_empty.json()
    print(f"Total works returned for NonExistentStateName: {data_empty['total']}")
    assert data_empty['total'] == 0, f"Expected 0 works, got {data_empty['total']}"
    assert data_empty['summary']['total_works'] == 0
    print("[PASS] Test 6 PASSED: Non-existent filter cleanly returned 0 works.")

    print("\n==================================================")
    print("ALL PUBLIC EXPLORER VALIDATION TESTS PASSED SUCCESSFULLY!")
    print("==================================================")

if __name__ == "__main__":
    test_public_explorer()
