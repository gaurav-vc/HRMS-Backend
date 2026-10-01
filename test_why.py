from django.contrib.auth.models import User
from employees.models import Employee
from organisation.models import Site

u = User.objects.get(email='gocixi8623@bitproy.com')
emp = u.employee_profile

print("User email:", u.email)
print("Emp site:", emp.site.name if emp.site else 'None')
print("Emp enrolled sites:", list(emp.enrolled_sites.values_list('name', flat=True)))
print("Sites where contact_email is this user:", list(Site.objects.filter(contact_email=u.email).values_list('name', flat=True)))
