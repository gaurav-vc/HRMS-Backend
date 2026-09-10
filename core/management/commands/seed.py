from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from admin_org.models import Organization

class Command(BaseCommand):
    help = 'Seeds the database with an initial admin user and default organization'

    def handle(self, *args, **kwargs):
        self.stdout.write("Starting database seed...")

        # 1. Create a superuser if it doesn't exist
        if not User.objects.filter(username='admin').exists():
            User.objects.create_superuser('admin', 'admin@example.com', 'admin123')
            self.stdout.write(self.style.SUCCESS("Successfully created superuser 'admin' with password 'admin123'"))
        else:
            self.stdout.write(self.style.WARNING("Superuser 'admin' already exists. Skipping."))

        # 2. Create a default Organization if it doesn't exist
        if not Organization.objects.exists():
            org = Organization.objects.create(
                name="Default Organization",
                company_name="Vibe Copilot",
                status="Active"
            )
            self.stdout.write(self.style.SUCCESS(f"Successfully created default organization: {org.name}"))
        else:
            self.stdout.write(self.style.WARNING("Organization already exists. Skipping."))

        self.stdout.write(self.style.SUCCESS("Database seeding completed successfully!"))
