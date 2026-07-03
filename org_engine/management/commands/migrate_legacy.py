import sys
from django.core.management.base import BaseCommand
from org_engine.models import OrganizationNode, OrganizationNodeType
from organisation.models import Entity, Department, Role
from employees.models import Employee

class Command(BaseCommand):
    help = 'Migrates legacy users and roles into the new Enterprise Organization Graph'

    def handle(self, *args, **kwargs):
        self.stdout.write("Starting legacy migration to Organization Graph...")

        # 1. Clear existing tree data (User already did this manually, but just in case)
        OrganizationNode.objects.all().delete()
        self.stdout.write("Cleared existing tree data.")

        # 2. Get or create node types
        entity_type, _ = OrganizationNodeType.objects.get_or_create(name='Entity', defaults={'level_order': 1})
        dept_type, _ = OrganizationNodeType.objects.get_or_create(name='Department', defaults={'level_order': 2})
        role_type, _ = OrganizationNodeType.objects.get_or_create(name='Role', defaults={'level_order': 3})
        emp_type, _ = OrganizationNodeType.objects.get_or_create(name='Employee', defaults={'level_order': 4})

        # 3. Create Entity Nodes
        entity_nodes = {}
        for entity in Entity.objects.all():
            node = OrganizationNode.objects.create(
                name=entity.name,
                node_type=entity_type,
                tenant_id=1,
            )
            entity_nodes[entity.id] = node
        
        self.stdout.write(f"Migrated {len(entity_nodes)} Entities.")

        # 4. Create Department Nodes
        dept_nodes = {}
        for dept in Department.objects.all():
            parent_node = entity_nodes.get(dept.entity_id) if dept.entity_id else None
            node = OrganizationNode.objects.create(
                name=dept.name,
                node_type=dept_type,
                parent=parent_node,
                tenant_id=1,
            )
            dept_nodes[dept.id] = node
        
        self.stdout.write(f"Migrated {len(dept_nodes)} Departments.")

        # 5. Create Role Nodes
        role_nodes = {}
        for role in Role.objects.all():
            parent_node = dept_nodes.get(role.department_id) if role.department_id else None
            node = OrganizationNode.objects.create(
                name=role.name,
                node_type=role_type,
                parent=parent_node,
                tenant_id=1,
            )
            role_nodes[role.id] = node
        
        self.stdout.write(f"Migrated {len(role_nodes)} Roles.")

        # 6. Create Employee Nodes
        emp_count = 0
        for emp in Employee.objects.all():
            # Employees map to Role. If no Role, fallback to Department. If no Dept, fallback to Entity.
            parent_node = role_nodes.get(emp.dynamic_role_id)
            if not parent_node:
                parent_node = dept_nodes.get(emp.department_id)
            if not parent_node:
                parent_node = entity_nodes.get(emp.entity_id)

            OrganizationNode.objects.create(
                name=f"{emp.first_name} {emp.last_name}",
                node_type=emp_type,
                parent=parent_node,
                tenant_id=1,
            )
            emp_count += 1
            
        self.stdout.write(f"Migrated {emp_count} Employees.")

        self.stdout.write(self.style.SUCCESS("Legacy migration completed successfully! Go to the UI and refresh the page to see your real tree!"))
