import os
import django
from datetime import date

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings")
django.setup()

from employees.models import OfferLetter

# Let's update Offer ID 7 to have a future date so it shows up in "Upcoming"
try:
    offer = OfferLetter.objects.get(id=7)
    if offer.employee:
        offer.employee.doj = date(2026, 8, 1) # Future date
        offer.employee.save()
        print(f"Updated Employee DOJ for Offer 7 to {offer.employee.doj}")
except Exception as e:
    print(f"Error: {e}")
