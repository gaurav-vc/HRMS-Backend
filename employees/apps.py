from django.apps import AppConfig


class EmployeesConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'employees'

    def ready(self):
        # Startup should remain side-effect free.
        # Background scheduling (e.g. birthday emails) is triggered via management commands / task runner.
        pass
