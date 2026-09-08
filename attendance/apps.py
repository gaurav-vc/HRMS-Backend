from django.apps import AppConfig
from django.core.checks import Warning, register
from datetime import datetime

class AttendanceConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'attendance'

    def ready(self):
        import attendance.signals

@register()
def check_shadow_mode_expiry(app_configs, **kwargs):
    errors = []
    from django.conf import settings
    shadow_mode = getattr(settings, 'LIVENESS_SHADOW_MODE_ENABLED', True)
    
    # Deployment date assumed to be today (2026-09-08)
    deployment_date = datetime(2026, 9, 8) 
    days_since_deploy = (datetime.now() - deployment_date).days
    
    if shadow_mode and days_since_deploy >= 14:
        errors.append(
            Warning(
                'Shadow Mode has been running for >= 14 days. Please review StrictLivenessAuditLog and disable LIVENESS_SHADOW_MODE_ENABLED.',
                hint='Set LIVENESS_SHADOW_MODE_ENABLED = False in settings.py',
                id='attendance.W001',
            )
        )
    return errors
