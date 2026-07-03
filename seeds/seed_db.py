import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

from organisation.models import Entity, Branch, Site
from employees.models import Employee

# Create Entity
entity, _ = Entity.objects.get_or_create(name="PeoplePulse Corp", code="PP")

# Create Branch
branch, _ = Branch.objects.get_or_create(name="Headquarters", entity=entity, city="Bengaluru")

# Create Site
site, _ = Site.objects.get_or_create(
    name="Bengaluru HQ",
    branch=branch,
    defaults={
        'latitude': 12.971598,
        'longitude': 77.594562,
        'radius': 150,
        'qr_enabled': True,
        'face_enabled': True
    }
)

# Create Employee
employee, _ = Employee.objects.update_or_create(
    code="EMP001",
    defaults={
        'email': "admin@peoplepulse.com",
        'first_name': "Admin",
        'last_name': "User",
        'entity': entity,
        'branch': branch,
        'site': site,
        'status': 'Active',
        'ctc': 2400000
    }
)

print(f"Successfully seeded DB! Site ID: {site.id}, Employee ID: {employee.id}")
