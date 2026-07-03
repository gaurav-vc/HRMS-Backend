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

urlpatterns = [
    path('', include(router.urls)),
]
