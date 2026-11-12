from django.db import models
from django.utils import timezone
from admin_org.models import Organization


class Entity(models.Model):
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='entities', null=True, blank=True)
    name = models.CharField(max_length=100)
    code = models.CharField(max_length=50, blank=True, null=True)
    country = models.CharField(max_length=50, default='India')
    currency = models.CharField(max_length=10, default='INR')
    gstin = models.CharField(max_length=50, blank=True, null=True)
    status = models.CharField(max_length=20, default='Active')
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return self.name

class Branch(models.Model):
    name = models.CharField(max_length=100)
    entity = models.ForeignKey(Entity, on_delete=models.CASCADE, related_name='branches')
    code = models.CharField(max_length=50, blank=True, null=True)
    city = models.CharField(max_length=100, blank=True, null=True)
    state = models.CharField(max_length=100, blank=True, null=True)
    head = models.CharField(max_length=100, blank=True, null=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.name} ({self.entity.name})"

class Site(models.Model):
    name = models.CharField(max_length=100)
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='sites', null=True, blank=True)
    branch = models.ForeignKey(Branch, on_delete=models.CASCADE, related_name='sites', null=True, blank=True)
    site_code = models.CharField(max_length=50, blank=True, null=True)
    product_type = models.CharField(max_length=50, blank=True, null=True)
    country = models.CharField(max_length=50, blank=True, null=True)
    status = models.CharField(max_length=20, default='Active')
    activate_date = models.DateField(null=True, blank=True)
    
    # Contact Info
    contact_name = models.CharField(max_length=100, blank=True, null=True)
    contact_phone = models.CharField(max_length=20, blank=True, null=True)
    contact_email = models.EmailField(blank=True, null=True)
    
    # Modules
    modules = models.JSONField(default=list, blank=True, null=True)

    address = models.TextField(blank=True, null=True)
    latitude = models.FloatField(blank=True, null=True)
    longitude = models.FloatField(blank=True, null=True)
    radius = models.IntegerField(default=150)
    qr_enabled = models.BooleanField(default=True)
    face_enabled = models.BooleanField(default=True)
    is_saturday_working = models.BooleanField(default=False)
    is_sub_site = models.BooleanField(default=False)
    parent_site = models.ForeignKey('self', on_delete=models.CASCADE, related_name='sub_sites', null=True, blank=True, help_text="The main client site this sub-site belongs to")
    
    # Tablet Attendance Kiosk Configuration (Dynamic Per-Site)
    kiosk_enabled = models.BooleanField(default=False)
    kiosk_similarity_threshold = models.FloatField(default=0.45, help_text="Facial similarity threshold (0.40 - 0.70)")
    kiosk_cooldown_seconds = models.IntegerField(default=30, help_text="Debounce seconds to prevent duplicate punches")
    kiosk_auto_punch = models.BooleanField(default=True, help_text="Auto-detect IN vs OUT based on previous punch")
    kiosk_token = models.CharField(max_length=64, blank=True, null=True, unique=True, help_text="Secure terminal key for physical tablet")
    kiosk_pin = models.CharField(max_length=10, default='1234', help_text="4-digit PIN to exit kiosk mode on tablet")
    
    # Branding for Site
    logo = models.ImageField(upload_to='site_logos/', null=True, blank=True)
    branding_text = models.CharField(max_length=100, default='PeoplePulse HRMS', blank=True, null=True)
    
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return self.name

class Department(models.Model):
    name = models.CharField(max_length=100)
    entity = models.ForeignKey(Entity, on_delete=models.CASCADE, related_name='departments', null=True, blank=True)
    code = models.CharField(max_length=50, blank=True, null=True)
    head = models.CharField(max_length=100, blank=True, null=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return self.name

class Designation(models.Model):
    title = models.CharField(max_length=100)
    department = models.ForeignKey(Department, on_delete=models.CASCADE, related_name='designations', null=True, blank=True)
    grade = models.CharField(max_length=50, blank=True, null=True)
    created_at = models.DateTimeField(default=timezone.now)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return self.title

class AttendancePolicy(models.Model):
    employee = models.OneToOneField('employees.Employee', on_delete=models.CASCADE, related_name='attendance_policy', null=True, blank=True)
    site = models.OneToOneField(Site, on_delete=models.CASCADE, related_name='attendance_policy', null=True, blank=True)
    organization = models.OneToOneField(Entity, on_delete=models.CASCADE, related_name='default_attendance_policy', null=True, blank=True)
    
    # Policy rules
    max_late_minutes = models.IntegerField(default=15)
    half_day_hours = models.DecimalField(max_digits=4, decimal_places=2, default=4.00)
    full_day_hours = models.DecimalField(max_digits=4, decimal_places=2, default=8.00)
    ot_applicable_after_hours = models.DecimalField(max_digits=4, decimal_places=2, default=2.0)
    
    require_face = models.BooleanField(default=True)
    face_match_threshold = models.DecimalField(max_digits=5, decimal_places=2, default=95.00, help_text="Strict accuracy percentage required for face verification")
    require_qr = models.BooleanField(default=True)
    require_gps = models.BooleanField(default=True)
    wfh_employees = models.ManyToManyField('employees.Employee', related_name='wfh_policies', blank=True, help_text="Employees granted Work From Home privileges to bypass geofence.")

    def __str__(self):
        if self.employee:
            return f"Policy for Employee: {self.employee.user.username if self.employee.user else self.employee.id}"
        if self.site:
            return f"Policy for Site: {self.site.name}"
        if self.organization:
            return f"Default Policy for Org: {self.organization.name}"
        return "Global Attendance Policy"


class PunctualitySlab(models.Model):
    COMPARISON_CHOICES = (
        ('AFTER_MANDATORY_PRIOR', 'After Mandatory Prior Mark (Before Shift Start)'),
        ('AFTER_SHIFT_START', 'After Exact Shift Start Time'),
        ('AFTER_GRACE_MINUTES', 'After Grace Period Past Shift Start'),
    )
    DEDUCTION_TYPE_CHOICES = (
        ('FIXED_AMOUNT', 'Fixed Monetary Amount (₹)'),
        ('HALF_DAY', 'Half Day Salary Deduction'),
        ('PERCENTAGE', 'Percentage of Daily Wage (%)'),
    )

    policy = models.ForeignKey(AttendancePolicy, on_delete=models.CASCADE, related_name='punctuality_slabs')
    name = models.CharField(max_length=100, help_text="e.g. Late Reporting (15m Prior), Post-Shift Start")
    applicable_designations = models.ManyToManyField(
        Designation, blank=True,
        help_text="Designations subject to this slab (e.g. Trainers). Empty applies to all."
    )
    applicable_roles = models.ManyToManyField(
        'Role', blank=True, related_name='punctuality_slabs',
        help_text="Dynamic roles subject to this slab. Empty applies to all."
    )
    comparison_type = models.CharField(max_length=30, choices=COMPARISON_CHOICES)
    minutes_threshold = models.IntegerField(
        default=0,
        help_text="Minutes relative to shift start or prior arrival mark"
    )
    deduction_type = models.CharField(max_length=20, choices=DEDUCTION_TYPE_CHOICES, default='FIXED_AMOUNT')
    deduction_value = models.DecimalField(
        max_digits=10, decimal_places=2, default=0.00,
        help_text="₹ amount if FIXED_AMOUNT, or percentage if PERCENTAGE, or 0.5 for HALF_DAY"
    )
    order = models.IntegerField(default=1, help_text="Evaluation priority order")

    class Meta:
        ordering = ['order', 'minutes_threshold']

    def __str__(self):
        return f"{self.name} ({self.get_deduction_type_display()} - {self.deduction_value})"


class PunctualityPenaltyLog(models.Model):
    daily_attendance = models.ForeignKey('attendance.DailyAttendance', on_delete=models.CASCADE, related_name='punctuality_logs')
    slab = models.ForeignKey(PunctualitySlab, on_delete=models.SET_NULL, null=True, blank=True)
    penalty_amount = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    penalty_type = models.CharField(max_length=50)
    punch_time = models.DateTimeField()
    shift_start = models.DateTimeField(null=True, blank=True)
    minutes_late = models.IntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"Penalty {self.penalty_amount} for {self.daily_attendance.employee}"

class Role(models.Model):
    name = models.CharField(max_length=100)
    code = models.CharField(max_length=50, unique=True)
    organization = models.ForeignKey('admin_org.Organization', on_delete=models.CASCADE, null=True, blank=True, related_name='roles')
    site = models.ForeignKey('Site', on_delete=models.CASCADE, null=True, blank=True, related_name='roles')
    department = models.ForeignKey(Department, on_delete=models.SET_NULL, null=True, blank=True, related_name='roles')
    access_scope = models.CharField(max_length=50, default='Self') # Corporate, Region, Site, Self
    dashboard_type = models.CharField(max_length=50, blank=True, null=True)
    can_manage_users = models.BooleanField(default=False)
    can_approve = models.BooleanField(default=False)
    cross_department_access = models.BooleanField(default=False)
    status = models.CharField(max_length=20, default='Active')
    hierarchy_level = models.CharField(max_length=20, blank=True, null=True)
    reporting_to = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True, related_name='subordinate_roles')
    permissions = models.JSONField(default=dict, blank=True, null=True)
    
    def __str__(self):
        return f"{self.name} ({self.code})"
