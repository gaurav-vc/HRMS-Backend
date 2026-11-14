from django.apps import AppConfig


class OrganisationConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'organisation'

    def ready(self):
        # Startup should remain side-effect free.
        # Database operations and role cleanup are handled via migrations or management commands.
        pass
