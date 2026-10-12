from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import AttendanceViewSet, RegularizationViewSet, ShiftDefinitionViewSet, RosterViewSet, HolidayViewSet, HolidayRuleGroupViewSet

router = DefaultRouter()
router.register(r'regularization', RegularizationViewSet, basename='regularization')
router.register(r'shifts', ShiftDefinitionViewSet, basename='shifts')
router.register(r'roster', RosterViewSet, basename='roster')
router.register(r'holidays', HolidayViewSet, basename='holidays')
router.register(r'holiday-rules', HolidayRuleGroupViewSet, basename='holiday-rules')
router.register(r'', AttendanceViewSet, basename='attendance')
from .liveness_api import LivenessChallengeAPIView, LivenessVerifyAPIView
from .kiosk_api import KioskConfigAPIView, KioskPunchAPIView, KioskVerifyPinAPIView

urlpatterns = [
    path('kiosk/config/', KioskConfigAPIView.as_view(), name='kiosk-config'),
    path('kiosk/punch/', KioskPunchAPIView.as_view(), name='kiosk-punch'),
    path('kiosk/verify-pin/', KioskVerifyPinAPIView.as_view(), name='kiosk-verify-pin'),
    path('liveness/challenge/', LivenessChallengeAPIView.as_view(), name='liveness-challenge'),
    path('liveness/verify/', LivenessVerifyAPIView.as_view(), name='liveness-verify'),
    path('', include(router.urls)),
]
