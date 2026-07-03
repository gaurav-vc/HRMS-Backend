import os
import django
import sys
import json

# Setup Django
sys.path.append(r"c:\Users\MC VIP\OneDrive\Desktop\HRMS\backend")
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "hrms.settings")
django.setup()

from attendance.models import DailyAttendance
from attendance.serializers import DailyAttendanceSerializer

latest = DailyAttendance.objects.order_by('-id').first()
if latest:
    data = DailyAttendanceSerializer(latest).data
    print(json.dumps(data, indent=2))
else:
    print("No attendance records found.")
