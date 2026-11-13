import os, django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()
from django.test import RequestFactory
from rest_framework_simplejwt.views import TokenObtainPairView

rf = RequestFactory()
req = rf.post('/api/auth/token/', data='{"username":"Admin","password":"123"}', content_type='application/json')
# Access body before view
b = req.body
print("Accessed req.body:", b)

view = TokenObtainPairView.as_view()
resp = view(req)
print("DRF view executed with status:", resp.status_code)

