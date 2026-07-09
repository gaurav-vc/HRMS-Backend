from django.db import models
from django.conf import settings
from employees.models import Employee
from organisation.models import Entity, Department

# ==========================================
# CORE CONFIGURATION & AUDIT
# ==========================================

class PayrollSettings(models.Model):
    """Admin configurable settings to eliminate hardcoded values"""
    ctc_variance_threshold_percent = models.DecimalField(max_digits=5, decimal_places=2, default=1.0)
    pf_wage_limit = models.DecimalField(max_digits=10, decimal_places=2, default=15000.0)
    esic_wage_limit = models.DecimalField(max_digits=10, decimal_places=2, default=21000.0)
    
class PayrollEvent(models.Model):
    """Central Signal-Based Audit Bus"""
    EVENT_TYPES = (
        ('PayrollGenerated', 'PayrollGenerated'),
        ('PayslipFrozen', 'PayslipFrozen'),
        ('RetroCreated', 'RetroCreated'),
        ('RuleChanged', 'RuleChanged'),
        ('ApprovalGranted', 'ApprovalGranted'),
        ('RunFailed', 'RunFailed'),
        ('SimulationRun', 'SimulationRun'),
    )
    type = models.CharField(max_length=50, choices=EVENT_TYPES)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    timestamp = models.DateTimeField(auto_now_add=True)
    reference = models.CharField(max_length=100)
    payload = models.JSONField(default=dict)

class CTCImportHistory(models.Model):
    import_date = models.DateTimeField(auto_now_add=True)
    imported_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    records_processed = models.IntegerField(default=0)
    successful = models.IntegerField(default=0)
    failed = models.IntegerField(default=0)
    file_type = models.CharField(max_length=20, default='CSV')
    duration_seconds = models.IntegerField(default=0)
    status = models.CharField(max_length=20, choices=[('Completed', 'Completed'), ('Partial', 'Partial'), ('Failed', 'Failed')], default='Completed')

    def __str__(self):
        return f"Import {self.id} on {self.import_date}"

# ==========================================
# COST CENTERS & ALLOCATION
# ==========================================

class CostCenter(models.Model):
    name = models.CharField(max_length=100)
    code = models.CharField(max_length=50, unique=True)
    department = models.ForeignKey(Department, on_delete=models.CASCADE, related_name='cost_centers')

class EmployeeAllocation(models.Model):
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='allocations')
    cost_center = models.ForeignKey(CostCenter, on_delete=models.CASCADE)
    percentage = models.DecimalField(max_digits=5, decimal_places=2, help_text="Split percentage")

# ==========================================
# FORMULA ENGINE & VERSIONING
# ==========================================

class SalaryStructure(models.Model):
    STATUS_CHOICES = (('Active', 'Active'), ('Draft', 'Draft'))
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True, null=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='Draft')
    created_at = models.DateTimeField(auto_now_add=True)

class ComponentRule(models.Model):
    TYPE_CHOICES = (('Earning', 'Earning'), ('Deduction', 'Deduction'), ('Employer Contribution', 'Employer Contribution'))
    structure = models.ForeignKey(SalaryStructure, on_delete=models.CASCADE, related_name='components', null=True, blank=True)
    name = models.CharField(max_length=100)
    variable_code = models.CharField(max_length=50, unique=False, null=True, blank=True, help_text="Immutable code used in formulas (e.g., BASIC_PAY)")
    type = models.CharField(max_length=50, choices=TYPE_CHOICES)
    calc = models.CharField(max_length=50, default="Fixed")
    value = models.DecimalField(max_digits=12, decimal_places=2, default=0.0)
    
    formula = models.TextField(help_text="Evaluated safely via simpleeval", null=True, blank=True)
    is_statutory = models.BooleanField(default=False)
    prorate = models.BooleanField(default=False, help_text="Multiply result by (present_days / total_days)")
    
    effective_from = models.DateField()
    effective_to = models.DateField(null=True, blank=True)

    def __str__(self):
        return f"{self.name} ({self.type})"

class RuleDependency(models.Model):
    """Adjacency list for DAG Topological Sorting"""
    from_rule = models.ForeignKey(ComponentRule, related_name='outgoing_deps', on_delete=models.CASCADE)
    to_rule = models.ForeignKey(ComponentRule, related_name='incoming_deps', on_delete=models.CASCADE)

class RuleChangeLog(models.Model):
    rule = models.ForeignKey(ComponentRule, on_delete=models.CASCADE)
    changed_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    changed_at = models.DateTimeField(auto_now_add=True)
    reason = models.TextField()

class TaxRegimeSlab(models.Model):
    REGIME_CHOICES = (('Old', 'Old'), ('New', 'New'))
    regime = models.CharField(max_length=10, choices=REGIME_CHOICES)
    effective_from = models.DateField()
    effective_to = models.DateField(null=True, blank=True)
    min_income = models.DecimalField(max_digits=12, decimal_places=2)
    max_income = models.DecimalField(max_digits=12, decimal_places=2, null=True, blank=True)
    tax_rate = models.DecimalField(max_digits=5, decimal_places=2)

# ==========================================
# EXECUTION & IMMUTABILITY
# ==========================================

class PayrollRun(models.Model):
    STATUS_CHOICES = (
        ('Draft', 'Draft'),
        ('Processing', 'Processing'),
        ('Maker-Submitted', 'Maker-Submitted'),
        ('Checker-Approved', 'Checker-Approved'),
        ('Frozen', 'Frozen'),
        ('Disbursed', 'Disbursed'),
    )
    RUN_TYPE = (('Live', 'Live'), ('Simulation', 'Simulation'))
    
    period = models.CharField(max_length=7, help_text="YYYY-MM")
    entity = models.ForeignKey(Entity, on_delete=models.CASCADE, related_name='payroll_runs')
    run_type = models.CharField(max_length=20, choices=RUN_TYPE, default='Live')
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='Draft')
    
    maker = models.ForeignKey(settings.AUTH_USER_MODEL, related_name='made_runs', null=True, on_delete=models.SET_NULL)
    checker = models.ForeignKey(settings.AUTH_USER_MODEL, related_name='checked_runs', null=True, on_delete=models.SET_NULL)
    lock_date = models.DateField(null=True, blank=True)

class PayrollRunComment(models.Model):
    run = models.ForeignKey(PayrollRun, on_delete=models.CASCADE, related_name='comments')
    author = models.ForeignKey(settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL)
    comment = models.TextField()
    timestamp = models.DateTimeField(auto_now_add=True)


class Payslip(models.Model):
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE)
    run = models.ForeignKey(PayrollRun, on_delete=models.CASCADE)
    period = models.CharField(max_length=7)
    
    gross = models.DecimalField(max_digits=12, decimal_places=2, default=0.0)
    deductions = models.DecimalField(max_digits=12, decimal_places=2, default=0.0)
    net = models.DecimalField(max_digits=12, decimal_places=2, default=0.0)

    class Meta:
        unique_together = ('employee', 'period', 'run')

class PayslipLineItem(models.Model):
    payslip = models.ForeignKey(Payslip, on_delete=models.CASCADE, related_name='lines')
    rule = models.ForeignKey(ComponentRule, on_delete=models.PROTECT)
    amount = models.DecimalField(max_digits=12, decimal_places=2)

class PayslipAllocationSnapshot(models.Model):
    payslip = models.ForeignKey(Payslip, on_delete=models.CASCADE)
    cost_center = models.ForeignKey(CostCenter, on_delete=models.PROTECT)
    percentage = models.DecimalField(max_digits=5, decimal_places=2)

class SimulatedPayslip(models.Model):
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE)
    run = models.ForeignKey(PayrollRun, on_delete=models.CASCADE)
    period = models.CharField(max_length=7)
    gross = models.DecimalField(max_digits=12, decimal_places=2, default=0.0)
    deductions = models.DecimalField(max_digits=12, decimal_places=2, default=0.0)
    net = models.DecimalField(max_digits=12, decimal_places=2, default=0.0)

class SimulatedLineItem(models.Model):
    payslip = models.ForeignKey(SimulatedPayslip, on_delete=models.CASCADE, related_name='lines')
    rule = models.ForeignKey(ComponentRule, on_delete=models.PROTECT)
    amount = models.DecimalField(max_digits=12, decimal_places=2)

# ==========================================
# EXCEPTIONS & RETRO
# ==========================================

class PayrollException(models.Model):
    run = models.ForeignKey(PayrollRun, on_delete=models.CASCADE)
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE)
    error_trace = models.TextField()
    resolved = models.BooleanField(default=False)

class RetroPayrollEntry(models.Model):
    original_payslip = models.ForeignKey(Payslip, on_delete=models.CASCADE, related_name='retros')
    target_run = models.ForeignKey(PayrollRun, on_delete=models.CASCADE, related_name='retro_merges')
    diff_amount = models.DecimalField(max_digits=12, decimal_places=2)
    approved_for_merge = models.BooleanField(default=False)
    maker = models.ForeignKey(settings.AUTH_USER_MODEL, related_name='made_retros', null=True, on_delete=models.SET_NULL)
    checker = models.ForeignKey(settings.AUTH_USER_MODEL, related_name='checked_retros', null=True, on_delete=models.SET_NULL)

# ==========================================
# STATUTORY & LEGACY
# ==========================================

class StatutoryRegister(models.Model):
    run = models.ForeignKey(PayrollRun, on_delete=models.CASCADE)
    type = models.CharField(max_length=50) # PF, ESIC, PT, TDS
    generated_at = models.DateTimeField(auto_now_add=True)
    payload = models.JSONField()

class Loan(models.Model):
    STATUS_CHOICES = (('Active', 'Active'), ('Closed', 'Closed'), ('Pending', 'Pending'))
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='loans')
    type = models.CharField(max_length=50) 
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    emi = models.DecimalField(max_digits=10, decimal_places=2)
    tenure = models.IntegerField(help_text="In months")
    outstanding = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='Pending')

class Reimbursement(models.Model):
    STATUS_CHOICES = (('Pending', 'Pending'), ('Approved', 'Approved'), ('Rejected', 'Rejected'), ('Paid', 'Paid'))
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='reimbursements')
    category = models.CharField(max_length=50)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    date = models.DateField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='Pending')
    receipt = models.FileField(upload_to='reimbursements/receipts/', null=True, blank=True)

class ComplianceReport(models.Model):
    STATUS_CHOICES = (('Draft', 'Draft'), ('Pending', 'Pending'), ('Generated', 'Generated'), ('Filed', 'Filed'))
    CATEGORY_CHOICES = (('Provident Fund', 'Provident Fund'), ('ESI', 'ESI'), ('Professional Tax', 'Professional Tax'), ('TDS', 'TDS'))
    category = models.CharField(max_length=50, choices=CATEGORY_CHOICES, default='Provident Fund')
    key = models.CharField(max_length=100)
    desc = models.CharField(max_length=255)
    period = models.CharField(max_length=20, default='October 2026')
    amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    challan_number = models.CharField(max_length=100, blank=True, null=True)
    due = models.DateField()
    filed_on = models.DateField(blank=True, null=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='Draft')

# ==========================================
# TAX & FORM 16
# ==========================================

class Form16Document(models.Model):
    STATUS_CHOICES = (('Pending', 'Pending'), ('Distributed', 'Distributed'), ('Failed', 'Failed'))
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='form16_documents')
    financial_year = models.CharField(max_length=20)
    version = models.IntegerField(default=1)
    file = models.FileField(upload_to='form16_documents/')
    uploaded_by = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True)
    uploaded_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='Pending')

    class Meta:
        unique_together = ('employee', 'financial_year', 'version')
