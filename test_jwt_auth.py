import os, django
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()
from django.test import RequestFactory
from django.contrib.auth import get_user_model
from rest_framework_simplejwt.tokens import RefreshToken
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated

User = get_user_model()
admin = User.objects.filter(is_superuser=True).first()
token = str(RefreshToken.for_user(admin).access_token)

class TestProtectedView(APIView):
    permission_classes = [IsAuthenticated]
    def get(self, request):
        return Response({"user": str(request.user)})

rf = RequestFactory()
req = rf.get('/api/test/', HTTP_AUTHORIZATION=f'Bearer {token}')

print("Before view, req.user:", getattr(req, "user", "No user attr"))
resp = TestProtectedView.as_view()(req)
print("After view, resp status:", resp.status_code)
print("After view, req.user:", getattr(req, "user", "No user attr"))
print("Is authenticated:", req.user.is_authenticated if hasattr(req, "user") else "No")

