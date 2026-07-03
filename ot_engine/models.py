import hashlib
from django.db import models
from django.conf import settings
from employees.models import Employee
from attendance.models import DailyAttendance
from payroll.models import PayrollRun

# ==========================================
# POLICY & CONFIGURATION MODELS
# ==========================================

class OTPolicy(models.Model):
    name = models.CharField(max_length=100)
    multiplier = models.DecimalField(max_digits=4, decimal_places=2, default=1.0)
    weekend_multiplier = models.DecimalField(max_digits=4, decimal_places=2, default=1.5)
    holiday_multiplier = models.DecimalField(max_digits=4, decimal_places=2, default=2.0)
    
    # Rounding Policy
    ROUNDING_CHOICES = (
        ('1', 'Nearest Minute'),
        ('5', 'Nearest 5 Minutes'),
        ('15', 'Nearest 15 Minutes'),
        ('30', 'Nearest 30 Minutes'),
    )
    rounding_policy = models.CharField(max_length=5, choices=ROUNDING_CHOICES, default='15')
    
    # Breaks
    auto_deduct_break_mins = models.IntegerField(default=0)
    
    effective_from = models.DateField()
    effective_to = models.DateField(null=True, blank=True)

class OTThresholdConfig(models.Model):
    name = models.CharField(max_length=100)
    METHOD_CHOICES = (
        ('STD_DEV', 'Standard Deviation'),
        ('PERCENTILE', 'Percentile'),
        ('FIXED', 'Fixed Cap'),
    )
    method = models.CharField(max_length=20, choices=METHOD_CHOICES, default='STD_DEV')
    window_days = models.IntegerField(default=90, help_text="Historical window for baseline")
    multiplier_sensitivity = models.DecimalField(max_digits=5, decimal_places=2, default=2.0)
    
class OTApprovalRouting(models.Model):
    name = models.CharField(max_length=100)
    min_hours_for_hr = models.DecimalField(max_digits=5, decimal_places=2, default=5.0)
    min_hours_for_finance = models.DecimalField(max_digits=5, decimal_places=2, default=10.0)

# ==========================================
# TRANSACTION MODELS
# ==========================================

class OTRequest(models.Model):
    STATUS_CHOICES = (
        ('Pending', 'Pending'),
        ('Approved', 'Approved'),
        ('Rejected', 'Rejected'),
        ('Flagged', 'Flagged'),
    )
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE)
    attendance = models.OneToOneField(DailyAttendance, on_delete=models.CASCADE)
    requested_hours = models.DecimalField(max_digits=5, decimal_places=2)
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='Pending')
    created_at = models.DateTimeField(auto_now_add=True)

class OTApproval(models.Model):
    LEVEL_CHOICES = (
        ('Manager', 'Manager'),
        ('HR', 'HR'),
        ('Finance', 'Finance'),
    )
    request = models.ForeignKey(OTRequest, on_delete=models.CASCADE, related_name='approvals')
    level = models.CharField(max_length=20, choices=LEVEL_CHOICES)
    approver = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    approved_at = models.DateTimeField(auto_now_add=True)
    comments = models.TextField(blank=True, null=True)

class OTEntry(models.Model):
    request = models.OneToOneField(OTRequest, on_delete=models.CASCADE)
    approved_hours = models.DecimalField(max_digits=5, decimal_places=2)
    multiplier_applied = models.DecimalField(max_digits=4, decimal_places=2)
    converted_to_comp_off = models.BooleanField(default=False)

class RetroOTEntry(models.Model):
    original_entry = models.ForeignKey(OTEntry, on_delete=models.CASCADE, null=True, blank=True)
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE)
    attendance = models.ForeignKey(DailyAttendance, on_delete=models.CASCADE)
    adjusted_hours = models.DecimalField(max_digits=5, decimal_places=2)
    target_payroll_run = models.ForeignKey(PayrollRun, on_delete=models.CASCADE)
    reason = models.TextField()

class OTPayrollEntry(models.Model):
    ot_entry = models.OneToOneField(OTEntry, on_delete=models.CASCADE, null=True, blank=True)
    retro_entry = models.OneToOneField(RetroOTEntry, on_delete=models.CASCADE, null=True, blank=True)
    payroll_run = models.ForeignKey(PayrollRun, on_delete=models.CASCADE)
    calculated_amount = models.DecimalField(max_digits=10, decimal_places=2)

# ==========================================
# COMP-OFF MODELS
# ==========================================

class CompOffBalance(models.Model):
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE)
    available_days = models.DecimalField(max_digits=5, decimal_places=2, default=0.0)

class CompOffTransaction(models.Model):
    TYPE_CHOICES = (
        ('Credit', 'Credit'),
        ('Debit', 'Debit'),
        ('Lapse', 'Lapse'),
        ('Encash', 'Encash'),
    )
    balance = models.ForeignKey(CompOffBalance, on_delete=models.CASCADE, related_name='transactions')
    ot_entry = models.ForeignKey(OTEntry, on_delete=models.SET_NULL, null=True, blank=True)
    transaction_type = models.CharField(max_length=10, choices=TYPE_CHOICES)
    days = models.DecimalField(max_digits=5, decimal_places=2)
    expiry_date = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)

# ==========================================
# AUDIT LOG
# ==========================================

class OTAuditLog(models.Model):
    entity_type = models.CharField(max_length=50, help_text="e.g. OTRequest, OTPolicy")
    entity_id = models.IntegerField()
    action = models.CharField(max_length=50)
    actor = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    timestamp = models.DateTimeField(auto_now_add=True)
    hash_signature = models.CharField(max_length=64, help_text="SHA-256 chaining for immutability")

    def save(self, *args, **kwargs):
        if not self.hash_signature:
            last_audit = OTAuditLog.objects.order_by('-id').first()
            previous_hash = last_audit.hash_signature if last_audit else "GENESIS_BLOCK"
            payload = f"{self.entity_type}|{self.entity_id}|{self.action}|{self.actor_id}|{previous_hash}"
            self.hash_signature = hashlib.sha256(payload.encode('utf-8')).hexdigest()
        super().save(*args, **kwargs)
