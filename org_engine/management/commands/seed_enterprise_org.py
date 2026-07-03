from django.core.management.base import BaseCommand
from django.db import transaction
from org_engine.models import OrganizationNodeType, OrganizationNode
import time
import random

class Command(BaseCommand):
    help = 'Seeds the database with 10,000+ synthetic organization nodes to benchmark the Materialized Path implementation.'

    def handle(self, *args, **kwargs):
        self.stdout.write("Starting Enterprise Organization Benchmark Seed...")

        # 1. Ensure we have basic Node Types
        types = ['Group', 'Entity', 'Region', 'Department', 'Team', 'Role', 'Position', 'Employee']
        node_types = {}
        for idx, t in enumerate(types):
            nt, _ = OrganizationNodeType.objects.get_or_create(name=t, defaults={'level_order': idx})
            node_types[t] = nt

        # Clean existing test data (optional but good for a clean benchmark)
        OrganizationNode.objects.filter(name__startswith="Test").delete()

        # 2. Build Hierarchy
        # We will create 1 Group -> 5 Entities -> 5 Regions each -> 10 Departments each -> 5 Roles each -> 10 Employees each
        # Total nodes approx 1 + 5 + 25 + 250 + 1250 + 12500 = 14,031 nodes
        
        start_time = time.time()
        
        with transaction.atomic():
            group = OrganizationNode.objects.create(name="Test Group Corp", node_type=node_types['Group'])
            
            for e in range(5):
                entity = OrganizationNode.objects.create(
                    name=f"Test Entity {e}", 
                    node_type=node_types['Entity'], 
                    parent=group
                )
                
                for r in range(5):
                    region = OrganizationNode.objects.create(
                        name=f"Test Region {e}-{r}", 
                        node_type=node_types['Region'], 
                        parent=entity
                    )
                    
                    # Batch create optimization for deeper levels
                    departments = []
                    for d in range(10):
                        dep = OrganizationNode(
                            name=f"Test Dept {e}-{r}-{d}",
                            node_type=node_types['Department'],
                            parent=region
                        )
                        dep.save() # need save() to trigger path generation for now
                        
                        for ro in range(5):
                            role = OrganizationNode(
                                name=f"Test Role {e}-{r}-{d}-{ro}",
                                node_type=node_types['Role'],
                                parent=dep
                            )
                            role.save()
                            
                            for em in range(10):
                                emp = OrganizationNode(
                                    name=f"Test Employee {e}-{r}-{d}-{ro}-{em}",
                                    node_type=node_types['Employee'],
                                    parent=role
                                )
                                emp.save()

        end_time = time.time()
        self.stdout.write(self.style.SUCCESS(f"Successfully generated 14,000+ nodes in {end_time - start_time:.2f} seconds!"))
        
        # 3. Test Query Performance
        self.stdout.write("Benchmarking Read Operations...")
        
        q_start = time.time()
        # Find all descendants of Entity 0 (approx 2800 nodes)
        first_entity = OrganizationNode.objects.filter(name="Test Entity 0").first()
        descendants = first_entity.get_descendants().count()
        q_end = time.time()
        
        self.stdout.write(self.style.SUCCESS(f"Fetched {descendants} descendants in {q_end - q_start:.4f} seconds using Materialized Path!"))

        q_start = time.time()
        # Find all ancestors of the very last employee
        last_emp = OrganizationNode.objects.filter(name="Test Employee 4-4-9-4-9").first()
        ancestors = last_emp.get_ancestors().count()
        q_end = time.time()

        self.stdout.write(self.style.SUCCESS(f"Fetched {ancestors} ancestors in {q_end - q_start:.4f} seconds using Materialized Path!"))
