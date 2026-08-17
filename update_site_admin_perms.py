from organisation.models import Role

default_perms = {
    'Entities': {'view': True, 'create': True, 'update': True, 'delete': True},
    'Branches': {'view': True, 'create': True, 'update': True, 'delete': True},
    'Sites': {'view': True, 'create': True, 'update': True, 'delete': True},
    'Departments': {'view': True, 'create': True, 'update': True, 'delete': True},
    'Designations': {'view': True, 'create': True, 'update': True, 'delete': True},
    'Roles & Users': {'view': True, 'create': True, 'update': True, 'delete': True},
    'Employees': {'view': True, 'create': True, 'update': True, 'delete': True},
    'Attendance': {'view': True, 'create': True, 'update': True, 'delete': True},
    'Leaves': {'view': True, 'create': True, 'update': True, 'delete': True},
    'Payroll': {'view': True, 'create': True, 'update': True, 'delete': True},
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
