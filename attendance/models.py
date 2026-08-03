from django.db import models
from employees.models import Employee
from organisation.models import Site, Entity, Role, Department, Branch
import uuid
from django.db.models.signals import post_save
from django.dispatch import receiver
class DailyAttendance(models.Model):
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='attendances')
    site = models.ForeignKey(Site, on_delete=models.SET_NULL, null=True, blank=True)
    organization = models.ForeignKey(Entity, on_delete=models.SET_NULL, null=True, blank=True)
    
    attendance_date = models.DateField()
    first_check_in = models.DateTimeField(null=True, blank=True)
    last_check_out = models.DateTimeField(null=True, blank=True)
    
    total_work_hours = models.DecimalField(max_digits=5, decimal_places=2, default=0.00)
    overtime_hours = models.DecimalField(max_digits=5, decimal_places=2, default=0.00)
    
    attendance_status = models.CharField(max_length=20, default='Present') # Present, Absent, Half Day
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('employee', 'attendance_date')

    def save(self, *args, **kwargs):
        if self.first_check_in and self.last_check_out:
            # Calculate total duration in hours
            diff = self.last_check_out - self.first_check_in
            duration = diff.total_seconds() / 3600.0
            self.total_work_hours = max(0.0, round(duration, 2))
            
            # Fetch Attendance Policy for OT threshold
            from organisation.models import AttendancePolicy
            policy = None
            if hasattr(self.employee, 'attendance_policy'):
                policy = self.employee.attendance_policy
            elif self.site and hasattr(self.site, 'attendance_policy'):
                policy = self.site.attendance_policy
            elif self.employee.entity and hasattr(self.employee.entity, 'default_attendance_policy'):
                policy = self.employee.entity.default_attendance_policy
            
            ot_threshold = float(policy.ot_applicable_after_hours) if policy else 2.0

            # Fetch Shift Definition for this employee on this date for standard hours
            try:
                shift_assignment = ShiftAssignment.objects.get(employee=self.employee, date=self.attendance_date)
                shift = shift_assignment.shift
                import datetime
                dt_start = datetime.datetime.combine(self.attendance_date, shift.start_time)
                dt_end = datetime.datetime.combine(self.attendance_date, shift.end_time)
                if dt_end < dt_start:
                    dt_end += datetime.timedelta(days=1)
                standard_hours = (dt_end - dt_start).total_seconds() / 3600.0
            except ShiftAssignment.DoesNotExist:
                standard_hours = float(policy.full_day_hours) if policy else 8.0
            
            raw_ot = max(0.0, duration - standard_hours)
            
            # Rule: if overtime > threshold, they get the combined OT. Otherwise, OT pay will not add (0).
            if raw_ot > ot_threshold:
                self.overtime_hours = round(raw_ot, 2)
            else:
                self.overtime_hours = 0.00
                
        super().save(*args, **kwargs)

class FaceProfile(models.Model):
    employee = models.OneToOneField(Employee, on_delete=models.CASCADE, related_name='face_profile')
    
    # Wave 1: AES Envelope Encrypted Multi-Angle Vectors
    encrypted_face_encodings = models.BinaryField(blank=True, null=True, help_text="AES encrypted JSON payload of multi-angle vectors (Front, Left, Right, Up, Down)")
    encrypted_dek = models.BinaryField(blank=True, null=True, help_text="Encrypted Data Encryption Key specific to this row")
    embedding_version = models.CharField(max_length=10, default='v2.0')
    data_residency_shard = models.CharField(max_length=10, default='IN', help_text="e.g. EU for GDPR, IN for DPDPA")
    
    consent_granted = models.BooleanField(default=False, help_text="DPDPA/GDPR compliance explicit consent")
    
    # Wave 9: Accessibility Support
    accessibility_profile = models.BooleanField(
        default=False, 
        help_text="If True, active liveness challenges are relaxed or bypassed for motor-impaired/neurodivergent employees."
    )
    
    is_active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"Face Profile: {self.employee.first_name} {self.employee.last_name}"

class EnrollmentAudit(models.Model):
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='enrollment_audits')
    timestamp = models.DateTimeField(auto_now_add=True)
    device_info = models.CharField(max_length=255, blank=True, null=True)
    ip_address = models.GenericIPAddressField(blank=True, null=True)
    action = models.CharField(max_length=50) # e.g., ENROLL, RE_ENROLL, REVOKE
    hash_signature = models.CharField(max_length=64, help_text="SHA256 for audit integrity")

    def save(self, *args, **kwargs):
        if not self.hash_signature or self.hash_signature == 'pending_hash_chain':
            import hashlib
            # Wave 11: Immutable Audit Logs (Blockchain concept)
            # Find the previous audit log to link the chain
            last_audit = EnrollmentAudit.objects.order_by('-id').first()
            previous_hash = last_audit.hash_signature if last_audit else "GENESIS_BLOCK"
            
            payload = f"{self.employee.id}|{self.action}|{self.ip_address}|{previous_hash}"
            self.hash_signature = hashlib.sha256(payload.encode('utf-8')).hexdigest()
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.action} - {self.employee.first_name} ({self.timestamp})"

class DynamicQRToken(models.Model):
    site = models.ForeignKey(Site, on_delete=models.CASCADE, related_name='qr_tokens')
    token = models.CharField(max_length=64, unique=True, default=uuid.uuid4)
    expires_at = models.DateTimeField()
    is_used = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"QR Token for {self.site.name} (Expires: {self.expires_at})"

class ConsentLog(models.Model):
    """
    Wave 10: Privacy & Compliance.
    Immutable audit trail for GDPR/DPDPA biometric consent.
    """
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='consent_logs')
    action = models.CharField(max_length=20, choices=(('GRANTED', 'Granted'), ('REVOKED', 'Revoked')))
    timestamp = models.DateTimeField(auto_now_add=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    user_agent = models.TextField(null=True, blank=True)
    
    def __str__(self):
        return f"{self.employee} - {self.action} at {self.timestamp}"

class ManualOverrideRequest(models.Model):
    """
    Wave 13: Manual Review Controls.
    Requires 2-person approval (e.g. HR + Admin) to override the AI.
    """
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='override_requests')
    reason = models.TextField(help_text="Why did the AI fail? (e.g. Server down, False Rejection)")
    
    approver_1 = models.ForeignKey(Employee, on_delete=models.SET_NULL, null=True, blank=True, related_name='overrides_approved_1')
    approver_2 = models.ForeignKey(Employee, on_delete=models.SET_NULL, null=True, blank=True, related_name='overrides_approved_2')
    
    is_approved = models.BooleanField(default=False)
    timestamp = models.DateTimeField(auto_now_add=True)
    
    def check_approval(self):
        if self.approver_1 and self.approver_2 and self.approver_1 != self.approver_2:
            self.is_approved = True
            self.save()
            return True
        return False

@receiver(post_save, sender=Employee)
def delete_face_profile_if_inactive(sender, instance, **kwargs):
    if instance.status != 'Active':
        FaceProfile.objects.filter(employee=instance).delete()

class PunchLog(models.Model):
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE)
    daily_attendance = models.ForeignKey(DailyAttendance, on_delete=models.CASCADE, related_name='punches')
    
    punch_time = models.DateTimeField()
    punch_type = models.CharField(max_length=10) # IN or OUT
    source = models.CharField(max_length=20) # GPS, QR, FACE, WEB
    
    latitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    longitude = models.DecimalField(max_digits=9, decimal_places=6, null=True, blank=True)
    
    VERIFICATION_CHOICES = [
        ('VERIFIED', 'Verified'),
        ('PENDING_ML_INSTALL', 'Pending ML Install'),
        ('REJECTED', 'Rejected'),
        ('UNVERIFIED_LEGACY', 'Unverified Legacy'),
    ]
    verification_status = models.CharField(max_length=20, choices=VERIFICATION_CHOICES, default='PENDING_ML_INSTALL')
    
    qr_token = models.CharField(max_length=64, null=True, blank=True)
    
    device_info = models.CharField(max_length=255, blank=True, null=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=['employee', 'qr_token'],
                name='unique_punch_per_qr_token'
            )
        ]

class RegularizationRequest(models.Model):
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='regularizations')
    attendance_date = models.DateField()
    
    requested_check_in = models.DateTimeField()
    requested_check_out = models.DateTimeField()
    
    reason = models.TextField()
    manager_comments = models.TextField(blank=True, null=True)
    attachment = models.FileField(upload_to='regularizations/', blank=True, null=True)
    
    status = models.CharField(max_length=20, default='Pending') # Pending, Approved, Rejected
    
    approved_by = models.ForeignKey(Employee, on_delete=models.SET_NULL, null=True, blank=True, related_name='approved_regularizations')
    approved_at = models.DateTimeField(null=True, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

class ShiftDefinition(models.Model):
    site = models.ForeignKey(Site, on_delete=models.CASCADE, related_name='shift_definitions', null=True, blank=True)
    name = models.CharField(max_length=100)
    code = models.CharField(max_length=20, unique=True)
    start_time = models.TimeField()
    end_time = models.TimeField()
    grace_minutes = models.IntegerField(default=0)
    ot_multiplier = models.DecimalField(max_digits=4, decimal_places=2, default=1.0)
    color_hex = models.CharField(max_length=20, default="#000000")
    is_active = models.BooleanField(default=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.name} ({self.code})"

class ShiftAssignment(models.Model):
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='shift_assignments')
    shift = models.ForeignKey(ShiftDefinition, on_delete=models.CASCADE)
    date = models.DateField()
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        unique_together = ('employee', 'date')

    def __str__(self):
        return f"{self.employee.code} - {self.shift.code} on {self.date}"

class Holiday(models.Model):
    site = models.ForeignKey(Site, on_delete=models.CASCADE, related_name='holidays', null=True, blank=True)
    name = models.CharField(max_length=100)
    date = models.DateField()
    holiday_type = models.CharField(max_length=50, default='Festival') # National, Festival, Company, Optional, Restricted, Regional
    description = models.TextField(blank=True, null=True)
    status = models.CharField(max_length=20, default='Active') # Active, Draft

    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.name} on {self.date}"

class HolidayRuleGroup(models.Model):
    holiday = models.ForeignKey(Holiday, on_delete=models.CASCADE, related_name='rule_groups')
    
    applicable_roles = models.ManyToManyField(Role, blank=True, related_name='applicable_holidays')
    applicable_departments = models.ManyToManyField(Department, blank=True, related_name='applicable_holidays')
    applicable_entities = models.ManyToManyField(Entity, blank=True, related_name='applicable_holidays')
    applicable_branches = models.ManyToManyField(Branch, blank=True, related_name='applicable_holidays')
    
    excluded_roles = models.ManyToManyField(Role, blank=True, related_name='excluded_holidays')
    excluded_departments = models.ManyToManyField(Department, blank=True, related_name='excluded_holidays')
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    
    def __str__(self):
        return f"Rule Group for {self.holiday.name}"
