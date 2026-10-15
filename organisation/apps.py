from django.apps import AppConfig


class OrganisationConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'organisation'

    def ready(self):
        try:
            self._purge_hardcoded_seed_roles()
        except Exception:
            pass

    def _purge_hardcoded_seed_roles(self):
        """
        Dynamically eliminates hardcoded legacy seed data from the database.
        Ensures 100% of roles in the system are dynamically created and configured.
        """
        from django.db import connection
        table_names = connection.introspection.table_names()
        if 'organisation_role' not in table_names:
            return

        from organisation.models import Role
        from employees.models import Employee

        # 1. Consolidate and deduplicate 'Site Admin' roles
        site_admins = list(Role.objects.filter(name__iexact='Site Admin').order_by('id'))
        if site_admins:
            canonical_site_admin = site_admins[0]
            if len(site_admins) > 1:
                duplicate_ids = [r.id for r in site_admins[1:]]
                # Reassign any employees pointing to duplicate Site Admin roles
                Employee.objects.filter(dynamic_role_id__in=duplicate_ids).update(dynamic_role=canonical_site_admin)
                # Delete duplicate Site Admin roles
                Role.objects.filter(id__in=duplicate_ids).delete()

        # 2. Hardcoded test script role names to remove
        seed_names = [
            'ASSISTANT VICE PRESIDENT-PROCUREMENT',
            'DRIVER',
            'ENGINEER',
            'SENIOR ARCHITECT',
            'EXECUTIVE',
            'SENIOR MANAGER',
            'Human Resource'
        ]

        # Safely detach any employees referencing these seed roles
        Employee.objects.filter(dynamic_role__name__in=seed_names).update(dynamic_role=None)

        # Remove from OrganizationNode tree if present
        if 'org_engine_organizationnode' in table_names:
            try:
                from org_engine.models import OrganizationNode
                OrganizationNode.objects.filter(name__in=seed_names, node_type__name='Role').delete()
            except Exception:
                pass

        # Permanently purge the hardcoded seed roles
        Role.objects.filter(name__in=seed_names).delete()

