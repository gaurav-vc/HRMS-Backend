import os
import django

# Setup Django environment
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

from organisation.models import Site, Department, Designation, Entity

def setup_lotus_roles():
    print("Starting role creation for Lotus HQ...")
    
    # 1. Find the site
    site = Site.objects.filter(contact_email='gauravkokane05@gmail.com').first()
    if not site:
        print("Error: Could not find site with admin email gauravkokane05@gmail.com")
        return
        
    print(f"Found Site: {site.name}")
    
    # 2. Get or create the Entity
    entity = Entity.objects.filter(name='Lotus Developers').first()
    if not entity:
        entity = Entity.objects.create(name='Lotus Developers')
        
    # 3. Create 'General Department' as requested
    department, dept_created = Department.objects.get_or_create(
        name='General Department',
        entity=entity,
        defaults={'code': 'GEN'}
    )
    if dept_created:
        print("Created new Department: General Department")
        
    # 4. Create the Designations from Picture 1
    roles_to_create = [
        "SENIOR MANAGER",
        "EXECUTIVE",
        "SENIOR ARCHITECT",
        "ENGINEER",
        "DRIVER",
        "ASSISTANT VICE PRESIDENT-PROCUREMENT"
    ]
    
    for title in roles_to_create:
        designation, created = Designation.objects.get_or_create(
            title=title,
            department=department
        )
        if created:
            print(f"  [+] Created Role/Designation: {title}")
        else:
            print(f"  [-] Role/Designation {title} already exists")

    from organisation.views import provision_contact_person
    print("Provisioning contact person (Site Admin Employee profile)...")
    provision_contact_person(site)
            
    print("Successfully completed role generation and admin provisioning!")

# Execute immediately when loaded in shell
setup_lotus_roles()
