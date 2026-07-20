import os
import django
import sys
import traceback

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

from django.test import RequestFactory
from django.contrib.auth.models import User
from employees.dashboard_views import DashboardStatsAPIView

req = RequestFactory().get('/api/dashboard/stats/')
user = User.objects.filter(is_superuser=True).first() or User.objects.first()
req.user = user

view = DashboardStatsAPIView.as_view()

try:
    res = view(req)
    print("STATUS CODE:", res.status_code)
except Exception as e:
    print("500 ERROR TRACEBACK:")
    print(traceback.format_exc())
