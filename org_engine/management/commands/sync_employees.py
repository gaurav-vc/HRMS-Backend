from django.core.management.base import BaseCommand
from employees.models import Employee
from org_engine.models import OrganizationNode, OrganizationNodeType
from org_engine.engine import HierarchyEngine

class Command(BaseCommand):
    help = 'Cleans up employee nodes that were incorrectly attached to the root node'

    def handle(self, *args, **kwargs):
        emp_type = OrganizationNodeType.objects.filter(name='Employee').first()
        if not emp_type:
            self.stdout.write("No Employee node type found.")
            return

        deleted_count = 0
        
        # Get all OrganizationNodes of type Employee
        emp_nodes = OrganizationNode.objects.filter(node_type=emp_type)
        
        for node in emp_nodes:
            # Check if the corresponding Employee has a role
            emp = Employee.objects.filter(
                first_name=node.name.split(' ')[0], 
                last_name=' '.join(node.name.split(' ')[1:])
            ).first()
            
            if emp and not emp.dynamic_role:
                # Employee exists but has no role, so their node shouldn't exist!
                self.stdout.write(f"Deleting node for {node.name} because they have no role.")
                node.delete()
                deleted_count += 1
            elif not emp:
                # Just in case there are orphaned nodes
                self.stdout.write(f"Deleting orphaned node {node.name}")
                node.delete()
                deleted_count += 1
                
        self.stdout.write(self.style.SUCCESS(f"Successfully cleaned up {deleted_count} employee nodes."))
