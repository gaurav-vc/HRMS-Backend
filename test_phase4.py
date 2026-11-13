import os
import sys
sys.path.insert(0, 'C:/Hrms/HRMS-Backend')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
import django
django.setup()

from datetime import date, timedelta
from decimal import Decimal
from django.utils import timezone
from rest_framework.test import APIRequestFactory, force_authenticate
from authentication.models import User
from employees.models import Employee
from leaves.models import LeaveType, LeaveBalance, LeaveRequest
from leaves.views import LeaveRequestViewSet
from payroll.models import PayrollRun
from payroll.views import PayrollRunViewSet
from attendance.models import DynamicQRToken, PunchLog
from attendance.views import AttendanceViewSet
from organisation.models import Site

def run_tests():
    print("==================================================")
    print("RUNNING PHASE 4 BUSINESS LOGIC & CONCURRENCY TESTS")
    print("==================================================")

    factory = APIRequestFactory()
    user_admin = User.objects.get(username="Admin")
    user_emp = User.objects.get(username="employee")
    emp = user_emp.employee_profile

    # -------------------------------------------------------------------------
    # Test 1: Leave Engine - Overlap & Balance Concurrency
    # -------------------------------------------------------------------------
    print("\n--- Test 1: Leave Engine Concurrency & Balance Locking ---")
    lt = LeaveType.objects.filter(code="PL").first() or LeaveType.objects.filter(annual_entitlement__gt=0).first()
    year = date.today().year

    # Ensure clean starting balance of 10 days
    balance, _ = LeaveBalance.objects.get_or_create(
        employee=emp,
        leave_type=lt,
        year=year,
        defaults={"allocated_days": Decimal("10.00"), "used_days": Decimal("0.00"), "remaining_days": Decimal("10.00")}
    )
    balance.allocated_days = Decimal("10.00")
    balance.used_days = Decimal("0.00")
    balance.remaining_days = Decimal("10.00")
    balance.save()

    # Clear existing requests on target test dates for idempotency
    d1 = date(year, 11, 16)
    d2 = date(year, 11, 17)
    LeaveRequest.objects.filter(employee=emp, start_date=d1).delete()

    view_leave = LeaveRequestViewSet.as_view({'post': 'create'})

    # 1.1 Create first leave request for 2 days
    req1 = factory.post('/api/leaves/', {
        'leave_type': lt.id,
        'start_date': d1.strftime('%Y-%m-%d'),
        'end_date': d2.strftime('%Y-%m-%d'),
        'reason': 'Medical checkup'
    }, format='json')
    force_authenticate(req1, user=user_emp)
    resp1 = view_leave(req1)
    assert resp1.status_code == 201, f"FAIL: Expected 201, got {resp1.status_code}: {resp1.data}"
    leave_id = resp1.data.get('id')
    print(f"PASS: Created initial leave request {leave_id}")

    # 1.2 Overlapping leave request check (same dates)
    req_overlap = factory.post('/api/leaves/', {
        'leave_type': lt.id,
        'start_date': d1.strftime('%Y-%m-%d'),
        'end_date': d2.strftime('%Y-%m-%d'),
        'reason': 'Duplicate leave'
    }, format='json')
    force_authenticate(req_overlap, user=user_emp)
    resp_overlap = view_leave(req_overlap)
    assert resp_overlap.status_code == 400, f"FAIL: Expected 400 for overlapping leave, got {resp_overlap.status_code}"
    print(f"PASS: Overlapping leave correctly rejected: {resp_overlap.data.get('detail')}")

    # 1.3 Approve leave request & verify balance deduction
    view_approve = LeaveRequestViewSet.as_view({'patch': 'approve'})
    req_app = factory.patch(f'/api/leaves/{leave_id}/approve/', {'manager_comments': 'Approved!'}, format='json')
    force_authenticate(req_app, user=user_admin)
    resp_app = view_approve(req_app, pk=leave_id)
    assert resp_app.status_code == 200, f"FAIL: Approval failed: {resp_app.data}"
    
    # Reload balance from DB
    balance.refresh_from_db()
    assert balance.used_days == Decimal("2.00"), f"FAIL: Expected 2.00 used days, got {balance.used_days}"
    assert balance.remaining_days == Decimal("8.00"), f"FAIL: Expected 8.00 remaining days, got {balance.remaining_days}"
    assert resp_app.data.get('approved_by') != "Manager", "FAIL: approved_by should be real user name, not hardcoded 'Manager'!"
    print(f"PASS: Leave approved atomically. Balance remaining: {balance.remaining_days}, approvedBy: {resp_app.data.get('approved_by')}")

    # 1.4 Cancel leave request & verify balance refund
    view_cancel = LeaveRequestViewSet.as_view({'patch': 'cancel'})
    req_cancel = factory.patch(f'/api/leaves/{leave_id}/cancel/', {'manager_comments': 'Cancelled by user'}, format='json')
    force_authenticate(req_cancel, user=user_admin)
    resp_cancel = view_cancel(req_cancel, pk=leave_id)
    assert resp_cancel.status_code == 200, f"FAIL: Cancel failed: {resp_cancel.data}"
    
    balance.refresh_from_db()
    assert balance.used_days == Decimal("0.00"), f"FAIL: Balance was not refunded on cancel! {balance.used_days}"
    assert balance.remaining_days == Decimal("10.00"), f"FAIL: Balance was not restored to 10! {balance.remaining_days}"
    print(f"PASS: Leave cancelled and balance restored atomically: remaining={balance.remaining_days}")

    # -------------------------------------------------------------------------
    # Test 2: Payroll Concurrency & State Machine Protection
    # -------------------------------------------------------------------------
    print("\n--- Test 2: Payroll State Machine & Concurrency Guard ---")
    from organisation.models import Entity
    ent = Entity.objects.first()
    run = PayrollRun.objects.filter(entity=ent, period="2026-11").first()
    if not run:
        run = PayrollRun.objects.create(
            period="2026-11",
            entity=ent,
            status="Draft"
        )

    # Set status to Processing (simulating an in-flight background job)
    run.status = "Processing"
    run.save()

    view_payroll = PayrollRunViewSet.as_view({'post': 'execute'})
    req_pay = factory.post(f'/api/payroll/runs/{run.id}/execute/', {}, format='json')
    force_authenticate(req_pay, user=user_admin)
    resp_pay = view_payroll(req_pay, pk=run.id)
    
    assert resp_pay.status_code == 400, f"FAIL: Expected 400 for concurrent payroll run, got {resp_pay.status_code}"
    assert "currently being processed" in resp_pay.data.get('detail', ''), f"FAIL: Unexpected message {resp_pay.data}"
    print(f"PASS: Concurrent execution of running payroll blocked safely: {resp_pay.data.get('detail')}")

    # Reset run status back to Draft
    run.status = "Draft"
    run.save()

    # -------------------------------------------------------------------------
    # Test 3: Attendance Dynamic QR Expiry & Replay Defense
    # -------------------------------------------------------------------------
    print("\n--- Test 3: Attendance QR Expiry & Anti-Replay Defense ---")
    site = emp.site or Site.objects.first()
    
    # 3.1 Create expired QR token
    expired_token = DynamicQRToken.objects.create(
        site=site,
        expires_at=timezone.now() - timedelta(minutes=5) # 5 minutes in the past
    )

    view_punch = AttendanceViewSet.as_view({'post': 'punch'})
    req_expired = factory.post('/api/attendance/punch/', {
        'punch_type': 'IN',
        'source': 'QR',
        'qr_token': expired_token.token,
        'employee': emp.id
    }, format='json')
    force_authenticate(req_expired, user=user_emp)
    resp_expired = view_punch(req_expired)

    assert resp_expired.status_code == 400, f"FAIL: Expected 400 for expired QR code, got {resp_expired.status_code}"
    assert "expired" in resp_expired.data.get('error', '').lower() or "expired" in str(resp_expired.data).lower(), f"FAIL: Expected expired message, got {resp_expired.data}"
    print(f"PASS: Expired QR token rejected: {resp_expired.data}")

    # 3.2 Create valid QR token and punch in
    valid_token = DynamicQRToken.objects.create(
        site=site,
        expires_at=timezone.now() + timedelta(minutes=5)
    )
    req_valid = factory.post('/api/attendance/punch/', {
        'punch_type': 'IN',
        'source': 'QR',
        'qr_token': valid_token.token,
        'employee': emp.id
    }, format='json')
    force_authenticate(req_valid, user=user_emp)
    resp_valid = view_punch(req_valid)
    assert resp_valid.status_code == 200, f"FAIL: Valid QR punch failed: {resp_valid.data}"
    print("PASS: Valid QR code accepted for punch-in")

    # 3.3 Replay the exact same QR token for the same employee
    req_replay = factory.post('/api/attendance/punch/', {
        'punch_type': 'IN',
        'source': 'QR',
        'qr_token': valid_token.token,
        'employee': emp.id
    }, format='json')
    force_authenticate(req_replay, user=user_emp)
    resp_replay = view_punch(req_replay)
    assert resp_replay.status_code == 400, f"FAIL: Replay attack succeeded! Expected 400, got {resp_replay.status_code}"
    assert "replay" in str(resp_replay.data).lower(), f"FAIL: Expected replay message, got {resp_replay.data}"
    print(f"PASS: Replayed QR token blocked successfully: {resp_replay.data}")

    print("\n==================================================")
    print("ALL PHASE 4 BUSINESS LOGIC & CONCURRENCY TESTS PASSED!")
    print("==================================================")

if __name__ == '__main__':
    run_tests()
