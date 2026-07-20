import os
import django
import sys
import traceback

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

from django.test import RequestFactory
from django.contrib.auth.models import User
from employees.dashboard_views import DashboardStatsAPIView
from employees.models import Employee

req = RequestFactory().get('/api/dashboard/stats/')
# Try with an employee user instead of superuser
emp = Employee.objects.first()
if emp and emp.user:
    user = emp.user
else:
    user = User.objects.filter(is_superuser=False).first()

if not user:
    print("No non-superuser found!")
else:
    print(f"Testing with user: {user.username}")
    req.user = user

    view = DashboardStatsAPIView.as_view()

    try:
        res = view(req)
        print("STATUS CODE:", res.status_code)
        if res.status_code == 500:
            print("Response:", res.content)
    except Exception as e:
        print("500 ERROR TRACEBACK:")
        print(traceback.format_exc())
