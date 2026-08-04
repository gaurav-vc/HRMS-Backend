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
    require_qr = models.BooleanField(default=True)
    require_gps = models.BooleanField(default=True)

    def __str__(self):
        if self.employee:
            return f"Policy for Employee: {self.employee.user.username if self.employee.user else self.employee.id}"
        if self.site:
            return f"Policy for Site: {self.site.name}"
        if self.organization:
            return f"Default Policy for Org: {self.organization.name}"
        return "Global Attendance Policy"

class Role(models.Model):
    name = models.CharField(max_length=100)
    code = models.CharField(max_length=50, unique=True)
    organization = models.ForeignKey('admin_org.Organization', on_delete=models.CASCADE, null=True, blank=True, related_name='roles')
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
