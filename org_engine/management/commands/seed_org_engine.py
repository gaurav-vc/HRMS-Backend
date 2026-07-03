import os
from django.core.management.base import BaseCommand
from org_engine.models import OrganizationNodeType, OrganizationNode
from django.db import transaction

class Command(BaseCommand):
    help = 'Seeds the database with a predefined Organization Tree Structure'

    def handle(self, *args, **kwargs):
        self.stdout.write("Starting Organization Tree Seeding...")
        
        with transaction.atomic():
            # Clear existing data
            OrganizationNode.objects.all().delete()
            OrganizationNodeType.objects.all().delete()
            
            self.stdout.write("Cleared existing organization nodes and types.")

            # Create Node Types
            node_types_data = [
                {'name': 'Organisation', 'level_order': 0},
                {'name': 'Entity', 'level_order': 1},
                {'name': 'Branch', 'level_order': 2},
                {'name': 'Site', 'level_order': 3},
                {'name': 'Department', 'level_order': 4},
                {'name': 'Designation', 'level_order': 5},
            ]
            
            node_types = {}
            for nt_data in node_types_data:
                nt = OrganizationNodeType.objects.create(**nt_data)
                node_types[nt.name] = nt
            
            self.stdout.write("Created Node Types.")

            # Create Root Organisation
            org_node = OrganizationNode.objects.create(
                name="Global Corp",
                node_type=node_types['Organisation'],
                parent=None,
                code="ORG001"
            )

            # Create Entity
            entity_node = OrganizationNode.objects.create(
                name="Tech Entity",
                node_type=node_types['Entity'],
                parent=org_node,
                code="ENT001"
            )

            # Create Branch
            branch_node = OrganizationNode.objects.create(
                name="Headquarters",
                node_type=node_types['Branch'],
                parent=entity_node,
                code="BRN001"
            )

            # Create Site
            site_node = OrganizationNode.objects.create(
                name="Main Campus",
                node_type=node_types['Site'],
                parent=branch_node,
                code="SIT001"
            )

            # Create Department
            dept_node = OrganizationNode.objects.create(
                name="Executive & Operations",
                node_type=node_types['Department'],
                parent=site_node,
                code="DEP001"
            )

            # Create Designations based on the H1 to H15 hierarchy as a nested tree
            designations = [
                ("Promoter / Chairman", "H1"),
                ("Board of Directors", "H2"),
                ("Group CEO / Managing Director", "H3"),
                ("C-Level Leadership", "H4"),
                ("President / EVP", "H5"),
                ("VP / Regional Head", "H6"),
                ("General Manager", "H7"),
                ("Senior Manager", "H8"),
                ("Manager", "H9"),
                ("Assistant Manager", "H10"),
                ("Senior Executive", "H11"),
                ("Executive", "H12"),
                ("Associate", "H13"),
                ("Officer", "H14"),
                ("Staff / Site Personnel", "H15")
            ]

            parent_node = dept_node
            for name, code in designations:
                node = OrganizationNode.objects.create(
                    name=f"{code} - {name}",
                    node_type=node_types['Designation'],
                    parent=parent_node,
                    code=code
                )
                parent_node = node  # Make the next designation a child of this one
                
            self.stdout.write(self.style.SUCCESS('Successfully seeded Organization Tree Structure!'))
