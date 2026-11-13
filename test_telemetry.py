import os
import sys
sys.path.insert(0, 'C:/Hrms/HRMS-Backend')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
import django
django.setup()

import time
from rest_framework.test import APIRequestFactory, force_authenticate
from authentication.models import User
from core.telemetry import (
    record_request_telemetry,
    get_telemetry_summary,
    resolve_anomaly,
    _ENDPOINT_METRICS,
    _ACTIVE_ANOMALIES,
)
from core.telemetry_views import (
    TelemetryOverviewAPIView,
    TelemetrySyntheticRunAPIView,
    TelemetryResolveAnomalyAPIView,
)

def run_tests():
    print("==================================================")
    print("RUNNING APM TELEMETRY & ML ANOMALY DETECTION TESTS")
    print("==================================================")

    factory = APIRequestFactory()
    user_admin = User.objects.get(username="Admin")
    user_emp = User.objects.get(username="employee")

    # -------------------------------------------------------------------------
    # Test 1: Platform Segregation & Rolling Baseline Computation
    # -------------------------------------------------------------------------
    print("\n--- Test 1: Platform Segregation (WEB vs MOBILE Baselines) ---")
    test_endpoint = "/api/test-profile"
    
    # Record 6 samples for WEB (average 20ms)
    for _ in range(6):
        record_request_telemetry(
            endpoint=test_endpoint,
            method="GET",
            status_code=200,
            duration_ms=20.0,
            query_count=2,
            view_name="TestView",
            file_source="test_view.py:10",
            platform="WEB",
            tenant_id="tenant_1"
        )

    # Record 6 samples for MOBILE (average 80ms)
    for _ in range(6):
        record_request_telemetry(
            endpoint=test_endpoint,
            method="GET",
            status_code=200,
            duration_ms=80.0,
            query_count=2,
            view_name="TestView",
            file_source="test_view.py:10",
            platform="MOBILE",
            tenant_id="tenant_1"
        )

    window = _ENDPOINT_METRICS["GET " + test_endpoint]
    web_stats = window.web.get_stats()
    mobile_stats = window.mobile.get_stats()

    assert web_stats["count"] == 6, f"Expected 6 web samples, got {web_stats['count']}"
    assert mobile_stats["count"] == 6, f"Expected 6 mobile samples, got {mobile_stats['count']}"
    assert web_stats["mean"] == 20.0, f"Expected 20.0ms web mean, got {web_stats['mean']}"
    assert mobile_stats["mean"] == 80.0, f"Expected 80.0ms mobile mean, got {mobile_stats['mean']}"
    print(f"PASS: Platform metrics segregated cleanly (Web Mean: {web_stats['mean']}ms, Mobile Mean: {mobile_stats['mean']}ms)!")

    # -------------------------------------------------------------------------
    # Test 2: Statistical Z-Score Latency Spike Detection
    # -------------------------------------------------------------------------
    print("\n--- Test 2: Statistical Z-Score Latency Spike Detection ---")
    # Seed variance into web slice so std_dev > 5.0ms
    for d in [10.0, 30.0, 15.0, 25.0, 20.0]:
        record_request_telemetry(
            endpoint=test_endpoint,
            method="GET",
            status_code=200,
            duration_ms=d,
            query_count=2,
            view_name="TestView",
            file_source="test_view.py:10",
            platform="WEB",
            tenant_id="tenant_1"
        )

    # Now inject a latency spike (450ms) on WEB
    initial_anom_count = len(_ACTIVE_ANOMALIES)
    record_request_telemetry(
        endpoint=test_endpoint,
        method="GET",
        status_code=200,
        duration_ms=450.0,
        query_count=2,
        view_name="TestView",
        file_source="test_view.py:10",
        platform="WEB",
        tenant_id="tenant_1",
        actor_email="dev@hrms.com"
    )

    assert len(_ACTIVE_ANOMALIES) > initial_anom_count, "FAIL: Latency spike anomaly not registered!"
    latest_anom = _ACTIVE_ANOMALIES[0]
    assert latest_anom["type"] == "LATENCY_SPIKE", f"FAIL: Expected LATENCY_SPIKE, got {latest_anom['type']}"
    assert latest_anom["platform"] == "WEB", f"FAIL: Expected WEB platform attribution, got {latest_anom['platform']}"
    assert latest_anom["zScore"] > 2.5, f"FAIL: Expected z-score > 2.5, got {latest_anom['zScore']}"
    assert "standard deviations" in latest_anom["diagnosis"]
    assert "prescription" in latest_anom
    print(f"PASS: Z-Score Latency Spike caught! Z={latest_anom['zScore']}, Diagnosis: {latest_anom['diagnosis']}")

    # -------------------------------------------------------------------------
    # Test 3: N+1 Database Query Surge Detection (>3x baseline)
    # -------------------------------------------------------------------------
    print("\n--- Test 3: N+1 Database Query Explosion Heuristic ---")
    query_endpoint = "/api/employees/nplus1"
    # Seed baseline with 2 DB queries
    for _ in range(6):
        record_request_telemetry(
            endpoint=query_endpoint,
            method="GET",
            status_code=200,
            duration_ms=25.0,
            query_count=2,
            view_name="EmployeeListView",
            file_source="employees/views.py:45",
            platform="WEB",
            tenant_id="tenant_1"
        )

    # Inject N+1 surge: 28 queries (14x baseline)
    record_request_telemetry(
        endpoint=query_endpoint,
        method="GET",
        status_code=200,
        duration_ms=50.0,
        query_count=28,
        view_name="EmployeeListView",
        file_source="employees/views.py:45",
        platform="WEB",
        tenant_id="tenant_1"
    )

    db_anom = next((a for a in _ACTIVE_ANOMALIES if a["type"] == "N_PLUS_ONE_SURGE"), None)
    assert db_anom is not None, "FAIL: N+1 surge anomaly was not detected!"
    assert "select_related" in db_anom["prescription"], "FAIL: Prescription should suggest select_related/prefetch_related"
    print(f"PASS: N+1 DB loop surge detected! Metric: {db_anom['metricValue']}, Prescription: {db_anom['prescription']}")

    # -------------------------------------------------------------------------
    # Test 4: 5xx Server Exception Capture
    # -------------------------------------------------------------------------
    print("\n--- Test 4: 5xx Internal Server Exception Capture ---")
    crash_endpoint = "/api/payroll/broken"
    record_request_telemetry(
        endpoint=crash_endpoint,
        method="POST",
        status_code=500,
        duration_ms=120.0,
        query_count=4,
        view_name="PayrollCrashView",
        file_source="payroll/views.py:99",
        platform="MOBILE",
        tenant_id="tenant_2",
        error_message="ZeroDivisionError: division by zero in salary formula"
    )

    err_anom = next((a for a in _ACTIVE_ANOMALIES if a["type"] == "SERVER_EXCEPTION_5XX"), None)
    assert err_anom is not None, "FAIL: 5xx exception anomaly was not captured!"
    assert err_anom["severity"] == "CRITICAL"
    assert err_anom["platform"] == "MOBILE"
    assert "ZeroDivisionError" in err_anom["diagnosis"]
    print(f"PASS: 5xx exception recorded with diagnosis: {err_anom['diagnosis']}")

    # -------------------------------------------------------------------------
    # Test 5: RBAC Security Gate - Super Admin Only
    # -------------------------------------------------------------------------
    print("\n--- Test 5: RBAC Security Gate (Super Admin Only) ---")
    view_overview = TelemetryOverviewAPIView.as_view()

    # 5.1 Call as regular employee -> Expect HTTP 403
    req_emp = factory.get('/api/v1/superadmin/telemetry/overview/')
    force_authenticate(req_emp, user=user_emp)
    resp_emp = view_overview(req_emp)
    assert resp_emp.status_code == 403, f"FAIL: Expected 403 Forbidden for employee, got {resp_emp.status_code}"
    print("PASS: Non-superadmin employee blocked with HTTP 403 Forbidden!")

    # 5.2 Call as Super Admin -> Expect HTTP 200 OK
    req_admin = factory.get('/api/v1/superadmin/telemetry/overview/?platform=ALL')
    force_authenticate(req_admin, user=user_admin)
    resp_admin = view_overview(req_admin)
    assert resp_admin.status_code == 200, f"FAIL: Expected 200 OK for superadmin, got {resp_admin.status_code}"
    data = resp_admin.data.get("data", {})
    assert "platformHealthScore" in data
    assert "globalP95Latency" in data
    assert "activeAnomalies" in data
    assert "endpoints" in data
    assert "platformSummary" in data
    print(f"PASS: Super Admin received APM overview! Health Score: {data['platformHealthScore']}%, Global P95: {data['globalP95Latency']}ms")

    # -------------------------------------------------------------------------
    # Test 6: Proactive Synthetic Canary Probe Runner
    # -------------------------------------------------------------------------
    print("\n--- Test 6: Proactive Synthetic Canary Probe Across Tenants ---")
    view_canary = TelemetrySyntheticRunAPIView.as_view()
    req_canary = factory.post('/api/v1/superadmin/telemetry/synthetic-probe/')
    force_authenticate(req_canary, user=user_admin)
    resp_canary = view_canary(req_canary)
    assert resp_canary.status_code == 200, f"FAIL: Synthetic probe failed: {resp_canary.status_code}"
    canary_data = resp_canary.data.get("canaryReport", {})
    assert canary_data.get("probesExecuted", 0) > 0, "FAIL: No probes executed!"
    print(f"PASS: Canary executed {canary_data['probesExecuted']} automated tenant probes across Web & Mobile in {canary_data['totalDurationMs']}ms (Passed: {canary_data['passed']})!")

    # -------------------------------------------------------------------------
    # Test 7: Anomaly Resolution
    # -------------------------------------------------------------------------
    print("\n--- Test 7: Super Admin Anomaly Resolution ---")
    view_resolve = TelemetryResolveAnomalyAPIView.as_view()
    anom_id = latest_anom["id"]
    req_resolve = factory.post('/api/v1/superadmin/telemetry/anomalies/resolve/', {"anomalyId": anom_id}, format='json')
    force_authenticate(req_resolve, user=user_admin)
    resp_resolve = view_resolve(req_resolve)
    assert resp_resolve.status_code == 200
    assert resp_resolve.data.get("resolved") is True
    # Verify removed from active deque
    assert not any(a["id"] == anom_id for a in _ACTIVE_ANOMALIES)
    print(f"PASS: Anomaly {anom_id} successfully resolved and cleared from active alerts!")

    print("\n==================================================")
    print("ALL APM TELEMETRY & ML ANOMALY TESTS PASSED (100%)!")
    print("==================================================")

if __name__ == '__main__':
    run_tests()

