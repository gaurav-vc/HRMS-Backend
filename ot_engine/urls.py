from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .api import OTPolicyViewSet, OTRequestViewSet, CompOffViewSet

router = DefaultRouter()
router.register(r'policies', OTPolicyViewSet)
router.register(r'requests', OTRequestViewSet)
router.register(r'comp-off', CompOffViewSet)

urlpatterns = [
    path('', include(router.urls)),
]
