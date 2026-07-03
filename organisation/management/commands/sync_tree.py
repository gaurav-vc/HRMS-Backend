import sys
import re
from django.core.management.base import BaseCommand
from django.db import transaction
from organisation.models import Role
from org_engine.models import OrganizationNode, OrganizationNodeType
from org_engine.engine import HierarchyEngine
from employees.models import Employee

class Command(BaseCommand):
    help = 'Completely wipes the Organization Tree and rebuilds it exclusively with Roles and Employees based strictly on L-levels.'

    def extract_level(self, level_str):
        if not level_str:
            return None
        match = re.search(r'\d+', str(level_str))
        if match:
            return int(match.group())
        return None

    @transaction.atomic
    def handle(self, *args, **kwargs):
        self.stdout.write(self.style.WARNING("Initiating complete wipe of Organization Graph..."))

        # 1. NUKE the existing visual graph. (This only deletes visual nodes, not your actual data)
        OrganizationNode.objects.all().delete()
        self.stdout.write("Wiped previous graph structure.")

        # 2. Get Node Types
        role_type, _ = OrganizationNodeType.objects.get_or_create(name='Role')
        emp_type, _ = OrganizationNodeType.objects.get_or_create(name='Employee')

        # 3. Categorize all Roles by their extracted level number
        roles = Role.objects.all()
        level_map = {}
        for role in roles:
            lvl_num = self.extract_level(role.hierarchy_level)
            if lvl_num is not None:
                if lvl_num not in level_map:
                    level_map[lvl_num] = []
                level_map[lvl_num].append(role)
        
        # 4. Rebuild exclusively with Roles
        created_nodes = {} # role_id -> OrganizationNode
        
        for lvl_num in sorted(level_map.keys()):
            for role in level_map[lvl_num]:
                parent_node = None
                
                # If it's not the top level, find a parent
                if lvl_num > 1:
                    found_parent = False
                    for search_lvl in range(lvl_num - 1, 0, -1):
                        if search_lvl in level_map and len(level_map[search_lvl]) > 0:
                            parent_role = level_map[search_lvl][0] # Pick the first available boss
                            
                            # Hard-link in database
                            role.reporting_to = parent_role
                            role.save(update_fields=['reporting_to'])
                            
                            parent_node = created_nodes.get(parent_role.id)
                            break
                            
                # Create the Role Node in the Tree
                role_node = OrganizationNode.objects.create(
                    name=role.name,
                    node_type=role_type,
                    parent=parent_node,
                    tenant_id=1
                )
                created_nodes[role.id] = role_node

        self.stdout.write(self.style.SUCCESS(f"Successfully generated pure Role hierarchy with {len(created_nodes)} roles!"))

        # 5. Snap all Employees perfectly under their Dynamic Roles
        synced_users = 0
        employees = Employee.objects.all()
        for emp in employees:
            if emp.dynamic_role and emp.dynamic_role.id in created_nodes:
                emp_name = f"{emp.first_name} {emp.last_name}"
                parent_role_node = created_nodes[emp.dynamic_role.id]
                
                OrganizationNode.objects.create(
                    name=emp_name,
                    node_type=emp_type,
                    parent=parent_role_node,
                    tenant_id=1
                )
                synced_users += 1
                
        self.stdout.write(self.style.SUCCESS(f"Successfully snapped {synced_users} users directly into the Roles!"))
