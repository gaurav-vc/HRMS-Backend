from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import PayrollRunViewSet, LoanViewSet, ReimbursementViewSet, ComponentRuleViewSet, ComplianceReportViewSet, SalarySlipAPIView, SalaryStructureViewSet, PayslipPDFView, PayslipEmailView, PayrollPreviewAPIView, Form16DocumentViewSet

router = DefaultRouter()
router.register(r'runs', PayrollRunViewSet)
router.register(r'loans', LoanViewSet)
router.register(r'reimbursements', ReimbursementViewSet)
router.register(r'components', ComponentRuleViewSet)
router.register(r'compliance', ComplianceReportViewSet)
router.register(r'structures', SalaryStructureViewSet)
router.register(r'form16', Form16DocumentViewSet)

urlpatterns = [
    path('preview/', PayrollPreviewAPIView.as_view(), name='payroll-preview'),
    path('slips/<int:pk>/pdf/', PayslipPDFView.as_view(), name='payslip-pdf'),
    path('slips/<int:pk>/email/', PayslipEmailView.as_view(), name='payslip-email'),
    path('slips/', SalarySlipAPIView.as_view(), name='salary-slips'),
    path('', include(router.urls)),
]
