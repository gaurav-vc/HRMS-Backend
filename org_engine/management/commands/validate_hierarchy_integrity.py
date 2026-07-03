from django.core.management.base import BaseCommand
from org_engine.models import OrganizationNode, NodeRelationship
from django.db.models import Count, Q

class Command(BaseCommand):
    help = 'Scheduled Integrity Validation Job to detect orphans, broken chains, and inactive managers.'

    def handle(self, *args, **kwargs):
        self.stdout.write("Running Enterprise Hierarchy Integrity Validation...")
        issues_found = 0

        # 1. Orphan Nodes (Has parent_id but parent does not exist or parent is deleted)
        self.stdout.write("Checking for orphan nodes...")
        valid_parent_ids = OrganizationNode.objects.values_list('id', flat=True)
        orphans = OrganizationNode.objects.filter(parent_id__isnull=False).exclude(parent_id__in=valid_parent_ids)
        if orphans.exists():
            for orphan in orphans:
                self.stderr.write(f"ORPHAN DETECTED: Node {orphan.id} '{orphan.name}' points to missing parent {orphan.parent_id}")
                issues_found += 1

        # 2. Inactive Managers with Active Reports
        self.stdout.write("Checking for inactive managers with active reports...")
        active_with_inactive_parents = OrganizationNode.objects.filter(
            status='Active',
            parent__status='Archived'
        )
        if active_with_inactive_parents.exists():
            for node in active_with_inactive_parents:
                self.stderr.write(f"HIERARCHY VIOLATION: Active Node {node.id} '{node.name}' reports to Archived Node {node.parent_id}")
                issues_found += 1

        # 3. Path Consistency Check
        self.stdout.write("Checking materialized path consistency...")
        all_nodes = OrganizationNode.objects.filter(parent__isnull=False)
        for node in all_nodes:
            expected_prefix = f"{node.parent.path}." if node.parent.path else ""
            if not node.path.startswith(expected_prefix):
                self.stderr.write(f"PATH INCONSISTENCY: Node {node.id} path '{node.path}' does not match parent '{node.parent.path}'")
                issues_found += 1

        # 4. Matrix Relationship Validation (Target missing)
        self.stdout.write("Checking matrix relationship integrity...")
        broken_rels = NodeRelationship.objects.filter(
            Q(source_node__isnull=True) | Q(target_node__isnull=True)
        )
        if broken_rels.exists():
            for rel in broken_rels:
                self.stderr.write(f"BROKEN MATRIX: Relationship {rel.id} has missing source or target.")
                issues_found += 1

        if issues_found == 0:
            self.stdout.write(self.style.SUCCESS("Validation Complete: 0 issues found. The hierarchy is perfectly intact!"))
        else:
            self.stderr.write(self.style.ERROR(f"Validation Complete: {issues_found} issues detected requiring administrator attention."))
