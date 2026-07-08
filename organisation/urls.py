from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import EntityViewSet, BranchViewSet, SiteViewSet, DepartmentViewSet, DesignationViewSet, RoleViewSet, AttendancePolicyViewSet

router = DefaultRouter()

router.register(r'entities', EntityViewSet)
router.register(r'branches', BranchViewSet)
router.register(r'sites', SiteViewSet)
router.register(r'departments', DepartmentViewSet)
router.register(r'designations', DesignationViewSet)
router.register(r'roles', RoleViewSet)
router.register(r'attendance-policies', AttendancePolicyViewSet, basename='attendance-policy')

urlpatterns = [
    path('', include(router.urls)),
]
