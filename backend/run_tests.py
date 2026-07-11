"""
碳关税合规审计系统 — 自动化集成测试
======================================
要求在分析之前启动 FastAPI 服务器：
    cd backend
    uvicorn src.api.app:app --host 0.0.0.0 --port 8008 --reload

然后运行该测试：
    cd backend
    python run_tests.py
"""

import sys, json
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve()))

PASS = 0; FAIL = 0
BASE = "http://127.0.0.1:8008"
TOKEN = ""; THREAD_ID = ""

def check(condition, msg=""):
    if not condition:
        raise AssertionError(msg)

import requests

# ---- 1. Health ----
print("=" * 60)
print("1. Health Checks")
print("=" * 60)
try:
    r = requests.get(f"{BASE}/", timeout=5)
    check(r.status_code == 200); check(r.json()["status"] == "ok")
    print(f"  [PASS] GET / -> {r.json()}")
    PASS += 1
except Exception as e:
    print(f"  [FAIL] {e}"); FAIL += 1

try:
    r = requests.get(f"{BASE}/api/v1/health", timeout=5)
    check(r.status_code == 200)
    print(f"  [PASS] GET /api/v1/health")
    PASS += 1
except Exception as e:
    print(f"  [FAIL] {e}"); FAIL += 1

# ---- 2. Auth ----
print()
print("2. JWT Auth")
print("=" * 60)
try:
    r = requests.post(f"{BASE}/api/v1/auth/token",
        json={"username":"admin","password":"admin123"}, timeout=5)
    check(r.status_code == 200)
    data = r.json(); TOKEN = data["access_token"]
    check(data["token_type"] == "bearer")
    print(f"  [PASS] POST /auth/token -> expires={data['expires_in']}min")
    PASS += 1
except Exception as e:
    print(f"  [FAIL] {e}"); FAIL += 1

try:
    r = requests.post(f"{BASE}/api/v1/auth/token",
        json={"username":"admin","password":"wrong"}, timeout=5)
    check(r.status_code == 401)
    print(f"  [PASS] POST /auth/token (wrong pw) -> 401")
    PASS += 1
except Exception as e:
    print(f"  [FAIL] {e}"); FAIL += 1

# ---- 3. Protected endpoints ----
print()
print("3. Protected Endpoints")
print("=" * 60)
AUTH = {"Authorization": f"Bearer {TOKEN}"}

try:
    r = requests.post(f"{BASE}/api/v1/audit/start",
        json={"bom_data":{"test":1}}, timeout=5)
    check(r.status_code == 401)
    print(f"  [PASS] No token -> /audit/start -> 401")
    PASS += 1
except Exception as e:
    print(f"  [FAIL] {e}"); FAIL += 1

try:
    r = requests.post(f"{BASE}/api/v1/rag/search",
        json={"query":"CBAM carbon tariff policy","top_k":2}, timeout=60)
    check(r.status_code == 200)
    ctx_len = len(r.json().get("context",""))
    check(ctx_len > 0)
    print(f"  [PASS] POST /rag/search (public) -> context={ctx_len} chars")
    PASS += 1
except Exception as e:
    print(f"  [FAIL] {e}"); FAIL += 1

# ---- 4. Full audit workflow ----
print()
print("4. Full Audit Workflow (may take 60-120s)")
print("=" * 60)
try:
    r = requests.post(f"{BASE}/api/v1/audit/start",
        json={
            "bom_data": {
                "product_name": "铝合金型材",
                "hs_code": "7604",
                "weight_kg": 60000,
                "material": "铝",
                "origin_port": "深圳",
                "destination_port": "汉堡",
                "transport_mode": "sea",
            },
            "target_country": "EU",
        },
        headers=AUTH, timeout=300)
    check(r.status_code == 200)
    data = r.json(); THREAD_ID = data.get("thread_id", "")
    review = data.get("review_data", {})
    check(data["status"] == "pending_review")
    total = float(review.get("total_emissions", 0))
    check(total > 0)
    print(f"  [PASS] POST /audit/start")
    print(f"    thread_id: {THREAD_ID}")
    print(f"    product: {review.get('product_name')}")
    print(f"    total tCO2e: {total}")
    print(f"    risk: {review.get('risk_level')}")
    PASS += 1
except Exception as e:
    print(f"  [FAIL] {e}"); FAIL += 1

if THREAD_ID:
    try:
        r = requests.get(f"{BASE}/api/v1/audit/status/{THREAD_ID}",
            headers=AUTH, timeout=10)
        check(r.status_code == 200)
        data = r.json()
        check(data.get("pending_review") == True)
        print(f"  [PASS] GET /audit/status -> node={data.get('current_node')}")
        PASS += 1
    except Exception as e:
        print(f"  [FAIL] {e}"); FAIL += 1

# ---- 5. Approve ----
print()
print("5. HITL Approval")
print("=" * 60)
if THREAD_ID:
    try:
        r = requests.post(f"{BASE}/api/v1/audit/approve",
            json={"thread_id":THREAD_ID,"approved":True,"feedback":"OK"},
            headers=AUTH, timeout=120)
        check(r.status_code == 200)
        data = r.json()
        check(data["status"] == "completed")
        report = data.get("audit_report_md", "")
        check(len(report) > 100)
        check("碳排放" in report or "carbon" in report.lower() or "tCO2" in report)
        print(f"  [PASS] POST /audit/approve -> report {len(report)} chars")
        PASS += 1
    except Exception as e:
        print(f"  [FAIL] {e}"); FAIL += 1

print()
print("=" * 60)
print(f"RESULTS: {PASS} passed / {FAIL} failed")
print("=" * 60)
sys.exit(0 if FAIL == 0 else 1)
