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
      1. user.email matches Site.contact_email
      2. employee.role == 'site_admin' -> employee.site and employee.enrolled_sites
    """
    from organisation.models import Site
    from django.db.models import Q

    admin_sites_by_email = Site.objects.filter(contact_email=user.email)
    
    employee = getattr(user, 'employee_profile', None)
    if employee and employee.role == 'site_admin':
        site_ids = list(admin_sites_by_email.values_list('id', flat=True))
        if employee.site_id:
            site_ids.append(employee.site_id)
        if employee.enrolled_sites.exists():
            site_ids.extend(employee.enrolled_sites.values_list('id', flat=True))
        
        if site_ids:
            return Site.objects.filter(id__in=set(site_ids))

    if admin_sites_by_email.exists():
        return admin_sites_by_email

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

    if user.is_superuser:
        return qs

    employee = getattr(user, 'employee_profile', None)

    if employee and employee.role == 'super_admin':
        return qs

    if qs.model.__name__ == 'Holiday':
        from django.db.models import Q
        if employee and hasattr(employee, 'organization') and employee.organization:
            return qs.filter(Q(site__organization=employee.organization) | Q(site__isnull=True)).distinct()
        if employee and employee.site:
            return qs.filter(Q(site=employee.site) | Q(site__isnull=True)).distinct()
        return qs.filter(site__isnull=True).distinct()

    # ── MULTI-TENANT BOUNDARY: apply organisation scope first ────────────────
    # If the user is an org_admin, they shouldn't be restricted by admin_sites
    if employee and employee.role in ('admin', 'org_admin'):
        if hasattr(employee, 'organization') and employee.organization:
            from django.db.models import Q
            if hasattr(qs.model, 'employee'):
                qs = qs.filter(employee__organization=employee.organization)
            elif hasattr(qs.model, 'organization'):
                org_field = qs.model._meta.get_field('organization')
                if org_field.is_relation and org_field.related_model.__name__ == 'Entity':
                    qs = qs.filter(organization__organization=employee.organization)
                else:
                    qs = qs.filter(organization=employee.organization)
            elif qs.model.__name__ == 'Employee':
                qs = qs.filter(organization=employee.organization)
            elif hasattr(qs.model, 'entity'):
                qs = qs.filter(entity__organization=employee.organization)
            elif hasattr(qs.model, 'department'):
                qs = qs.filter(department__entity__organization=employee.organization)
            elif hasattr(qs.model, 'structure'):
                qs = qs.filter(structure__site__organization=employee.organization)
            elif qs.model.__name__ == 'SalaryStructure':
                qs = qs.filter(site__organization=employee.organization)
            return qs

    # ── SITE ADMIN ───────────────────────────────────────────────────────────
    admin_sites = _get_admin_sites(user)
    if admin_sites.exists():
        from django.db.models import Q
        if hasattr(qs.model, 'site') and qs.model.__name__ not in ['Site', 'Employee']:
            return qs.filter(site__in=admin_sites)
        if hasattr(qs.model, 'employee'):
            return qs.filter(Q(employee__site__in=admin_sites) | Q(employee__enrolled_sites__in=admin_sites)).distinct()
        if qs.model.__name__ == 'Employee':
            return qs.filter(Q(site__in=admin_sites) | Q(enrolled_sites__in=admin_sites)).distinct()
            
        # Restrict structural data (Orgs, Entities, Branches, Departments, Sites) to the Organization
        org_ids = admin_sites.values_list('organization_id', flat=True).distinct()

        if qs.model.__name__ == 'Site':
            return qs.filter(id__in=admin_sites.values_list('id', flat=True))
        if qs.model.__name__ == 'Organization':
            return qs.filter(id__in=org_ids)
        if qs.model.__name__ == 'Entity':
            return qs.filter(organization_id__in=org_ids)
        if qs.model.__name__ == 'Branch':
            return qs.filter(entity__organization_id__in=org_ids)
        if qs.model.__name__ == 'Department':
            return qs.filter(entity__organization_id__in=org_ids)
        if qs.model.__name__ == 'Role':
            return qs.filter(organization_id__in=org_ids)
        if qs.model.__name__ == 'Designation':
            return qs.filter(department__entity__organization_id__in=org_ids)
            
        if hasattr(qs.model, 'organization'):
            org_field = qs.model._meta.get_field('organization')
            if org_field.is_relation and org_field.related_model.__name__ == 'Entity':
                return qs.filter(organization__organization_id__in=org_ids)
            else:
                return qs.filter(organization_id__in=org_ids)
        if hasattr(qs.model, 'entity'):
            return qs.filter(entity__organization_id__in=org_ids)
        if hasattr(qs.model, 'department'):
            return qs.filter(department__entity__organization_id__in=org_ids)
        if hasattr(qs.model, 'structure'):
            return qs.filter(structure__site__in=admin_sites)
        if qs.model.__name__ == 'SalaryStructure':
            return qs.filter(site__in=admin_sites)

        return qs.none()

    # ── NO EMPLOYEE PROFILE → DENY ───────────────────────────────────────────
    if not employee:
        return qs.none()

    role = employee.role
    dynamic_role = getattr(employee, 'dynamic_role', None)

    # ── MULTI-TENANT BOUNDARY: apply organisation scope first ────────────────
    # Every query from this point is bounded by employee.organization.
    if hasattr(employee, 'organization') and employee.organization:
        from django.db.models import Q
        # If the model has an employee field, it's safest to scope by employee's organization
        # to prevent missing records if intermediate entities lack an organization link.
        if hasattr(qs.model, 'employee'):
            qs = qs.filter(employee__organization=employee.organization)
        elif hasattr(qs.model, 'organization'):
            org_field = qs.model._meta.get_field('organization')
            if org_field.is_relation and org_field.related_model.__name__ == 'Entity':
                qs = qs.filter(organization__organization=employee.organization)
            else:
                qs = qs.filter(organization=employee.organization)
        elif qs.model.__name__ == 'Employee':
            qs = qs.filter(organization=employee.organization)
        elif hasattr(qs.model, 'entity'):
            qs = qs.filter(entity__organization=employee.organization)
        elif hasattr(qs.model, 'department'):
            qs = qs.filter(department__entity__organization=employee.organization)
        elif hasattr(qs.model, 'structure'):
            qs = qs.filter(structure__site__organization=employee.organization)
        elif qs.model.__name__ == 'SalaryStructure':
            qs = qs.filter(site__organization=employee.organization)

    # ── DYNAMIC ROLE SCOPING ─────────────────────────────────────────────────
    has_org_access = False
    custom_allowed = []
    if dynamic_role:
        if dynamic_role.access_scope in ['Corporate', 'Region', 'Custom'] or dynamic_role.cross_department_access:
            has_org_access = True
            if dynamic_role.access_scope == 'Custom':
                custom_allowed = dynamic_role.permissions.get('allowed_entities', [])

    if dynamic_role:
        if has_org_access:
            if dynamic_role.access_scope == 'Corporate' or dynamic_role.cross_department_access:
                return qs

            if custom_allowed:
                if hasattr(qs.model, 'entity'):
                    return qs.filter(entity_id__in=custom_allowed)
                if hasattr(qs.model, 'department'):
                    return qs.filter(department__entity_id__in=custom_allowed)
                if hasattr(qs.model, 'employee'):
                    return qs.filter(employee__entity_id__in=custom_allowed)
                if hasattr(qs.model, 'structure'):
                    return qs.filter(structure__site__entity_id__in=custom_allowed)
                if qs.model.__name__ == 'SalaryStructure':
                    return qs.filter(site__entity_id__in=custom_allowed)
                if qs.model.__name__ == 'Employee':
                    return qs.filter(entity_id__in=custom_allowed)

            if hasattr(qs.model, 'entity'):
                return qs.filter(entity=employee.entity) if employee.entity else qs
            if hasattr(qs.model, 'department'):
                return qs.filter(department__entity=employee.entity) if employee.entity else qs
            if hasattr(qs.model, 'employee'):
                return qs.filter(employee__entity=employee.entity) if employee.entity else qs
            if hasattr(qs.model, 'structure'):
                return qs.filter(structure__site__organization=employee.organization) if employee.organization else qs
            if qs.model.__name__ == 'SalaryStructure':
                return qs.filter(site__organization=employee.organization) if employee.organization else qs
            if qs.model.__name__ == 'Employee':
                return qs.filter(entity=employee.entity)
        else:
            # Scoped to individual employee only
            if hasattr(qs.model, 'employee'):
                return qs.filter(employee=employee)
            elif qs.model.__name__ == 'Employee':
                return qs.filter(id=employee.id)
            elif hasattr(qs.model, 'structure'):
                return qs.filter(structure__site=employee.site) if employee.site else qs
            elif qs.model.__name__ == 'SalaryStructure':
                return qs.filter(site=employee.site) if employee.site else qs
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
        from django.db.models import Q
        
        # Build filter for organization and site
        manager_org = employee.organization_id
        manager_site = employee.site_id
        
        # If manager doesn't have an org/site, fallback to entity
        if not manager_org or not manager_site:
            if hasattr(qs.model, 'entity'):
                return qs.filter(entity=employee.entity)
            if hasattr(qs.model, 'department'):
                return qs.filter(department__entity=employee.entity)
            if hasattr(qs.model, 'employee'):
                return qs.filter(employee__entity=employee.entity)
            if hasattr(qs.model, 'structure'):
                return qs.filter(structure__site__entity=employee.entity)
            if qs.model.__name__ == 'SalaryStructure':
                return qs.filter(site__entity=employee.entity)
            if qs.model.__name__ == 'Employee':
                return qs.filter(entity=employee.entity)
                
        # Filter by org and site
        if hasattr(qs.model, 'site') and hasattr(qs.model, 'organization'):
            return qs.filter(organization_id=manager_org, site_id=manager_site)
        if hasattr(qs.model, 'site'):
            return qs.filter(site_id=manager_site)
        if hasattr(qs.model, 'employee'):
            return qs.filter(employee__organization_id=manager_org, employee__site_id=manager_site)
        if qs.model.__name__ == 'Employee':
            return qs.filter(organization_id=manager_org, site_id=manager_site)

    # ── DEFAULT: employee sees only their own records (and their site's structural data) ────────────────────────
    if hasattr(qs.model, 'employee'):
        from django.db.models import Q
        return qs.filter(Q(employee=employee) | Q(employee__manager=employee)).distinct()
    
    # Allow seeing colleagues in the same site
    if qs.model.__name__ == 'Employee':
        from django.db.models import Q
        site_filter = Q(site=employee.site) if employee.site else Q(id=employee.id)
        if employee.enrolled_sites.exists():
            site_filter |= Q(site__in=employee.enrolled_sites.all())
        return qs.filter(site_filter).distinct()
        
    if qs.model.__name__ == 'Site':
        from django.db.models import Q
        return qs.model.objects.filter(Q(id=employee.site_id) | Q(id__in=employee.enrolled_sites.all())).distinct()

    # Allow seeing structural data related to their site's entity
    if employee.site and employee.site.branch:
        entity = employee.site.branch.entity
        if qs.model.__name__ == 'Organization':
            return qs.filter(id=entity.organization_id)
        if qs.model.__name__ == 'Entity':
            return qs.filter(id=entity.id)
        if qs.model.__name__ == 'Branch':
            return qs.filter(entity=entity)
        if qs.model.__name__ == 'Department':
            return qs.filter(entity=entity)
            
        if hasattr(qs.model, 'site'):
            from django.db.models import Q
            site_filter = Q(site=employee.site) if employee.site else Q(id=0)
            if employee.enrolled_sites.exists():
                site_filter |= Q(site__in=employee.enrolled_sites.all())
            
            if hasattr(qs.model, 'organization'):
                site_filter |= Q(site__isnull=True, organization=entity.organization)
            elif hasattr(qs.model, 'entity'):
                site_filter |= Q(site__isnull=True, entity=entity)
            else:
                site_filter |= Q(site__isnull=True)
                
            return qs.filter(site_filter).distinct()
            
        if hasattr(qs.model, 'organization'):
            return qs.filter(organization=entity.organization)
        if hasattr(qs.model, 'entity'):
            return qs.filter(entity=entity)
        if hasattr(qs.model, 'department'):
            return qs.filter(department__entity=entity)

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

    def create(self, request, *args, **kwargs):
        """
        Intercept creation to auto-assign the user's isolated scope (Site/Entity/Org) 
        if the frontend didn't provide it. This prevents records from 'disappearing' 
        due to missing scope fields triggering isolation filters.
        """
        if request.user.is_authenticated and not request.user.is_superuser:
            model = self.get_queryset().model
            from organisation.models import Site
            
            target_site = None
            target_org = None
            target_entity = None
            
            employee = getattr(request.user, 'employee_profile', None)
            admin_sites = Site.objects.filter(contact_email=request.user.email)
            
            if admin_sites.exists():
                site = admin_sites.first()
                target_site = site.id
                target_org = site.organization_id
                target_entity = site.branch.entity_id if site.branch else None
            elif employee:
                target_site = employee.site_id
                target_org = employee.organization_id
                target_entity = employee.entity_id
                
            if target_org or target_site or target_entity:
                if hasattr(request.data, 'copy'):
                    mutable_data = request.data.copy()
                else:
                    mutable_data = dict(request.data)
                    
                modified = False
                if hasattr(model, 'site') and not mutable_data.get('site') and target_site:
                    mutable_data['site'] = target_site
                    modified = True
                if hasattr(model, 'organization') and not mutable_data.get('organization'):
                    org_field = model._meta.get_field('organization')
                    if org_field.is_relation and org_field.related_model.__name__ == 'Entity':
                        if target_entity:
                            mutable_data['organization'] = target_entity
                            modified = True
                    elif target_org:
                        mutable_data['organization'] = target_org
                        modified = True
                if hasattr(model, 'entity') and not mutable_data.get('entity') and target_entity:
                    mutable_data['entity'] = target_entity
                    modified = True
                    
                if modified:
                    serializer = self.get_serializer(data=mutable_data)
                    serializer.is_valid(raise_exception=True)
                    self.perform_create(serializer)
                    from rest_framework.response import Response
                    from rest_framework import status
                    headers = self.get_success_headers(serializer.data)
                    return Response(serializer.data, status=status.HTTP_201_CREATED, headers=headers)
                    
        return super().create(request, *args, **kwargs)

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
        # Bypass for superadmins
        if request.user.is_superuser:
            return True
        employee = getattr(request.user, 'employee_profile', None)
        if employee and employee.role == 'super_admin':
            return True
        # 3. If view doesn't define rbac_module, don't enforce dynamic CRUD here (let other permissions handle it)
        rbac_module = getattr(view, 'rbac_module', None)
        if not rbac_module:
            return True
            
        # 4. Extract module permissions
        module_perms = {}
        from organisation.models import Site
        site = Site.objects.filter(contact_email=request.user.email).first()
        if site:
            if site.modules:
                for mod in site.modules:
                    mod_name = mod if isinstance(mod, str) else mod.get('name', '')
                    if mod_name == rbac_module:
                        module_perms = {'view': True, 'create': True, 'update': True, 'delete': True}
                        break
        elif employee and employee.dynamic_role and employee.dynamic_role.permissions:
            module_perms = employee.dynamic_role.permissions.get(rbac_module, {})
                            
        # If no permissions found, deny
        if not module_perms:
            return False
        
        # 6. Map request method to Create/Read/Update/Delete
        method = request.method
        if method in ['GET', 'HEAD', 'OPTIONS']:
            view_perm = module_perms.get('view')
            return view_perm in [True, 'self', 'selected_entities']
        elif method == 'POST':
            return module_perms.get('create') is True
        elif method in ['PUT', 'PATCH']:
            # We will allow the request to proceed to has_object_permission
            # if they are a manager. We'll enforce the strict check there.
            if module_perms.get('update') is True:
                return True
            if employee:
                from employees.models import Employee
                if Employee.objects.filter(manager=employee).exists():
                    return True
            return False
        elif method == 'DELETE':
            return module_perms.get('delete') is True
            
        return False

    def has_object_permission(self, request, view, obj):
        if request.user.is_superuser:
            return True
        employee = getattr(request.user, 'employee_profile', None)
        if employee and employee.role == 'super_admin':
            return True

        # Check if they are updating a reportee's object
        method = request.method
        if method in ['PUT', 'PATCH'] and employee and hasattr(obj, 'employee'):
            if getattr(obj.employee, 'manager_id', None) == employee.id:
                return True
                
        # Otherwise fallback to the module permissions
        rbac_module = getattr(view, 'rbac_module', None)
        if not rbac_module:
            return True
            
        module_perms = {}
        from organisation.models import Site
        site = Site.objects.filter(contact_email=request.user.email).first()
        if site:
            if site.modules:
                for mod in site.modules:
                    mod_name = mod if isinstance(mod, str) else mod.get('name', '')
                    if mod_name == rbac_module:
                        module_perms = {'view': True, 'create': True, 'update': True, 'delete': True}
                        break
        elif employee and employee.dynamic_role and employee.dynamic_role.permissions:
            module_perms = employee.dynamic_role.permissions.get(rbac_module, {})
            
        if method in ['PUT', 'PATCH']:
            return module_perms.get('update') is True
        elif method == 'DELETE':
            return module_perms.get('delete') is True
            
        return True
