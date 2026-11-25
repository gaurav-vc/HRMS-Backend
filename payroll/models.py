import datetime
import calendar
import decimal
from decimal import Decimal
from django.db import models
from django.conf import settings
from employees.models import Employee
from organisation.models import Entity, Department

# ==========================================
# CORE CONFIGURATION & AUDIT
# ==========================================


class PayrollSettings(models.Model):
    """Admin configurable settings to eliminate hardcoded values"""

    ctc_variance_threshold_percent = models.DecimalField(
        max_digits=5, decimal_places=2, default=1.0
    )
    pf_wage_limit = models.DecimalField(
        max_digits=10, decimal_places=2, default=15000.0
    )
    esic_wage_limit = models.DecimalField(
        max_digits=10, decimal_places=2, default=21000.0
    )


class PayrollEvent(models.Model):
    """Central Signal-Based Audit Bus"""

    EVENT_TYPES = (
        ("PayrollGenerated", "PayrollGenerated"),
        ("PayslipFrozen", "PayslipFrozen"),
        ("RetroCreated", "RetroCreated"),
        ("RuleChanged", "RuleChanged"),
        ("ApprovalGranted", "ApprovalGranted"),
        ("RunFailed", "RunFailed"),
        ("SimulationRun", "SimulationRun"),
    )
    type = models.CharField(max_length=50, choices=EVENT_TYPES)
    actor = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL
    )
    timestamp = models.DateTimeField(auto_now_add=True)
    reference = models.CharField(max_length=100)
    payload = models.JSONField(default=dict)


class CTCImportHistory(models.Model):
    import_date = models.DateTimeField(auto_now_add=True)
    imported_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True
    )
    records_processed = models.IntegerField(default=0)
    successful = models.IntegerField(default=0)
    failed = models.IntegerField(default=0)
    file_type = models.CharField(max_length=20, default="CSV")
    duration_seconds = models.IntegerField(default=0)
    status = models.CharField(
        max_length=20,
        choices=[
            ("Completed", "Completed"),
            ("Partial", "Partial"),
            ("Failed", "Failed"),
        ],
        default="Completed",
    )

    def __str__(self):
        return f"Import {self.id} on {self.import_date}"


# ==========================================
# COST CENTERS & ALLOCATION
# ==========================================


class CostCenter(models.Model):
    name = models.CharField(max_length=100)
    code = models.CharField(max_length=50, unique=True)
    department = models.ForeignKey(
        Department, on_delete=models.CASCADE, related_name="cost_centers"
    )


class EmployeeAllocation(models.Model):
    employee = models.ForeignKey(
        Employee, on_delete=models.CASCADE, related_name="allocations"
    )
    cost_center = models.ForeignKey(CostCenter, on_delete=models.CASCADE)
    percentage = models.DecimalField(
        max_digits=5, decimal_places=2, help_text="Split percentage"
    )


# ==========================================
# FORMULA ENGINE & VERSIONING
# ==========================================


class SalaryStructure(models.Model):
    site = models.ForeignKey(
        "organisation.Site",
        on_delete=models.CASCADE,
        related_name="salary_structures",
        null=True,
        blank=True,
    )
    STATUS_CHOICES = (("Active", "Active"), ("Draft", "Draft"))
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True, null=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="Draft")
    created_at = models.DateTimeField(auto_now_add=True)


class ComponentRule(models.Model):
    TYPE_CHOICES = (
        ("Earning", "Earning"),
        ("Deduction", "Deduction"),
        ("Employer Contribution", "Employer Contribution"),
    )
    structure = models.ForeignKey(
        SalaryStructure,
        on_delete=models.CASCADE,
        related_name="components",
        null=True,
        blank=True,
    )
    name = models.CharField(max_length=100)
    variable_code = models.CharField(
        max_length=50,
        unique=False,
        null=True,
        blank=True,
        help_text="Immutable code used in formulas (e.g., BASIC_PAY)",
    )
    type = models.CharField(max_length=50, choices=TYPE_CHOICES)
    calc = models.CharField(max_length=50, default="Fixed")
    value = models.DecimalField(max_digits=12, decimal_places=2, default=0.0)

    formula = models.TextField(
        help_text="Evaluated safely via simpleeval", null=True, blank=True
    )
    is_statutory = models.BooleanField(default=False)
    prorate = models.BooleanField(
        default=False, help_text="Multiply result by (present_days / total_days)"
    )

    effective_from = models.DateField()
    effective_to = models.DateField(null=True, blank=True)

    def __str__(self):
        return f"{self.name} ({self.type})"


class RuleDependency(models.Model):
    """Adjacency list for DAG Topological Sorting"""

    from_rule = models.ForeignKey(
        ComponentRule, related_name="outgoing_deps", on_delete=models.CASCADE
    )
    to_rule = models.ForeignKey(
        ComponentRule, related_name="incoming_deps", on_delete=models.CASCADE
    )


class RuleChangeLog(models.Model):
    rule = models.ForeignKey(ComponentRule, on_delete=models.CASCADE)
    changed_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True
    )
    changed_at = models.DateTimeField(auto_now_add=True)
    reason = models.TextField()


class TaxRegimeSlab(models.Model):
    REGIME_CHOICES = (("Old", "Old"), ("New", "New"))
    regime = models.CharField(max_length=10, choices=REGIME_CHOICES)
    effective_from = models.DateField()
    effective_to = models.DateField(null=True, blank=True)
    min_income = models.DecimalField(max_digits=12, decimal_places=2)
    max_income = models.DecimalField(
        max_digits=12, decimal_places=2, null=True, blank=True
    )
    tax_rate = models.DecimalField(max_digits=5, decimal_places=2)


# ==========================================
# EXECUTION & IMMUTABILITY
# ==========================================


class PayrollRun(models.Model):
    STATUS_CHOICES = (
        ("Draft", "Draft"),
        ("Processing", "Processing"),
        ("Maker-Submitted", "Maker-Submitted"),
        ("Checker-Approved", "Checker-Approved"),
        ("Frozen", "Frozen"),
        ("Disbursed", "Disbursed"),
        ("Rejected", "Rejected"),
    )
    RUN_TYPE = (("Live", "Live"), ("Simulation", "Simulation"))

    period = models.CharField(max_length=7, help_text="YYYY-MM")
    entity = models.ForeignKey(
        Entity, on_delete=models.CASCADE, related_name="payroll_runs"
    )
    run_type = models.CharField(max_length=20, choices=RUN_TYPE, default="Live")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="Draft")

    maker = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="made_runs",
        null=True,
        on_delete=models.SET_NULL,
    )
    checker = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="checked_runs",
        null=True,
        on_delete=models.SET_NULL,
    )
    lock_date = models.DateField(null=True, blank=True)
    remarks = models.TextField(
        blank=True, default="", help_text="Mandatory execution remarks"
    )
    approval_remarks = models.TextField(
        blank=True, default="", help_text="Mandatory approval remarks"
    )


class PayrollRunComment(models.Model):
    run = models.ForeignKey(
        PayrollRun, on_delete=models.CASCADE, related_name="comments"
    )
    author = models.ForeignKey(
        settings.AUTH_USER_MODEL, null=True, on_delete=models.SET_NULL
    )
    comment = models.TextField()
    timestamp = models.DateTimeField(auto_now_add=True)


class Payslip(models.Model):
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE)
    run = models.ForeignKey(PayrollRun, on_delete=models.CASCADE)
    period = models.CharField(max_length=7)

    gross = models.DecimalField(max_digits=12, decimal_places=2, default=0.0)
    deductions = models.DecimalField(max_digits=12, decimal_places=2, default=0.0)
    net = models.DecimalField(max_digits=12, decimal_places=2, default=0.0)

    # Attendance & Proration Snapshot fields
    days_present = models.DecimalField(max_digits=6, decimal_places=2, default=0.0)
    days_paid = models.DecimalField(max_digits=6, decimal_places=2, default=0.0)
    total_days = models.DecimalField(max_digits=6, decimal_places=2, default=30.0)
    lop_days = models.DecimalField(max_digits=6, decimal_places=2, default=0.0)
    half_days = models.DecimalField(max_digits=6, decimal_places=2, default=0.0)
    late_penalty_days = models.DecimalField(max_digits=6, decimal_places=2, default=0.0)
    ot_hours = models.DecimalField(max_digits=6, decimal_places=2, default=0.0)
    annual_leaves = models.DecimalField(max_digits=6, decimal_places=2, default=0.0)
    attendance_snapshot = models.JSONField(default=dict, blank=True)

    class Meta:
        unique_together = ("employee", "period", "run")

    @property
    def tds(self):
        line = self.lines.filter(
            models.Q(rule__name__icontains="TDS")
            | models.Q(rule__name__icontains="Income Tax")
        ).first()
        return line.amount if line else Decimal("0.00")


class PayslipLineItem(models.Model):
    payslip = models.ForeignKey(Payslip, on_delete=models.CASCADE, related_name="lines")
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

    days_present = models.DecimalField(max_digits=6, decimal_places=2, default=0.0)
    days_paid = models.DecimalField(max_digits=6, decimal_places=2, default=0.0)
    total_days = models.DecimalField(max_digits=6, decimal_places=2, default=30.0)
    lop_days = models.DecimalField(max_digits=6, decimal_places=2, default=0.0)
    half_days = models.DecimalField(max_digits=6, decimal_places=2, default=0.0)
    late_penalty_days = models.DecimalField(max_digits=6, decimal_places=2, default=0.0)
    ot_hours = models.DecimalField(max_digits=6, decimal_places=2, default=0.0)
    annual_leaves = models.DecimalField(max_digits=6, decimal_places=2, default=0.0)
    attendance_snapshot = models.JSONField(default=dict, blank=True)


class SimulatedLineItem(models.Model):
    payslip = models.ForeignKey(
        SimulatedPayslip, on_delete=models.CASCADE, related_name="lines"
    )
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
    original_payslip = models.ForeignKey(
        Payslip, on_delete=models.CASCADE, related_name="retros"
    )
    target_run = models.ForeignKey(
        PayrollRun, on_delete=models.CASCADE, related_name="retro_merges"
    )
    diff_amount = models.DecimalField(max_digits=12, decimal_places=2)
    approved_for_merge = models.BooleanField(default=False)
    maker = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="made_retros",
        null=True,
        on_delete=models.SET_NULL,
    )
    checker = models.ForeignKey(
        settings.AUTH_USER_MODEL,
        related_name="checked_retros",
        null=True,
        on_delete=models.SET_NULL,
    )


# ==========================================
# STATUTORY & LEGACY
# ==========================================


class StatutoryRegister(models.Model):
    run = models.ForeignKey(PayrollRun, on_delete=models.CASCADE)
    type = models.CharField(max_length=50)  # PF, ESIC, PT, TDS
    generated_at = models.DateTimeField(auto_now_add=True)
    payload = models.JSONField()


class Loan(models.Model):
    STATUS_CHOICES = (
        ("Active", "Active"),
        ("Closed", "Closed"),
        ("Pending", "Pending"),
    )
    employee = models.ForeignKey(
        Employee, on_delete=models.CASCADE, related_name="loans"
    )
    type = models.CharField(max_length=50)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    emi = models.DecimalField(max_digits=10, decimal_places=2)
    tenure = models.IntegerField(help_text="In months")
    outstanding = models.DecimalField(max_digits=10, decimal_places=2)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="Pending")

    # Enhanced Lifecycle & Moratorium tracking
    start_period = models.CharField(
        max_length=20, default="", blank=True, help_text="e.g. 2026-04"
    )
    disbursement_date = models.DateField(null=True, blank=True)
    reason = models.TextField(blank=True, default="")
    moratorium_count = models.PositiveIntegerField(
        default=0, help_text="Times EMI was skipped"
    )
    approved_by = models.ForeignKey(
        Employee,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="approved_loans",
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True, null=True, blank=True)

    @property
    def installments_paid_count(self):
        return self.installments.filter(status="DEBITED").count()

    @property
    def installments_remaining_count(self):
        c = self.installments.filter(status="PENDING").count()
        if c == 0 and self.installments.count() == 0:
            return max(0, self.tenure - self.installments_paid_count)
        return c

    @property
    def total_amount_paid(self):
        from django.db.models import Sum

        val = self.installments.filter(status="DEBITED").aggregate(
            total=Sum("paid_amount")
        )["total"]
        return val or Decimal("0.00")

    def generate_schedule(self, start_period=None):
        """
        Generates or initializes standard monthly installments for the loan.
        """
        import datetime
        import calendar
        from decimal import Decimal
        from django.utils import timezone

        if not start_period:
            start_period = self.start_period
        if not start_period:
            now = timezone.now()
            start_period = now.strftime("%Y-%m")

        self.start_period = start_period
        self.save(update_fields=["start_period"])

        # If installments already exist, don't overwrite if any have been debited
        existing = self.installments.all()
        if existing.filter(status="DEBITED").exists():
            return

        existing.delete()

        parts = start_period.split("-")
        year = int(parts[0])
        month = int(parts[1])

        remaining_bal = self.amount
        monthly_emi = self.emi
        tenure = self.tenure

        installments = []
        for i in range(1, tenure + 1):
            cur_month = ((month - 1 + (i - 1)) % 12) + 1
            cur_year = year + ((month - 1 + (i - 1)) // 12)
            period_str = f"{cur_year:04d}-{cur_month:02d}"

            last_day = calendar.monthrange(cur_year, cur_month)[1]
            due_date = datetime.date(cur_year, cur_month, min(last_day, 28))

            if i == tenure:
                actual_emi = remaining_bal
            else:
                actual_emi = min(monthly_emi, remaining_bal)

            remaining_bal = max(Decimal("0.00"), remaining_bal - actual_emi)

            inst = LoanInstallment(
                loan=self,
                installment_number=i,
                period=period_str,
                due_date=due_date,
                emi_amount=actual_emi,
                principal_amount=actual_emi,
                paid_amount=Decimal("0.00"),
                balance_after=remaining_bal,
                status="PENDING",
            )
            installments.append(inst)

        LoanInstallment.objects.bulk_create(installments)


class LoanInstallment(models.Model):
    STATUS_CHOICES = (
        ("PENDING", "Pending Payroll Deduction"),
        ("DEBITED", "Debited in Payroll"),
        ("SKIPPED", "Skipped / Deferred by Management"),
        ("WAIVED", "Waived / Pardoned"),
    )
    STRATEGY_CHOICES = (
        ("NONE", "None"),
        ("EXTEND_TENURE", "Extend Loan Tenure (+1 Month)"),
        ("ADJUST_NEXT_MONTH", "Adjust in Next Month (Double EMI)"),
    )

    loan = models.ForeignKey(
        Loan, on_delete=models.CASCADE, related_name="installments"
    )
    installment_number = models.PositiveIntegerField()
    period = models.CharField(max_length=20, help_text="e.g. 2026-04")
    due_date = models.DateField()
    emi_amount = models.DecimalField(max_digits=10, decimal_places=2)
    principal_amount = models.DecimalField(
        max_digits=10, decimal_places=2, default=Decimal("0.00")
    )
    paid_amount = models.DecimalField(
        max_digits=10, decimal_places=2, default=Decimal("0.00")
    )
    balance_after = models.DecimalField(
        max_digits=10, decimal_places=2, default=Decimal("0.00")
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="PENDING")

    # Deduction Tracking
    debited_in_run = models.ForeignKey(
        "payroll.PayrollRun",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="debited_loan_installments",
    )
    debited_in_payslip = models.ForeignKey(
        "payroll.Payslip",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="loan_installments",
    )
    debited_at = models.DateTimeField(null=True, blank=True)

    # Management Skip & Moratorium Metadata
    skip_strategy = models.CharField(
        max_length=30, choices=STRATEGY_CHOICES, default="NONE"
    )
    skip_reason = models.TextField(blank=True, default="")
    skipped_by = models.ForeignKey(
        Employee,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="skipped_loan_installments",
    )
    skipped_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["installment_number"]
        unique_together = ("loan", "installment_number")


class EmiReliefRequest(models.Model):
    STATUS_CHOICES = (
        ("PENDING", "Pending CEO Decision"),
        ("APPROVED", "Approved & Moratorium Granted"),
        ("REJECTED", "Rejected"),
    )
    PREFERRED_STRATEGY_CHOICES = (
        ("EXTEND_TENURE", "Extend Loan Tenure (+1 Month)"),
        ("ADJUST_NEXT_MONTH", "Adjust in Next Month (Double EMI)"),
        ("EITHER", "Either Strategy (CEO Discretion)"),
    )

    loan = models.ForeignKey(
        Loan, on_delete=models.CASCADE, related_name="relief_requests"
    )
    installment = models.ForeignKey(
        LoanInstallment,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="relief_requests",
    )
    employee = models.ForeignKey(
        Employee, on_delete=models.CASCADE, related_name="loan_relief_requests"
    )
    reason = models.TextField(help_text="Reason for employee relief request")
    preferred_strategy = models.CharField(
        max_length=30, choices=PREFERRED_STRATEGY_CHOICES, default="EITHER"
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="PENDING")

    # CEO Action Tracking
    applied_strategy = models.CharField(max_length=30, blank=True, default="")
    decision_remarks = models.TextField(blank=True, default="")
    decided_by = models.ForeignKey(
        Employee,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="decided_loan_relief_requests",
    )
    decided_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True, null=True, blank=True)

    class Meta:
        ordering = ["-created_at"]


class SalaryAdvance(models.Model):
    STATUS_CHOICES = (
        ("Pending", "Pending Approval"),
        ("Approved", "Approved"),
        ("Disbursed", "Disbursed"),
        ("Recovered", "Recovered"),
        ("Rejected", "Rejected"),
        ("Cancelled", "Cancelled"),
    )
    employee = models.ForeignKey(
        Employee, on_delete=models.CASCADE, related_name="salary_advances"
    )
    amount = models.DecimalField(
        max_digits=10, decimal_places=2, help_text="Requested advance amount"
    )
    tenure = models.PositiveIntegerField(
        default=1, help_text="Repayment tenure in months (1 to 3)"
    )
    monthly_installment = models.DecimalField(
        max_digits=10, decimal_places=2, default=Decimal("0.00")
    )
    outstanding = models.DecimalField(
        max_digits=10, decimal_places=2, default=Decimal("0.00")
    )
    start_period = models.CharField(
        max_length=20, default="", blank=True, help_text="e.g. 2026-12"
    )
    reason = models.TextField(blank=True, default="")
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="Pending")

    # Approval & Disbursement
    approved_by = models.ForeignKey(
        Employee,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="approved_salary_advances",
    )
    approved_at = models.DateTimeField(null=True, blank=True)
    disbursement_date = models.DateField(null=True, blank=True)
    disbursement_mode = models.CharField(
        max_length=50, default="Bank Transfer", blank=True
    )
    disbursement_ref = models.CharField(max_length=100, default="", blank=True)

    created_at = models.DateTimeField(auto_now_add=True, null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True, null=True, blank=True)

    @property
    def installments_recovered_count(self):
        return self.installments.filter(status="RECOVERED").count()

    @property
    def installments_pending_count(self):
        return self.installments.filter(status="PENDING").count()

    @property
    def total_amount_recovered(self):
        from django.db.models import Sum

        val = self.installments.filter(status="RECOVERED").aggregate(
            total=Sum("recovered_amount")
        )["total"]
        return val or Decimal("0.00")

    def generate_schedule(self, start_period=None):
        """
        Generates or initializes monthly recovery installments for the salary advance.
        """
        import datetime
        import calendar
        from decimal import Decimal
        from django.utils import timezone

        if not start_period:
            start_period = self.start_period
        if not start_period:
            now = timezone.now()
            start_period = now.strftime("%Y-%m")

        self.start_period = start_period
        self.save(update_fields=["start_period"])

        # If installments already recovered, do not overwrite
        existing = self.installments.all()
        if existing.filter(status="RECOVERED").exists():
            return

        existing.delete()

        parts = start_period.split("-")
        year = int(parts[0])
        month = int(parts[1])

        tenure = max(1, self.tenure)
        base_installment = (self.amount / Decimal(str(tenure))).quantize(
            Decimal("0.01"), rounding=decimal.ROUND_DOWN
        )
        remainder = (self.amount - (base_installment * Decimal(str(tenure)))).quantize(
            Decimal("0.01")
        )

        remaining_bal = self.amount
        installments = []

        for i in range(1, tenure + 1):
            cur_month = ((month - 1 + (i - 1)) % 12) + 1
            cur_year = year + ((month - 1 + (i - 1)) // 12)
            p_str = f"{cur_year:04d}-{cur_month:02d}"

            _, last_day = calendar.monthrange(cur_year, cur_month)
            due_d = datetime.date(cur_year, cur_month, last_day)

            # Add any rounding remainder to the first installment
            inst_amount = base_installment + (remainder if i == 1 else Decimal("0.00"))
            remaining_bal = max(Decimal("0.00"), remaining_bal - inst_amount)

            inst = SalaryAdvanceInstallment(
                advance=self,
                installment_number=i,
                period=p_str,
                due_date=due_d,
                amount=inst_amount,
                balance_after=remaining_bal,
                status="PENDING",
            )
            installments.append(inst)

        SalaryAdvanceInstallment.objects.bulk_create(installments)


class SalaryAdvanceInstallment(models.Model):
    STATUS_CHOICES = (
        ("PENDING", "Pending Payroll Deduction"),
        ("RECOVERED", "Recovered in Payroll"),
        ("SKIPPED", "Skipped by Management"),
        ("WAIVED", "Waived"),
    )
    advance = models.ForeignKey(
        SalaryAdvance, on_delete=models.CASCADE, related_name="installments"
    )
    installment_number = models.PositiveIntegerField()
    period = models.CharField(max_length=20, help_text="e.g. 2026-12")
    due_date = models.DateField()
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    recovered_amount = models.DecimalField(
        max_digits=10, decimal_places=2, default=Decimal("0.00")
    )
    balance_after = models.DecimalField(
        max_digits=10, decimal_places=2, default=Decimal("0.00")
    )
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="PENDING")

    # Deduction Tracking
    debited_in_run = models.ForeignKey(
        "payroll.PayrollRun",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="debited_advance_installments",
    )
    debited_in_payslip = models.ForeignKey(
        "payroll.Payslip",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="advance_installments",
    )
    debited_at = models.DateTimeField(null=True, blank=True)

    # Management Skip metadata
    skip_reason = models.TextField(blank=True, default="")
    skipped_by = models.ForeignKey(
        Employee,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="skipped_advance_installments",
    )
    skipped_at = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["installment_number"]
        unique_together = ("advance", "installment_number")


class Reimbursement(models.Model):
    STATUS_CHOICES = (
        ("Pending", "Pending"),
        ("Approved", "Approved"),
        ("Rejected", "Rejected"),
        ("Paid", "Paid"),
    )
    employee = models.ForeignKey(
        Employee, on_delete=models.CASCADE, related_name="reimbursements"
    )
    category = models.CharField(max_length=50)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    date = models.DateField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="Pending")
    receipt = models.FileField(
        upload_to="reimbursements/receipts/", null=True, blank=True
    )


class ComplianceReport(models.Model):
    site = models.ForeignKey(
        "organisation.Site",
        on_delete=models.CASCADE,
        related_name="compliance_reports",
        null=True,
        blank=True,
    )
    STATUS_CHOICES = (
        ("Draft", "Draft"),
        ("Pending", "Pending"),
        ("Generated", "Generated"),
        ("Filed", "Filed"),
    )
    CATEGORY_CHOICES = (
        ("Provident Fund", "Provident Fund"),
        ("ESI", "ESI"),
        ("Professional Tax", "Professional Tax"),
        ("TDS", "TDS"),
    )
    category = models.CharField(
        max_length=50, choices=CATEGORY_CHOICES, default="Provident Fund"
    )
    key = models.CharField(max_length=100)
    desc = models.CharField(max_length=255)
    period = models.CharField(max_length=20, default="October 2026")
    amount = models.DecimalField(max_digits=12, decimal_places=2, default=0)
    challan_number = models.CharField(max_length=100, blank=True, null=True)
    due = models.DateField()
    filed_on = models.DateField(blank=True, null=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="Draft")


# ==========================================
# TAX & FORM 16
# ==========================================


class Form16Document(models.Model):
    STATUS_CHOICES = (
        ("Pending", "Pending"),
        ("Distributed", "Distributed"),
        ("Failed", "Failed"),
    )
    employee = models.ForeignKey(
        Employee, on_delete=models.CASCADE, related_name="form16_documents"
    )
    financial_year = models.CharField(max_length=20)
    version = models.IntegerField(default=1)
    file = models.FileField(upload_to="form16_documents/")
    uploaded_by = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True
    )
    uploaded_at = models.DateTimeField(auto_now_add=True)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="Pending")

    class Meta:
        unique_together = ("employee", "financial_year", "version")


# ==========================================
# EMPLOYEE WALLET & SECURITY DEPOSIT SYSTEM
# ==========================================


class WalletPolicy(models.Model):
    BASIS_CHOICES = (
        ("GROSS", "Percentage of Monthly Gross Salary"),
        ("BASIC", "Percentage of Basic Salary"),
        ("FIXED", "Fixed Monthly Amount (₹)"),
    )
    site = models.OneToOneField(
        "organisation.Site",
        on_delete=models.CASCADE,
        related_name="wallet_policy",
        null=True,
        blank=True,
    )
    entity = models.OneToOneField(
        "organisation.Entity",
        on_delete=models.CASCADE,
        related_name="default_wallet_policy",
        null=True,
        blank=True,
    )
    organization = models.ForeignKey(
        "admin_org.Organization",
        on_delete=models.CASCADE,
        related_name="wallet_policies",
        null=True,
        blank=True,
    )
    is_enabled = models.BooleanField(default=False)
    deduction_basis = models.CharField(
        max_length=10, choices=BASIS_CHOICES, default="GROSS"
    )
    deduction_rate = models.DecimalField(
        max_digits=7, decimal_places=2, default=10.00, help_text="e.g. 10.00 for 10%"
    )
    target_ceiling = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        default=30000.00,
        help_text="Maximum accumulated deposit limit (e.g. ₹30,000)",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        target = (
            f"Site: {self.site.name}"
            if self.site
            else f"Org: {self.organization.name}" if self.organization else "Global"
        )
        return f"Wallet Policy ({target}) - {self.deduction_rate}% up to ₹{self.target_ceiling}"


class EmployeeWallet(models.Model):
    employee = models.OneToOneField(
        Employee, on_delete=models.CASCADE, related_name="wallet"
    )
    is_active = models.BooleanField(
        default=True,
        help_text="Toggle wallet deposit deduction on/off for this employee",
    )
    current_balance = models.DecimalField(max_digits=12, decimal_places=2, default=0.00)
    custom_target_ceiling = models.DecimalField(
        max_digits=12,
        decimal_places=2,
        null=True,
        blank=True,
        help_text="Overrides policy ceiling if set",
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    @property
    def effective_ceiling(self):
        if self.custom_target_ceiling is not None:
            return self.custom_target_ceiling
        policy = getattr(self.employee.site, "wallet_policy", None) or getattr(
            self.employee.entity, "default_wallet_policy", None
        )
        return policy.target_ceiling if policy else Decimal("30000.00")

    def __str__(self):
        return f"Wallet: {self.employee} - Balance: ₹{self.current_balance} / Limit: ₹{self.effective_ceiling}"


class WalletLedgerEntry(models.Model):
    TXN_TYPES = (
        ("SALARY_DEDUCTION", "Salary Deduction Credit"),
        ("REFUND", "Security Deposit Refund Debit"),
        ("MANUAL_ADJUSTMENT", "Manual Adjustment"),
    )
    wallet = models.ForeignKey(
        EmployeeWallet, on_delete=models.CASCADE, related_name="transactions"
    )
    payroll_run = models.ForeignKey(
        "PayrollRun",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="wallet_transactions",
    )
    period = models.CharField(max_length=7, help_text="YYYY-MM")
    transaction_type = models.CharField(
        max_length=20, choices=TXN_TYPES, default="SALARY_DEDUCTION"
    )
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    balance_after = models.DecimalField(max_digits=12, decimal_places=2)
    notes = models.CharField(max_length=255, blank=True, null=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-created_at"]

    def __str__(self):
        return f"{self.period} - {self.transaction_type}: {self.amount} (Balance: {self.balance_after})"


# ==========================================
# DISCIPLINARY MEMOS & PENALTIES
# ==========================================


class DisciplinaryInfractionCategory(models.Model):
    entity = models.ForeignKey(
        Entity,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="disciplinary_categories",
    )
    organization = models.ForeignKey(
        "admin_org.Organization",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="disciplinary_categories",
    )
    name = models.CharField(max_length=150)
    code = models.CharField(max_length=50, blank=True)
    description = models.TextField(blank=True, null=True)
    default_penalty_amount = models.DecimalField(
        max_digits=10, decimal_places=2, default=Decimal("500.00")
    )
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]
        verbose_name = "Disciplinary Infraction Category"
        verbose_name_plural = "Disciplinary Infraction Categories"

    def __str__(self):
        return f"{self.name} (Default: ₹{self.default_penalty_amount})"


class EmployeeDisciplinaryMemo(models.Model):
    STATUS_CHOICES = (
        ("PENDING", "Pending Payroll Deduction"),
        ("DEDUCTED", "Deducted in Payroll"),
        ("WAIVED", "Waived / Pardoned"),
        ("CANCELLED", "Cancelled"),
    )

    employee = models.ForeignKey(
        Employee, on_delete=models.CASCADE, related_name="disciplinary_memos"
    )
    issued_by = models.ForeignKey(
        Employee,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="issued_disciplinary_memos",
    )
    category = models.ForeignKey(
        DisciplinaryInfractionCategory,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="memos",
    )
    is_custom_reason = models.BooleanField(default=False)
    infraction_reason = models.CharField(max_length=255)
    description = models.TextField(blank=True, null=True)
    amount = models.DecimalField(max_digits=10, decimal_places=2)
    incident_date = models.DateField()
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="PENDING")
    is_active = models.BooleanField(
        default=True, help_text="True while pending payroll deduction"
    )
    payroll_run = models.ForeignKey(
        "PayrollRun",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="disciplinary_memos",
    )
    payslip = models.ForeignKey(
        "Payslip",
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name="disciplinary_memos",
    )
    deducted_at = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["-incident_date", "-created_at"]

    def __str__(self):
        return f"Memo #{self.id}: {self.employee} - {self.infraction_reason} (₹{self.amount}) [{self.status}]"
