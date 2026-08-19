from organisation.models import Role

default_perms = {
    'Dashboard': {'view': True, 'create': True, 'update': True, 'delete': True},
    'Entities': {'view': True, 'create': True, 'update': True, 'delete': True},
    'Branches': {'view': True, 'create': True, 'update': True, 'delete': True},
    'Sites': {'view': True, 'create': True, 'update': True, 'delete': True},
    'Departments': {'view': True, 'create': True, 'update': True, 'delete': True},
    'Designations': {'view': True, 'create': True, 'update': True, 'delete': True},
    'Roles & Users': {'view': True, 'create': True, 'update': True, 'delete': True},
    'Employees': {'view': True, 'create': True, 'update': True, 'delete': True},
    'My Calendar': {'view': True, 'create': True, 'update': True, 'delete': True},
    'Offer Letters': {'view': True, 'create': True, 'update': True, 'delete': True},
    'Offer Templates': {'view': True, 'create': True, 'update': True, 'delete': True},
    'Separation Request': {'view': True, 'create': True, 'update': True, 'delete': True},
    'Manage Exits': {'view': True, 'create': True, 'update': True, 'delete': True},
    'Attendance': {'view': True, 'create': True, 'update': True, 'delete': True},
    'Shift Definitions': {'view': True, 'create': True, 'update': True, 'delete': True},
    'Weekly Roster': {'view': True, 'create': True, 'update': True, 'delete': True},
    'QR Check-in': {'view': True, 'create': True, 'update': True, 'delete': True},
    'Face Verification': {'view': True, 'create': True, 'update': True, 'delete': True},
    'GPS Capture': {'view': True, 'create': True, 'update': True, 'delete': True},
    'Regularization': {'view': True, 'create': True, 'update': True, 'delete': True},
    'Leave Requests': {'view': True, 'create': True, 'update': True, 'delete': True},
    'Inbox': {'view': True, 'create': True, 'update': True, 'delete': True},
    'Holiday Planner': {'view': True, 'create': True, 'update': True, 'delete': True},
    'Calendar': {'view': True, 'create': True, 'update': True, 'delete': True},
    'Payroll Overview': {'view': True, 'create': True, 'update': True, 'delete': True},
    'Salary Structure': {'view': True, 'create': True, 'update': True, 'delete': True},
    'Import CTC': {'view': True, 'create': True, 'update': True, 'delete': True},
    'Run Payroll': {'view': True, 'create': True, 'update': True, 'delete': True},
    'Salary Slips': {'view': True, 'create': True, 'update': True, 'delete': True},
    'Compliance': {'view': True, 'create': True, 'update': True, 'delete': True},
    'Loans & Advances': {'view': True, 'create': True, 'update': True, 'delete': True},
    'Reimbursements': {'view': True, 'create': True, 'update': True, 'delete': True},
    'Form 16 Management': {'view': True, 'create': True, 'update': True, 'delete': True},
    'My Form 16': {'view': True, 'create': True, 'update': True, 'delete': True},
    'Organization Tree': {'view': True, 'create': True, 'update': True, 'delete': True},
    'Reports': {'view': True, 'create': True, 'update': True, 'delete': True},
    'Settings': {'view': True, 'create': True, 'update': True, 'delete': True},
}

roles = Role.objects.filter(code='SITE_ADMIN')
for role_obj in roles:
    changed = False
    if not role_obj.permissions:
        role_obj.permissions = {}
    for k, v in default_perms.items():
        if k not in role_obj.permissions:
            role_obj.permissions[k] = v
            changed = True
    if changed:
        role_obj.save(update_fields=['permissions'])
        print(f"Updated permissions for {role_obj.name}")
print("Done.")
