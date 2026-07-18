import os
import django
import random
from datetime import timedelta
from django.utils import timezone

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

from organisation.models import Entity, Branch, Site, Department, Designation
from employees.models import Employee
from admin_org.models import Organization

def randomize_dates():
    models_to_update = [Entity, Branch, Site, Department, Designation, Employee, Organization]
    
    for model in models_to_update:
        records = model.objects.all()
        for record in records:
            # Generate a random number of days (1 to 180) and hours (1 to 24) to subtract
            random_days = random.randint(1, 180)
            random_hours = random.randint(1, 24)
            random_minutes = random.randint(1, 60)
            
            # Subtract the random time from the current time
            new_date = timezone.now() - timedelta(days=random_days, hours=random_hours, minutes=random_minutes)
            
            # Only update if the field exists
            if hasattr(record, 'created_at'):
                record.created_at = new_date
                record.save(update_fields=['created_at'])
                
    print("Successfully randomized all created_at dates! Please refresh your frontend.")

if __name__ == '__main__':
    randomize_dates()
