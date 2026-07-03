from django.core.management.base import BaseCommand
from employees.models import Employee
from organisation.models import Role
from org_engine.models import OrganizationNode, OrganizationNodeType
from org_engine.engine import HierarchyEngine

class Command(BaseCommand):
    help = 'Assigns test roles to employees and syncs the Org Tree.'

    def handle(self, *args, **kwargs):
        emp_type, _ = OrganizationNodeType.objects.get_or_create(name='Employee')
        
        # Get roles (based on standard hierarchy you showed earlier)
        role1 = Role.objects.filter(name="Board of Directors").first()
        role2 = Role.objects.filter(name="Group CEO / Managing Director").first()
        role3 = Role.objects.filter(name="C-Level Leadership").first()
        
        # If specific roles aren't found, just grab any 3 distinct roles
        if not all([role1, role2, role3]):
            roles = list(Role.objects.all()[:3])
            if len(roles) >= 3:
                role1, role2, role3 = roles
            else:
                self.stdout.write("Not enough roles found in the database to test.")
                return
            
        # Get 5 employees (excluding Gaurav)
        employees = list(Employee.objects.exclude(first_name__icontains="Gaurav")[:5])
        
        if len(employees) < 5:
            self.stdout.write("Not enough employees found to test.")
            return
            
        # Our assignment plan:
        # Two people in role1
        # Two people in role2
        # One person in role3
        assignments = [
            (employees[0], role1),
            (employees[1], role1), 
            (employees[2], role2),
            (employees[3], role2), 
            (employees[4], role3), 
        ]
        
        for emp, role in assignments:
            # 1. Update Employee model (This updates the Users table page)
            emp.dynamic_role = role
            emp.save(update_fields=['dynamic_role'])
            
            # 2. Sync to Org Engine Graph (This updates the Org Tree page)
            emp_name = f"{emp.first_name} {emp.last_name}"
            
            # Find the target Role Node in the Org Tree
            role_node = OrganizationNode.objects.filter(name=role.name, node_type__name='Role').first()
            
            if role_node:
                # Find if employee already has a node
                emp_node = OrganizationNode.objects.filter(name=emp_name, node_type=emp_type).first()
                if emp_node:
                    # Move them to the new role
                    HierarchyEngine.move_node(emp_node, role_node)
                else:
                    # Create them under the role
                    OrganizationNode.objects.create(
                        name=emp_name,
                        node_type=emp_type,
                        parent=role_node,
                        tenant_id=1
                    )
            
            self.stdout.write(f"Assigned {emp_name} to {role.name}")
            
        self.stdout.write(self.style.SUCCESS("\nSuccessfully assigned roles! You can now check the Users table and Org Tree frontend."))
