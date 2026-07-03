import sys
from django.core.management.base import BaseCommand
from organisation.models import Role

class Command(BaseCommand):
    help = 'Seeds H1-H15 hierarchy roles'

    def handle(self, *args, **kwargs):
        self.stdout.write("Seeding H1-H15 hierarchy roles...")

        hierarchy = [
            ("H1", "Promoter / Chairman"),
            ("H2", "Board of Directors"),
            ("H3", "Group CEO / Managing Director"),
            ("H4", "C-Level Leadership"),
            ("H5", "President / EVP"),
            ("H6", "VP / Regional Head"),
            ("H7", "General Manager"),
            ("H8", "Senior Manager"),
            ("H9", "Manager"),
            ("H10", "Assistant Manager"),
            ("H11", "Senior Executive"),
            ("H12", "Executive"),
            ("H13", "Associate"),
            ("H14", "Officer"),
            ("H15", "Staff / Site Personnel"),
        ]

        previous_role = None
        created_count = 0

        from org_engine.models import OrganizationNode, OrganizationNodeType
        from org_engine.engine import HierarchyEngine

        role_type, _ = OrganizationNodeType.objects.get_or_create(name='Role')
        
        # Get root node
        tree = OrganizationNode.objects.filter(parent__isnull=True).first()
        root_id = tree.id if tree else None

        for level, name in hierarchy:
            # Check if role exists
            role, created = Role.objects.get_or_create(
                code=name.replace(" ", "_").replace("/", "").upper()[:50],
                defaults={
                    'name': name,
                    'hierarchy_level': level,
                    'reporting_to': previous_role,
                    'access_scope': 'Corporate' if int(level[1:]) <= 5 else 'Region' if int(level[1:]) <= 8 else 'Site'
                }
            )

            if not created:
                role.hierarchy_level = level
                role.reporting_to = previous_role
                role.save(update_fields=['hierarchy_level', 'reporting_to'])
            else:
                created_count += 1
            
            # Sync with Organization Engine
            role_node, node_created = OrganizationNode.objects.get_or_create(
                name=role.name,
                node_type=role_type,
                defaults={'parent_id': root_id}
            )

            # Move node if reporting structure is set
            if previous_role:
                parent_node = OrganizationNode.objects.filter(name=previous_role.name, node_type__name='Role').first()
                if parent_node and role_node.parent_id != parent_node.id:
                    HierarchyEngine.move_node(role_node, parent_node)

            previous_role = role

        self.stdout.write(self.style.SUCCESS(f"Successfully seeded {created_count} new roles and fully synced with the Organization Engine!"))
