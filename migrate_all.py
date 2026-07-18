import os
import django
import sys

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

from employees.models import Employee
from organisation.models import Entity, Site, Branch
from admin_org.models import Organization

def migrate_all():
    print("Migrating ALL employees to Lotus Developers -> Local Site HQ...")

    org, _ = Organization.objects.get_or_create(
        name__icontains='Lotus Developer',
        defaults={'name': 'Lotus Developers', 'status': 'Active'}
    )

    entity, _ = Entity.objects.get_or_create(
        name__icontains='Lotus Developer',
        defaults={'name': 'Lotus Developers', 'status': 'Active', 'organization': org}
    )
    
    branch, _ = Branch.objects.get_or_create(
        entity=entity,
        name='Head Office'
    )
    
    site, _ = Site.objects.get_or_create(
        organization=org,
        name__icontains='Local Site HQ',
        defaults={
            'name': 'Local Site HQ',
            'branch': branch,
            'site_code': 'LSHQ-01',
            'status': 'Active'
        }
    )

    # Ensure the Site Admin is correctly linked to contact_email so DataIsolationMixin works
    site.contact_email = "gauravkokane05@gmail.com"
    site.save()

    # Move ALL employees to this site so they are visible
    employees = Employee.objects.all()
    count = employees.count()
    employees.update(entity=entity, branch=branch, site=site)

    print(f"Successfully migrated all {count} employees and their associated data to the new Site!")

if __name__ == '__main__':
    migrate_all()
