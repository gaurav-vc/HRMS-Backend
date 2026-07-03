from django.contrib.auth.models import User
from employees.models import Employee
from org_engine.models import OrganizationNode, OrganizationNodeType
import json

def setup_users():
    # Fetch roles
    role_type, _ = OrganizationNodeType.objects.get_or_create(name='Role')
    
    # Ensure roles exist
    hr_role, _ = OrganizationNode.objects.get_or_create(name='HR Manager', node_type=role_type, tenant_id=1)
    ceo_role, _ = OrganizationNode.objects.get_or_create(name='Group CEO / Managing Director', node_type=role_type, tenant_id=1)
    finance_role, _ = OrganizationNode.objects.get_or_create(name='Finance', node_type=role_type, tenant_id=1)

    # 1. Setup HR User
    hr_user, _ = User.objects.get_or_create(username='hr@company.com', email='hr@company.com')
    hr_user.set_password('Password123!')
    hr_user.save()
    
    hr_emp, _ = Employee.objects.get_or_create(user=hr_user, defaults={
        'first_name': 'Sarah',
        'last_name': 'HR',
        'email': 'hr@company.com',
        'code': 'EMP-HR-01',
        'status': 'Active'
    })
    hr_emp.dynamic_role = hr_role
    hr_emp.save()

    # 2. Setup CEO User
    ceo_user, _ = User.objects.get_or_create(username='ceo@company.com', email='ceo@company.com')
    ceo_user.set_password('Password123!')
    ceo_user.save()
    
    ceo_emp, _ = Employee.objects.get_or_create(user=ceo_user, defaults={
        'first_name': 'Michael',
        'last_name': 'CEO',
        'email': 'ceo@company.com',
        'code': 'EMP-CEO-01',
        'status': 'Active'
    })
    ceo_emp.dynamic_role = ceo_role
    ceo_emp.save()

    # 3. Setup Finance User
    finance_user, _ = User.objects.get_or_create(username='finance@company.com', email='finance@company.com')
    finance_user.set_password('Password123!')
    finance_user.save()
    
    finance_emp, _ = Employee.objects.get_or_create(user=finance_user, defaults={
        'first_name': 'David',
        'last_name': 'Finance',
        'email': 'finance@company.com',
        'code': 'EMP-FIN-01',
        'status': 'Active'
    })
    finance_emp.dynamic_role = finance_role
    finance_emp.save()

    print("Test users successfully created/updated!")
    print("---------------------------------------")
    print("HR User: hr@company.com / Password123!")
    print("CEO User: ceo@company.com / Password123!")
    print("Finance User: finance@company.com / Password123!")
    print("---------------------------------------")

setup_users()
