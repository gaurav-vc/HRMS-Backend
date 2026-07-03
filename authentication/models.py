from django.db import models
from django.contrib.auth.models import User

class LoginAuditLog(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='login_logs', null=True, blank=True)
    attempted_username = models.CharField(max_length=255, null=True, blank=True)
    ip_address = models.GenericIPAddressField(null=True, blank=True)
    login_time = models.DateTimeField(auto_now_add=True)
    logout_time = models.DateTimeField(null=True, blank=True)
    status = models.CharField(max_length=50)  # e.g., 'SUCCESS', 'FAILED'
    
    def __str__(self):
        identifier = self.user.email if self.user else self.attempted_username
        return f"{identifier} - {self.status} at {self.login_time}"
