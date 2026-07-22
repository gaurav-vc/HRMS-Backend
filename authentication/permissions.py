from rest_framework import permissions


class BaseRolePermission(permissions.BasePermission):
    allowed_roles = []

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False

        # Superuser always has access
        if request.user.is_superuser:
            return True

        employee = getattr(request.user, 'employee_profile', None)

        from organisation.models import Site
        if Site.objects.filter(contact_email=request.user.email).exists():
            if 'site_admin' in self.allowed_roles:
                return True
            # For Site Admins accessing HR features like Payroll, grant access if module is enabled
            sites = Site.objects.filter(contact_email=request.user.email)
            for site in sites:
                if site.modules and any(m in site.modules for m in ['Payroll', 'Payroll Overview', 'Run Payroll', 'Salary Structure', 'Import CTC']):
                    return True
            if 'site_admin' not in self.allowed_roles:
                pass  # fall through to employee check

        if not employee:
            return False

        if 'super_admin' in self.allowed_roles and employee.role == 'super_admin':
            return True

        if employee.dynamic_role:
            dash = employee.dynamic_role.dashboard_type
            if 'org_admin' in self.allowed_roles and dash == 'executive':
                return True
            if 'hr' in self.allowed_roles and (dash == 'executive' or employee.dynamic_role.permissions.get('can_run_payroll')):
                return True
            if 'manager' in self.allowed_roles and dash in ['executive', 'manager']:
                return True

        return employee.role in self.allowed_roles


class IsSuperAdmin(BaseRolePermission):
    allowed_roles = ['super_admin']


class IsOrgAdmin(BaseRolePermission):
    allowed_roles = ['super_admin', 'org_admin']


class IsSiteAdmin(BaseRolePermission):
    allowed_roles = ['super_admin', 'org_admin', 'site_admin']


class IsHR(BaseRolePermission):
    allowed_roles = ['super_admin', 'org_admin', 'hr']


class IsManager(BaseRolePermission):
    allowed_roles = ['super_admin', 'org_admin', 'hr', 'manager']


class IsEmployee(BaseRolePermission):
    allowed_roles = ['super_admin', 'org_admin', 'site_admin', 'hr', 'manager', 'employee']


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _get_admin_sites(user):
    """
    Return a queryset of Sites that `user` administers.

    Detection order:
      1. user.email matches Site.contact_email  (primary path)
      2. user.auth_profile.user_type == 'site_admin' and org_profile.site is set (legacy path)
    """
    from organisation.models import Site

    admin_sites = Site.objects.filter(contact_email=user.email)
    if admin_sites.exists():
        return admin_sites

    # Legacy / secondary path
    auth_profile = getattr(user, 'auth_profile', None)
    if auth_profile and getattr(auth_profile, 'user_type', None) == 'site_admin':
        org_profile = getattr(user, 'org_profile', None)
        if org_profile and org_profile.site_id:
            return Site.objects.filter(id=org_profile.site_id)

    return Site.objects.none()


# ---------------------------------------------------------------------------
# Core isolation function
# ---------------------------------------------------------------------------

def isolate_queryset(qs, user):
    """
    Filters `qs` so that `user` only sees records they are authorised to access.

    Hierarchy (first match wins):
      Django is_superuser  → unrestricted
      Site Admin           → their site(s) only
      No employee profile  → nothing
      super_admin role     → unrestricted
      org_admin role       → their organisation only
      Dynamic role         → scoped by access_scope
      site_admin role      → their site only (legacy employee.site)
      hr / manager         → their entity only
      employee             → their own records only
    """
    if not user.is_authenticated:
        return qs.none()

    # ── PLATFORM SUPER ADMIN ─────────────────────────────────────────────────
    if user.is_superuser:
        return qs

    employee = getattr(user, 'employee_profile', None)

    # ── SITE ADMIN ───────────────────────────────────────────────────────────
    admin_sites = _get_admin_sites(user)
    if admin_sites.exists():
        if hasattr(qs.model, 'site'):
            return qs.filter(site__in=admin_sites)
        if hasattr(qs.model, 'employee'):
            return qs.filter(employee__site__in=admin_sites)
        if qs.model.__name__ == 'Employee':
            return qs.filter(site__in=admin_sites)
        if qs.model.__name__ == 'Site':
            return qs.filter(id__in=admin_sites.values('id'))

        # Restrict to orgs that own these sites
        org_ids = admin_sites.values_list('organization_id', flat=True).distinct()
        if qs.model.__name__ == 'Organization':
            return qs.filter(id__in=org_ids)
        if hasattr(qs.model, 'organization'):
            return qs.filter(organization_id__in=org_ids)
        if hasattr(qs.model, 'entity'):
            return qs.filter(entity__organization_id__in=org_ids)
        if hasattr(qs.model, 'department'):
            return qs.filter(department__entity__organization_id__in=org_ids)

        return qs.none()

    # ── NO EMPLOYEE PROFILE → DENY ───────────────────────────────────────────
    if not employee:
        return qs.none()

    role = employee.role
    dynamic_role = getattr(employee, 'dynamic_role', None)

    # ── ROLE-BASED SUPER ADMIN ───────────────────────────────────────────────
    if role == 'super_admin':
        return qs

    # ── MULTI-TENANT BOUNDARY: apply organisation scope first ────────────────
    # Every query from this point is bounded by employee.organization.
    if hasattr(employee, 'organization') and employee.organization:
        if hasattr(qs.model, 'organization'):
            qs = qs.filter(organization=employee.organization)
        elif qs.model.__name__ == 'Employee':
            qs = qs.filter(organization=employee.organization)
        elif hasattr(qs.model, 'entity'):
            qs = qs.filter(entity__organization=employee.organization)
        elif hasattr(qs.model, 'department'):
            qs = qs.filter(department__entity__organization=employee.organization)
        elif hasattr(qs.model, 'employee'):
            qs = qs.filter(employee__organization=employee.organization)

        # Org admins see everything in their org (already scoped above)
        if role in ('admin', 'org_admin'):
            return qs

    # ── DYNAMIC ROLE SCOPING ─────────────────────────────────────────────────
    has_org_access = False
    custom_allowed = []
    if dynamic_role:
        if dynamic_role.access_scope in ['Corporate', 'Region', 'Custom']:
            has_org_access = True
            if dynamic_role.access_scope == 'Custom':
                custom_allowed = dynamic_role.permissions.get('allowed_entities', [])

    if dynamic_role:
        if has_org_access:
            if dynamic_role.access_scope == 'Corporate':
                return qs

            if custom_allowed:
                if hasattr(qs.model, 'entity'):
                    return qs.filter(entity_id__in=custom_allowed)
                if hasattr(qs.model, 'department'):
                    return qs.filter(department__entity_id__in=custom_allowed)
                if hasattr(qs.model, 'employee'):
                    return qs.filter(employee__entity_id__in=custom_allowed)
                if qs.model.__name__ == 'Employee':
                    return qs.filter(entity_id__in=custom_allowed)

            if hasattr(qs.model, 'entity'):
                return qs.filter(entity=employee.entity) if employee.entity else qs
            if hasattr(qs.model, 'department'):
                return qs.filter(department__entity=employee.entity) if employee.entity else qs
            if hasattr(qs.model, 'employee'):
                return qs.filter(employee__entity=employee.entity) if employee.entity else qs
            if qs.model.__name__ == 'Employee':
                return qs.filter(entity=employee.entity)
        else:
            # Scoped to individual employee only
            if hasattr(qs.model, 'employee'):
                return qs.filter(employee=employee)
            elif qs.model.__name__ == 'Employee':
                return qs.filter(id=employee.id)
            elif qs.model.__name__ == 'Site':
                from django.db.models import Q
                return qs.model.objects.filter(Q(id=employee.site_id) | Q(id__in=employee.enrolled_sites.all()))
            return qs.none()

    # ── LEGACY ROLE LOGIC ────────────────────────────────────────────────────
    if role == 'site_admin':
        from django.db.models import Q
        if hasattr(qs.model, 'site'):
            return qs.filter(site=employee.site)
        if hasattr(qs.model, 'employee'):
            return qs.filter(Q(employee__site=employee.site) | Q(employee__enrolled_sites=employee.site)).distinct()
        if qs.model.__name__ == 'Employee':
            return qs.filter(Q(site=employee.site) | Q(enrolled_sites=employee.site)).distinct()

    if role in ('hr', 'manager'):
        if hasattr(qs.model, 'entity'):
            return qs.filter(entity=employee.entity)
        if hasattr(qs.model, 'department'):
            return qs.filter(department__entity=employee.entity)
        if hasattr(qs.model, 'employee'):
            return qs.filter(employee__entity=employee.entity)
        if qs.model.__name__ == 'Employee':
            return qs.filter(entity=employee.entity)

    # ── DEFAULT: employee sees only their own records ────────────────────────
    if hasattr(qs.model, 'employee'):
        return qs.filter(employee=employee)
    elif qs.model.__name__ == 'Employee':
        return qs.filter(id=employee.id)
    elif qs.model.__name__ == 'Site':
        from django.db.models import Q
        return qs.model.objects.filter(Q(id=employee.site_id) | Q(id__in=employee.enrolled_sites.all()))

    return qs.none()


# ---------------------------------------------------------------------------
# ViewSet Mixin
# ---------------------------------------------------------------------------

class DataIsolationMixin:
    """
    Mixin for ViewSets to enforce RBAC data isolation.

    Usage (always put FIRST in the inheritance chain):
        class MyViewSet(DataIsolationMixin, viewsets.ModelViewSet):
            queryset = MyModel.objects.all()
            ...

    The underlying model should have at least one of:
      - a `site` FK       → used for site-level isolation
      - an `employee` FK  → used for employee-level isolation
      - an `organization` FK
      - an `entity` FK

    If none of these exist, non-superusers will receive an empty queryset.
    """
    def get_queryset(self):
        qs = super().get_queryset()
        request = getattr(self, 'request', None)
        if request is None or not request.user.is_authenticated:
            return qs.none()
        return isolate_queryset(qs, request.user)

# ---------------------------------------------------------------------------
# Dynamic CRUD Permission
# ---------------------------------------------------------------------------

class DynamicCRUDPermission(permissions.BasePermission):
    """
    Enforces strict backend CRUD boundaries based on dynamic_role.permissions.
    Only checks if the view defines an `rbac_module` (e.g. `rbac_module = 'Employees'`).
    """
    def has_permission(self, request, view):
        # 1. Bypass if unauthenticated
        if not request.user or not request.user.is_authenticated:
            return False
            
        # 2. Super admins bypass all
        if request.user.is_superuser:
            return True
            
        employee = getattr(request.user, 'employee_profile', None)
        if employee and employee.role == 'super_admin':
            return True
            
        # 3. If view doesn't define rbac_module, don't enforce dynamic CRUD here (let other permissions handle it)
        rbac_module = getattr(view, 'rbac_module', None)
        if not rbac_module:
            return True
            
        # 4. If no employee or no dynamic role, they can't access an rbac_module protected view
        if not employee or not employee.dynamic_role or not employee.dynamic_role.permissions:
            return False
            
        # 5. Extract module permissions (fallback to empty)
        module_perms = employee.dynamic_role.permissions.get(rbac_module, {})
        
        # 6. Map request method to Create/Read/Update/Delete
        method = request.method
        if method in ['GET', 'HEAD', 'OPTIONS']:
            view_perm = module_perms.get('view')
            return view_perm in [True, 'self', 'selected_entities']
        elif method == 'POST':
            return module_perms.get('create') is True
        elif method in ['PUT', 'PATCH']:
            return module_perms.get('update') is True
        elif method == 'DELETE':
            return module_perms.get('delete') is True
            
        return False
