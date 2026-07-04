from django.urls import path
from .views import DashboardView, StatutoryRegisterView, CostCenterReportView, PayrollAttendanceReportView

urlpatterns = [
    path('dashboard/', DashboardView.as_view(), name='reports_dashboard'),
    path('statutory/', StatutoryRegisterView.as_view(), name='reports_statutory'),
    path('cost-centers/', CostCenterReportView.as_view(), name='reports_cost_centers'),
    path('payroll-attendance/', PayrollAttendanceReportView.as_view(), name='reports_payroll_attendance'),
]
