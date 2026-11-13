import os
import sys
sys.path.insert(0, 'C:/Hrms/HRMS-Backend')
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
import django
django.setup()

import io
from rest_framework.test import APIRequestFactory, force_authenticate
from authentication.models import User
from announcements.views import AnnouncementViewSet
from employees.views import EmployeeViewSet
from leaves.views import LeaveRequestViewSet
from leaves.models import LeaveType

def run_tests():
    print("==================================================")
    print("RUNNING PHASE 3 SERIALIZATION & SCHEMA ALIGNMENT TESTS")
    print("==================================================")

    factory = APIRequestFactory()
    user = User.objects.get(username="Admin")

    # 1. Test CamelCase FormData Parsing
    print("\n--- Test 1: CamelCase Multipart FormData Parsing ---")
    view_ann = AnnouncementViewSet.as_view({'post': 'create'})
    
    # Send FormData with camelCase keys and an attachment
    dummy_file = io.BytesIO(b"dummy pdf attachment content")
    dummy_file.name = "company_policy.pdf"
    
    req_data = {
        'title': 'CamelCase Test Announcement',
        'content': 'Testing camelCase conversion in multipart forms',
        'priority': 'Normal',
        'audienceType': 'EVERYONE',
        'attachment': dummy_file,
        'attachmentName': 'company_policy.pdf'
    }
    
    req = factory.post('/api/announcements/', req_data, format='multipart')
    force_authenticate(req, user=user)
    
    resp = view_ann(req)
    print(f"Announcement create status: {resp.status_code}")
    assert resp.status_code == 201, f"FAIL: Expected 201, got {resp.status_code}: {resp.data}"
    assert resp.data.get('audience_type') == 'EVERYONE' or resp.data.get('audienceType') == 'EVERYONE', "FAIL: audience_type not parsed correctly!"
    print("PASS: CamelCase multipart FormData parsed and saved successfully!")

    # 2. Test DD-MM-YYYY Date Parsing
    print("\n--- Test 2: Multi-format Date Parsing (DD-MM-YYYY) ---")
    lt = LeaveType.objects.first()
    if not lt:
        lt = LeaveType.objects.create(name="Privilege Leave", code="PL", annual_entitlement=12)

    from leaves.models import LeaveRequest
    if hasattr(user, 'employee_profile') and user.employee_profile:
        LeaveRequest.objects.filter(employee=user.employee_profile, start_date__gte='2026-12-01').delete()

    view_leave = LeaveRequestViewSet.as_view({'post': 'create'})
    
    # Submit leave with DD-MM-YYYY format
    leave_data = {
        'leave_type': lt.id,
        'start_date': '20-12-2026',
        'end_date': '22-12-2026',
        'reason': 'Year-end vacation'
    }
    
    req = factory.post('/api/leaves/', leave_data, format='json')
    force_authenticate(req, user=user)
    
    resp = view_leave(req)
    print(f"Leave request creation with DD-MM-YYYY status: {resp.status_code}")
    assert resp.status_code == 201, f"FAIL: Expected 201, got {resp.status_code}: {resp.data}"
    # Verify the date was parsed to canonical ISO in the response/database
    start_d = str(resp.data.get('start_date') or resp.data.get('startDate'))
    assert '2026-12-20' in start_d, f"FAIL: Expected 2026-12-20, got {start_d}"
    print("PASS: DD-MM-YYYY date format seamlessly parsed and normalized to ISO-8601!")

    # 3. Test Empty & Malformed Payloads (Standard Error Envelope)
    print("\n--- Test 3: Standard Error Envelope on Malformed/Empty Payloads ---")
    # Post empty payload
    req = factory.post('/api/leaves/', {}, format='json')
    force_authenticate(req, user=user)
    resp = view_leave(req)
    
    print(f"Empty payload response status: {resp.status_code}")
    print(f"Response envelope: {resp.data}")
    assert resp.status_code == 400, f"FAIL: Expected 400 Bad Request, got {resp.status_code}"
    assert resp.data.get('status') == 'error', "FAIL: Response missing standard 'status': 'error' envelope"
    assert 'code' in resp.data, "FAIL: Response missing 'code' in envelope"
    assert 'detail' in resp.data or 'errors' in resp.data, "FAIL: Response missing error details"
    print("PASS: Empty payload returns structured 400 Bad Request with standardized error envelope!")

    # 4. Test Non-existent Resource Handling
    print("\n--- Test 4: 404 Resource Handling Envelope ---")
    view_detail = AnnouncementViewSet.as_view({'get': 'retrieve'})
    req = factory.get('/api/announcements/00000000-0000-0000-0000-000000000000/')
    force_authenticate(req, user=user)
    resp = view_detail(req, pk='00000000-0000-0000-0000-000000000000')
    
    print(f"Non-existent retrieve status: {resp.status_code}")
    print(f"Response envelope: {resp.data}")
    assert resp.status_code == 404, f"FAIL: Expected 404, got {resp.status_code}"
    assert resp.data.get('status') == 'error', "FAIL: Missing 'status': 'error' in 404 envelope"
    assert resp.data.get('code') == 404, "FAIL: Incorrect code in 404 envelope"
    print("PASS: 404 error enveloped cleanly in standard JSON envelope!")

    print("\n==================================================")
    print("ALL PHASE 3 SERIALIZATION & SCHEMA TESTS PASSED!")
    print("==================================================")

if __name__ == '__main__':
    run_tests()

