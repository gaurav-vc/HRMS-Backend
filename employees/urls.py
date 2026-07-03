from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import EmployeeViewSet, EmployeeDocumentViewSet, EmployeeTransferViewSet, EmployeeExitViewSet, NotificationViewSet, OfferLetterViewSet, OfferTemplateViewSet
from .dashboard_views import DashboardStatsAPIView

router = DefaultRouter()
router.register(r'employees', EmployeeViewSet, basename='employee')
router.register(r'documents', EmployeeDocumentViewSet, basename='employee-document')
router.register(r'transfers', EmployeeTransferViewSet, basename='employee-transfer')
router.register(r'exits', EmployeeExitViewSet, basename='employee-exit')
router.register(r'notifications', NotificationViewSet, basename='notification')
router.register(r'offer-letters', OfferLetterViewSet, basename='offer-letter')
router.register(r'offer-templates', OfferTemplateViewSet, basename='offer-template')

urlpatterns = [
    path('dashboard/stats/', DashboardStatsAPIView.as_view(), name='dashboard-stats'),
    path('', include(router.urls)),
]
