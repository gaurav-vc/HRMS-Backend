import os
import sys
import django

# Setup Django environment
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

from django.core.management import call_command

print("Dumping database to data.json with UTF-8 encoding...")
with open('data.json', 'w', encoding='utf-8') as f:
    call_command('dumpdata', exclude=['contenttypes', 'auth.Permission'], indent=4, stdout=f)
    
print("Successfully generated data.json!")
