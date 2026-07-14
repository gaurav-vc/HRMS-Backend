import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings") 
django.setup()

from employees.models import OfferLetter
for offer in OfferLetter.objects.all():
    print(f"Offer ID: {offer.id}, Status: {offer.status}, Offer Joining Date: {offer.joining_date}, Emp DOJ: {offer.employee.doj if offer.employee else 'No Emp'}")
