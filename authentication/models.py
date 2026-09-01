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

from django.utils import timezone
import random

class PasswordResetOTP(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='otp_codes')
    otp = models.CharField(max_length=6)
    created_at = models.DateTimeField(auto_now_add=True)
    
    def is_valid(self):
        # 10 minutes validation
        return (timezone.now() - self.created_at).total_seconds() < 600
        
    @classmethod
    def generate_otp(cls, user):
        # Invalidate previous OTPs for this user
        cls.objects.filter(user=user).delete()
        
        otp = str(random.randint(100000, 999999))
        cls.objects.create(user=user, otp=otp)
        return otp
