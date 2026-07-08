from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import OrganizationViewSet, InvoiceViewSet

router = DefaultRouter()
router.register(r'organizations', OrganizationViewSet)
router.register(r'invoices', InvoiceViewSet)

urlpatterns = [
    path('', include(router.urls)),
]
