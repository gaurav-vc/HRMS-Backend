from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import LeaveRequestViewSet, LeaveTypeViewSet, LeaveBalanceViewSet, HolidayViewSet, LeavePolicyConfigAPIView

router = DefaultRouter()
router.register(r'types', LeaveTypeViewSet, basename='leavetype')
router.register(r'balances', LeaveBalanceViewSet, basename='leavebalance')
router.register(r'holidays', HolidayViewSet, basename='holiday')
router.register(r'', LeaveRequestViewSet, basename='leaverequest')

urlpatterns = [
    path('config/', LeavePolicyConfigAPIView.as_view(), name='leave-config'),
    path('', include(router.urls)),
]
