from authentication.permissions import _get_admin_sites, isolate_queryset
from django.contrib.auth.models import User
from employees.models import Employee
from organisation.models import Site, Department, Designation

u = User.objects.filter(email='luis.suarez@example.com').first()
if not u:
    u = User.objects.filter(email__icontains='suarez').first()
if not u:
    u = User.objects.last()

print("User:", u.email)
print("Role:", getattr(u, 'employee_profile', None).role if hasattr(u, 'employee_profile') else 'None')
print("Dynamic Role:", getattr(u, 'employee_profile', None).dynamic_role.name if getattr(u, 'employee_profile', None) and getattr(u, 'employee_profile', None).dynamic_role else 'None')
print("Admin Sites:", _get_admin_sites(u))

qs_emp = isolate_queryset(Employee.objects.all(), u)
print("Employees visible:", qs_emp.count())
print("Sites of visible employees:", set(qs_emp.values_list('site__name', flat=True)))

qs_site = isolate_queryset(Site.objects.all(), u)
print("Sites visible:", qs_site.count())
print("Sites:", list(qs_site.values_list('name', flat=True)))
