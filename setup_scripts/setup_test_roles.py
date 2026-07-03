from org_engine.models import OrganizationNode, OrganizationNodeType
import json

def setup():
    role_type, _ = OrganizationNodeType.objects.get_or_create(name='Role')

    hr_role = OrganizationNode.objects.filter(name__icontains='HR Manager', node_type=role_type).first()
    if hr_role:
        perms = hr_role.permissions or {}
        perms['can_process_payroll'] = True
        perms['can_view_confidential_payroll'] = False # Hidden from HR
        hr_role.permissions = perms
        hr_role.save()
        print(f"{hr_role.name} permissions updated.")

    ceo_role = OrganizationNode.objects.filter(name__icontains='CEO', node_type=role_type).first()
    if ceo_role:
        perms = ceo_role.permissions or {}
        perms['can_approve_payroll'] = True
        perms['can_view_confidential_payroll'] = True # CEO sees everything
        ceo_role.permissions = perms
        ceo_role.save()
        print(f"{ceo_role.name} permissions updated.")

    finance_role = OrganizationNode.objects.filter(name__icontains='Finance', node_type=role_type).first()
    if finance_role:
        perms = finance_role.permissions or {}
        perms['can_release_salary'] = True
        perms['can_view_confidential_payroll'] = True # Finance HR usually sees it too
        finance_role.permissions = perms
        finance_role.save()
        print(f"{finance_role.name} permissions updated.")

    print("Done setting up roles.")

setup()
