from django.contrib import admin
from .models import (
    PayrollSettings, PayrollEvent, CostCenter, EmployeeAllocation,
    SalaryStructure, ComponentRule, RuleDependency, RuleChangeLog, TaxRegimeSlab,
    PayrollRun, Payslip, PayslipLineItem, PayslipAllocationSnapshot,
    SimulatedPayslip, SimulatedLineItem, PayrollException, RetroPayrollEntry,
    Loan, Reimbursement, ComplianceReport
)

# Core & Audit
admin.site.register(PayrollSettings)
admin.site.register(PayrollEvent)

# Cost Centers & Allocations
admin.site.register(CostCenter)
admin.site.register(EmployeeAllocation)

# Formula Engine & Versioning
admin.site.register(SalaryStructure)
admin.site.register(ComponentRule)
admin.site.register(RuleDependency)
admin.site.register(RuleChangeLog)
admin.site.register(TaxRegimeSlab)

# Execution & Payslips
admin.site.register(PayrollRun)
admin.site.register(Payslip)
admin.site.register(PayslipLineItem)
admin.site.register(PayslipAllocationSnapshot)
admin.site.register(SimulatedPayslip)
admin.site.register(SimulatedLineItem)

# Exceptions & Retro
admin.site.register(PayrollException)
admin.site.register(RetroPayrollEntry)

# Add-ons
admin.site.register(Loan)
admin.site.register(Reimbursement)

# Compliance
admin.site.register(ComplianceReport)
