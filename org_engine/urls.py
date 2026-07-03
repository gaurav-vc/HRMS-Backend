from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import OrganizationNodeTypeViewSet, OrganizationNodeViewSet, OrganizationAuditLogViewSet

router = DefaultRouter()
router.register(r'node-types', OrganizationNodeTypeViewSet)
router.register(r'nodes', OrganizationNodeViewSet)
router.register(r'audit-logs', OrganizationAuditLogViewSet)

urlpatterns = [
    path('', include(router.urls)),
]
