from django.db import models
from employees.models import Employee
from organisation.models import Entity, Site

class LeavePolicyConfiguration(models.Model):
    tenured_years_threshold = models.IntegerField(default=5, help_text="Years required to be considered tenured")
    tenured_annual_leaves = models.DecimalField(max_digits=5, decimal_places=2, default=15.0)
    standard_annual_leaves = models.DecimalField(max_digits=5, decimal_places=2, default=12.0)
    max_consecutive_leaves = models.IntegerField(default=3, help_text="Max consecutive days allowed without salary deduction")
    exception_month = models.IntegerField(default=3, help_text="Month (1-12) where all accumulated leaves can be taken at once")

    class Meta:
        verbose_name = "Leave Policy Configuration"
        verbose_name_plural = "Leave Policy Configurations"

    def __str__(self):
        return "Global Leave Policy Configuration"

    @classmethod
    def get_settings(cls):
        obj, created = cls.objects.get_or_create(id=1)
        return obj

class LeaveType(models.Model):
    name = models.CharField(max_length=100)
    code = models.CharField(max_length=20, unique=True)
    annual_entitlement = models.DecimalField(max_digits=5, decimal_places=2, default=0.0)
    carry_forward_allowed = models.BooleanField(default=False)
    max_carry_forward = models.DecimalField(max_digits=5, decimal_places=2, default=0.0)
    active = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.name} ({self.code})"

class LeaveBalance(models.Model):
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='leave_balances')
    leave_type = models.ForeignKey(LeaveType, on_delete=models.CASCADE)
    allocated_days = models.DecimalField(max_digits=5, decimal_places=2, default=0.0)
    used_days = models.DecimalField(max_digits=5, decimal_places=2, default=0.0)
    remaining_days = models.DecimalField(max_digits=5, decimal_places=2, default=0.0)
    year = models.IntegerField()

    class Meta:
        unique_together = ('employee', 'leave_type', 'year')

    def __str__(self):
        return f"{self.employee} - {self.leave_type} ({self.year})"

class LeaveRequest(models.Model):
    STATUS_CHOICES = (
        ('Pending', 'Pending'),
        ('Approved', 'Approved'),
        ('Rejected', 'Rejected'),
        ('Cancelled', 'Cancelled'),
    )

    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='leave_requests')
    organization = models.ForeignKey(Entity, on_delete=models.SET_NULL, null=True, blank=True)
    site = models.ForeignKey(Site, on_delete=models.SET_NULL, null=True, blank=True)
    leave_type = models.ForeignKey(LeaveType, on_delete=models.PROTECT)
    
    SUB_TYPE_CHOICES = (
        ('Sick', 'Sick'),
        ('Casual', 'Casual'),
        ('Other', 'Other'),
    )
    sub_type = models.CharField(max_length=50, choices=SUB_TYPE_CHOICES, default='Other')
    
    start_date = models.DateField()
    end_date = models.DateField()
    total_days = models.DecimalField(max_digits=5, decimal_places=2)
    salary_deduction_days = models.DecimalField(max_digits=5, decimal_places=2, default=0.0)
    
    reason = models.TextField()
    attachment = models.FileField(upload_to='leaves/attachments/', null=True, blank=True)
    
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default='Pending')
    manager_comments = models.TextField(null=True, blank=True)
    approved_by = models.CharField(max_length=100, null=True, blank=True)
    approved_at = models.DateTimeField(null=True, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.employee} - {self.leave_type} ({self.start_date} to {self.end_date})"

class Holiday(models.Model):
    name = models.CharField(max_length=100)
    date = models.DateField()
    description = models.TextField(blank=True, null=True)
    site = models.ForeignKey(Site, on_delete=models.CASCADE, null=True, blank=True, help_text="Leave blank if global holiday")
    
    class Meta:
        ordering = ['date']
        unique_together = ('date', 'site')
        
    def __str__(self):
        return f"{self.name} ({self.date})"
