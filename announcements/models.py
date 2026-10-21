import uuid
from django.db import models
from django.contrib.auth.models import User
from organisation.models import Entity, Department, Role
from employees.models import Employee

class Announcement(models.Model):
    AUDIENCE_CHOICES = [
        ('EVERYONE', 'Everyone'),
        ('ROLE', 'Specific Role(s)'),
        ('DEPARTMENT', 'Department'),
        ('INDIVIDUAL', 'Individual Employee'),
    ]
    PRIORITY_CHOICES = [
        ('Normal', 'Normal'),
        ('Important', 'Important'),
        ('Urgent', 'Urgent'),
    ]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    title = models.CharField(max_length=255)
    content = models.TextField()
    priority = models.CharField(max_length=20, choices=PRIORITY_CHOICES, default='Normal')
    
    # Attachment
    attachment = models.FileField(upload_to='announcements/%Y/%m/', null=True, blank=True)
    attachment_name = models.CharField(max_length=255, blank=True, null=True)
    
    # Audience Target
    audience_type = models.CharField(max_length=20, choices=AUDIENCE_CHOICES, default='EVERYONE')
    target_roles = models.ManyToManyField(Role, blank=True, related_name='announcements')
    target_departments = models.ManyToManyField(Department, blank=True, related_name='announcements')
    target_employees = models.ManyToManyField(Employee, blank=True, related_name='direct_announcements')
    entity = models.ForeignKey(Entity, on_delete=models.CASCADE, related_name='announcements', null=True, blank=True)
    
    is_active = models.BooleanField(default=True)
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']

    def __str__(self):
        return f"[{self.priority}] {self.title} ({self.audience_type})"

class AnnouncementReceipt(models.Model):
    announcement = models.ForeignKey(Announcement, on_delete=models.CASCADE, related_name='receipts')
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='announcement_receipts')
    read_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        unique_together = ('announcement', 'employee')

    def __str__(self):
        return f"{self.employee.code} read {self.announcement.title}"
