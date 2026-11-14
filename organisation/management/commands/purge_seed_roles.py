from django.core.management.base import BaseCommand
from django.db import connection


class Command(BaseCommand):
    help = "Purges hardcoded legacy seed roles and deduplicates Site Admin roles safely."

    def handle(self, *args, **options):
        table_names = connection.introspection.table_names()
        if "organisation_role" not in table_names:
            self.stdout.write("organisation_role table does not exist. Skipping.")
            return

        from organisation.models import Role
        from employees.models import Employee

        # 1. Consolidate and deduplicate 'Site Admin' roles
        site_admins = list(Role.objects.filter(name__iexact="Site Admin").order_by("id"))
        if site_admins:
            canonical_site_admin = site_admins[0]
            if len(site_admins) > 1:
                duplicate_ids = [r.id for r in site_admins[1:]]
                reassigned = Employee.objects.filter(dynamic_role_id__in=duplicate_ids).update(
                    dynamic_role=canonical_site_admin
                )
                deleted, _ = Role.objects.filter(id__in=duplicate_ids).delete()
                self.stdout.write(
                    self.style.SUCCESS(
                        f"Deduplicated Site Admin roles: reassigned {reassigned} employees, deleted {deleted} duplicate roles."
                    )
                )

        # 2. Hardcoded test script role names to remove
        seed_names = [
            "ASSISTANT VICE PRESIDENT-PROCUREMENT",
            "DRIVER",
            "ENGINEER",
            "SENIOR ARCHITECT",
            "EXECUTIVE",
            "SENIOR MANAGER",
            "Human Resource",
        ]

        # Safely detach any employees referencing these seed roles
        detached = Employee.objects.filter(dynamic_role__name__in=seed_names).update(dynamic_role=None)
        if detached:
            self.stdout.write(f"Detached {detached} employees referencing legacy seed roles.")

        # Remove from OrganizationNode tree if present
        if "org_engine_organizationnode" in table_names:
            try:
                from org_engine.models import OrganizationNode
                deleted_nodes, _ = OrganizationNode.objects.filter(
                    name__in=seed_names, node_type__name="Role"
                ).delete()
                if deleted_nodes:
                    self.stdout.write(f"Deleted {deleted_nodes} OrganizationNodes for seed roles.")
            except Exception as e:
                self.stdout.write(self.style.WARNING(f"Could not purge from OrganizationNode: {e}"))

        # Permanently purge the hardcoded seed roles
        deleted_roles, _ = Role.objects.filter(name__in=seed_names).delete()
        self.stdout.write(self.style.SUCCESS(f"Purged {deleted_roles} legacy seed roles."))

