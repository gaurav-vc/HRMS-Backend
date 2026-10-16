from rest_framework import permissions


def _is_truthy(val):
    return val in (True, 'true', 'True', 1, '1')


def _has_view_perm(val):
    return val in (True, 'true', 'True', 1, '1', 'self', 'selected_entities')


def check_user_permission(user, permission_name):
    """
    Dynamically checks whether `user` holds a specific permission toggle
    (e.g., 'can_run_payroll', 'can_view_confidential_payroll', 'can_approve_payroll',
           'can_release_salary', 'can_add_ctc').
    
    Order of precedence:
      1. Django Superuser -> Always True
      2. Super Admin role -> True
      3. Dynamic Role Permissions -> Evaluated in real-time from Role.permissions JSON
    """
    if not user or not user.is_authenticated:
        return False
    # Strict boundary: Superuser does not hold site-level operational permissions
    if user.is_superuser:
        return False
    emp = getattr(user, 'employee_profile', None)
    if not emp or emp.role == 'super_admin':
        return False
    if emp.dynamic_role and emp.dynamic_role.permissions:
        val = emp.dynamic_role.permissions.get(permission_name)
        return _is_truthy(val)
    return False


def check_module_permission(user, module_name, action='view'):
    """
    Dynamically checks whether `user` has 'view', 'create', 'update', or 'delete'
    for a given module (e.g., 'Entities', 'Sites', 'Employees', 'Salary Structure', etc.).
    """
    if not user or not user.is_authenticated:
        return False
    # Strict boundary: Superuser is only allowed on Super Admin platform modules
    if user.is_superuser:
        return module_name in ['Sites', 'Organizations', 'Billing']
    emp = getattr(user, 'employee_profile', None)
    if emp and emp.role == 'super_admin':
        return module_name in ['Sites', 'Organizations', 'Billing']

    # Check site modules if user is site contact
    from organisation.models import Site
    site = Site.objects.filter(contact_email=user.email).first()
    if site and site.modules:
        for mod in site.modules:
            mod_name = mod if isinstance(mod, str) else mod.get('name', '')
            if mod_name == module_name:
                return True

    if emp and emp.dynamic_role and emp.dynamic_role.permissions:
        perms = emp.dynamic_role.permissions
        mod_perm = perms.get(module_name)
        if isinstance(mod_perm, dict):
            val = mod_perm.get(action)
            if action == 'view':
                return _has_view_perm(val)
            return _is_truthy(val)

    return False


def user_can_approve(user, module=None):
    """
    Dynamically determines if `user` has approval privileges.
    NOT hardcoded to static roles like HR or Admin.
    Dynamically checks:
      1. Dynamic role's can_approve boolean field (Role.can_approve)
      2. Dynamic role's special permission toggles:
         - 'can_approve' in perms
         - 'can_approve_payroll' in perms
         - 'can_approve_leaves' in perms
      3. Dynamic role module-level permissions:
         - perms[module]['update'] or perms[module]['approve']
      4. Dynamic cross-module payroll approval flags
      5. Admin/Org Admin/Site Admin role fallback
    Returns True if authorized, False otherwise.
    """
    if not user or not user.is_authenticated:
        return False
    if user.is_superuser:
        return False  # Platform superusers cannot approve site operations
        
    emp = getattr(user, 'employee_profile', None)
    if not emp:
        return False

    # 1. Custom Dynamic Role permissions (primary source of truth)
    if emp.dynamic_role:
        role = emp.dynamic_role
        # Model-level approval toggle (Role.can_approve)
        if getattr(role, 'can_approve', False):
            return True

        # Special permission toggles in role's permissions dictionary
        perms = role.permissions or {}
        if any(_is_truthy(perms.get(k)) for k in ['can_approve', 'can_approve_payroll', 'can_approve_leaves']):
            return True

        # Module-specific permissions
        if module and module in perms:
            m_perm = perms.get(module)
            if isinstance(m_perm, dict) and (_is_truthy(m_perm.get('approve')) or _is_truthy(m_perm.get('update'))):
                return True

        # For payroll module aliases
        if module in ['Payroll', 'Run Payroll', 'Payroll Overview']:
            if _is_truthy(perms.get('can_approve_payroll')):
                return True
            p_perm = perms.get('Payroll') or perms.get('Run Payroll')
            if isinstance(p_perm, dict) and (_is_truthy(p_perm.get('approve')) or _is_truthy(p_perm.get('update'))):
                return True

    # 2. Administrative roles fallback
    if emp.role in ['admin', 'org_admin', 'site_admin']:
        return True

    return False


class BaseRolePermission(permissions.BasePermission):
    allowed_roles = []

    def has_permission(self, request, view):
        if not request.user or not request.user.is_authenticated:
            return False

        # Superuser is strictly allowed ONLY on views requiring super_admin
        if request.user.is_superuser:
            return 'super_admin' in self.allowed_roles

        # Explicit action-level dynamic approval check
        action_name = getattr(view, 'action', None)
        rbac_module = getattr(view, 'rbac_module', None)
        if action_name in ['approve', 'reject', 'approve_override']:
            return user_can_approve(request.user, module=rbac_module)

        employee = getattr(request.user, 'employee_profile', None)

        from organisation.models import Site
        site = None
        if employee and employee.site_id:
            site = employee.site
        if not site:
            site = Site.objects.filter(contact_email=request.user.email).first()
        if not site and employee and employee.enrolled_sites.exists():
            site = employee.enrolled_sites.first()

        # Strict site module boundary: If site has modules configured, rbac_module must be allowed
        if rbac_module and site and site.modules is not None:
            allowed_mods = set()
            for m in site.modules:
                allowed_mods.add(m if isinstance(m, str) else m.get('name', ''))
            if 'Sub Sites' in allowed_mods:
                allowed_mods.add('Sites')
            if 'Sites' in allowed_mods:
                allowed_mods.add('Sub Sites')

            if rbac_module not in allowed_mods:
                return False

        admin_sites = Site.objects.filter(contact_email=request.user.email)
        if admin_sites.exists():
            if 'site_admin' in self.allowed_roles:
                return True
            # For Site Admins accessing HR features like Payroll, grant access if module is enabled
            rbac_aliases = [rbac_module] if rbac_module else []
            if rbac_module == 'Sites':
                rbac_aliases.append('Sub Sites')
            elif rbac_module == 'Sub Sites':
                rbac_aliases.append('Sites')

            for s in admin_sites:
                if s.modules:
                    if rbac_aliases and any((m if isinstance(m, str) else m.get('name', '')) in rbac_aliases for m in s.modules):
                        return True
                    if any((m if isinstance(m, str) else m.get('name', '')) in ['Payroll', 'Payroll Overview', 'Run Payroll', 'Salary Structure', 'Import CTC'] for m in s.modules):
                        return True
            if 'site_admin' not in self.allowed_roles:
                pass  # fall through to employee check

        if not employee:
            return False

        if employee.role == 'super_admin':
            return 'super_admin' in self.allowed_roles

        if employee.role in ('admin', 'org_admin'):
            if self.allowed_roles != ['super_admin']:
                return True

        if employee.dynamic_role and employee.dynamic_role.permissions:
            perms = employee.dynamic_role.permissions

            # 1. Check view's rbac_module against dynamic role permissions
            mod_perm = None
            if rbac_module and rbac_module in perms:
                mod_perm = perms.get(rbac_module)
            elif rbac_module == 'Sites' and 'Sub Sites' in perms:
                mod_perm = perms.get('Sub Sites')
            elif rbac_module == 'Sub Sites' and 'Sites' in perms:
                mod_perm = perms.get('Sites')

            if mod_perm and isinstance(mod_perm, dict):
                method = request.method
                if method in ['GET', 'HEAD', 'OPTIONS']:
                    if _has_view_perm(mod_perm.get('view')):
                        return True
                elif method == 'POST':
                    if _is_truthy(mod_perm.get('create')):
                        return True
                elif method in ['PUT', 'PATCH']:
                    if _is_truthy(mod_perm.get('update')):
                        return True
                elif method == 'DELETE':
                    if _is_truthy(mod_perm.get('delete')):
                        return True

            # 2. Special Workflow Permissions for Payroll and HR views
            payroll_modules = ['Run Payroll', 'Payroll Overview', 'Salary Structure', 'Import CTC', 'Salary Slips', 'Compliance']
            if rbac_module in payroll_modules or 'hr' in self.allowed_roles:
                if any(_is_truthy(perms.get(k)) for k in ['can_run_payroll', 'can_view_confidential_payroll', 'can_approve_payroll', 'can_approve']):
                    return True

            # 3. Dynamic approval privilege for customized roles
            if getattr(employee.dynamic_role, 'can_approve', False) or any(_is_truthy(perms.get(k)) for k in ['can_approve', 'can_approve_payroll', 'can_approve_leaves']):
                if any(r in self.allowed_roles for r in ['manager', 'hr', 'site_admin']):
                    return True

            if 'site_admin' in self.allowed_roles and employee.dynamic_role.access_scope in ['Site', 'Location']:
                return True

        return employee.role in self.allowed_roles


class IsSuperAdmin(BaseRolePermission):
    allowed_roles = ['super_admin']


class IsOrgAdmin(BaseRolePermission):
    allowed_roles = ['org_admin']


class IsSiteAdmin(BaseRolePermission):
    allowed_roles = ['org_admin', 'site_admin']


class IsHR(BaseRolePermission):
    allowed_roles = ['org_admin', 'hr']


class IsManager(BaseRolePermission):
    allowed_roles = ['org_admin', 'hr', 'manager']


class IsEmployee(BaseRolePermission):
    allowed_roles = ['org_admin', 'site_admin', 'hr', 'manager', 'employee']


# ---------------------------------------------------------------------------
# Helper
# ---------------------------------------------------------------------------

def _get_tenant_site(user):
    """
    Returns the primary Main Site (created in Super Admin Sites with is_sub_site=False)
    that acts as the root multi-tenant boundary for `user`.
    """
    if not user or not user.is_authenticated or user.is_superuser:
        return None

    from organisation.models import Site

    # 1. Direct contact email match for Main Site (Super Admin Site)
    main_site = Site.objects.filter(contact_email=user.email, is_sub_site=False).first()
    if main_site:
        return main_site

    # 2. Match via employee profile
    employee = getattr(user, 'employee_profile', None)
    if employee:
        # Check employee's primary site
        if employee.site:
            if not employee.site.is_sub_site:
                return employee.site
            # If assigned to a sub-site, find parent main site
            enrolled_main = employee.enrolled_sites.filter(is_sub_site=False).first()
            if enrolled_main:
                return enrolled_main
            if employee.site.branch:
                branch_main = Site.objects.filter(branch=employee.site.branch, is_sub_site=False).first()
                if branch_main:
                    return branch_main
            if employee.site.organization:
                org_main = Site.objects.filter(organization=employee.site.organization, is_sub_site=False).first()
                if org_main:
                    return org_main
            return employee.site

        # Check enrolled sites for main site
        enrolled_main = employee.enrolled_sites.filter(is_sub_site=False).first()
        if enrolled_main:
            return enrolled_main

    # 3. Fallback: any site matching contact email
    return Site.objects.filter(contact_email=user.email).first()


def _get_tenant_scope(user):
    """
    Returns (all_tenant_site_ids, tenant_branch_ids, tenant_entity_ids, tenant_site)
    for strict multi-tenant boundary enforcement.
    """
    from organisation.models import Site, Branch, Entity
    from django.db.models import Q

    tenant_site = _get_tenant_site(user)
    if not tenant_site:
        return set(), set(), set(), None

    all_site_ids = {tenant_site.id}

    # Include all sub-sites belonging strictly to this tenant site:
    # 1. Any sub-site with the same branch as tenant_site
    if tenant_site.branch_id:
        sub_branch_sites = Site.objects.filter(branch_id=tenant_site.branch_id, is_sub_site=True).values_list('id', flat=True)
        all_site_ids.update(sub_branch_sites)
    
    # 2. Any sub-site created by / administered by the same contact_email
    if tenant_site.contact_email:
        sub_contact_sites = Site.objects.filter(contact_email=tenant_site.contact_email, is_sub_site=True).values_list('id', flat=True)
        all_site_ids.update(sub_contact_sites)

    # 3. Any sub-site enrolled in the admin employee's enrolled_sites
    employee = getattr(user, 'employee_profile', None)
    if employee and employee.enrolled_sites.exists():
        enrolled_subs = employee.enrolled_sites.filter(is_sub_site=True).values_list('id', flat=True)
        all_site_ids.update(enrolled_subs)

    # 4. Any sub-site belonging to this site's organization
    if tenant_site.organization_id:
        org_sub_sites = Site.objects.filter(organization_id=tenant_site.organization_id, is_sub_site=True).values_list('id', flat=True)
        all_site_ids.update(org_sub_sites)

    # Entity IDs - 100% dynamic, multi-tenant isolated via Organization & Branch relations
    entity_ids = set()
    if tenant_site.organization_id:
        org_entities = Entity.objects.filter(organization_id=tenant_site.organization_id).values_list('id', flat=True)
        entity_ids.update(org_entities)
    if employee and employee.entity_id:
        entity_ids.add(employee.entity_id)
    if tenant_site.branch and tenant_site.branch.entity_id:
        entity_ids.add(tenant_site.branch.entity_id)

    # Branch IDs - 100% dynamic from tenant entities and site/employee assignments
    branch_ids = set()
    if entity_ids:
        ent_branches = Branch.objects.filter(entity_id__in=entity_ids).values_list('id', flat=True)
        branch_ids.update(ent_branches)
    if tenant_site.branch_id:
        branch_ids.add(tenant_site.branch_id)
    site_branch_ids = Site.objects.filter(id__in=all_site_ids, branch__isnull=False).values_list('branch_id', flat=True)
    branch_ids.update(site_branch_ids)
    if employee and employee.branch_id:
        branch_ids.add(employee.branch_id)

    return all_site_ids, branch_ids, entity_ids, tenant_site


def _get_admin_sites(user):
    """
    Return a queryset of Sites that `user` administers, strictly bounded to their tenant.
    """
    from organisation.models import Site
    all_site_ids, _, _, _ = _get_tenant_scope(user)
    if all_site_ids:
        return Site.objects.filter(id__in=all_site_ids)
    return Site.objects.none()


# ---------------------------------------------------------------------------
# Core isolation function
# ---------------------------------------------------------------------------

def get_reporting_persons(employee):
    """
    Returns a list of active Employees who are designated reporting person(s)
    for this employee, based on:
    1. Direct reporting manager (employee.manager)
    2. Role-based reporting person from Settings: employee.dynamic_role.reporting_to
       Scoped to the employee's site or entity!
    """
    reporters = []
    if not employee:
        return reporters

    from employees.models import Employee
    from django.db.models import Q

    # 1. Direct manager
    if getattr(employee, 'manager', None) and employee.manager.status == 'Active':
        reporters.append(employee.manager)

    # 2. Role-based reporting person from Settings (employee.dynamic_role.reporting_to)
    if getattr(employee, 'dynamic_role', None) and employee.dynamic_role.reporting_to:
        target_role = employee.dynamic_role.reporting_to
        qs = Employee.objects.filter(dynamic_role=target_role, status='Active')
        if employee.site_id:
            site_candidates = list(qs.filter(Q(site_id=employee.site_id) | Q(enrolled_sites__id=employee.site_id)).distinct())
            if site_candidates:
                reporters.extend(site_candidates)
            elif employee.entity_id:
                ent_candidates = list(qs.filter(entity_id=employee.entity_id))
                reporters.extend(ent_candidates if ent_candidates else list(qs))
            else:
                reporters.extend(list(qs))
        elif employee.entity_id:
            ent_candidates = list(qs.filter(entity_id=employee.entity_id))
            reporters.extend(ent_candidates if ent_candidates else list(qs))
        else:
            reporters.extend(list(qs))

    # Deduplicate while preserving order
    seen = set()
    result = []
    for r in reporters:
        if r.id not in seen:
            seen.add(r.id)
            result.append(r)
    return result


def isolate_queryset(qs, user):
    """
    Filters `qs` so that `user` only sees records they are authorised to access.
    Enforces a strict multi-tenant boundary where Main Sites created in Super Admin
    never leak data between each other, AND enforces role-level data scoping:
    - 'Self': Self data only.
    - 'Location' / 'Site': Their assigned location / site.
    - 'Corporate': All data of the entities in their tenant.
    - 'Custom': Only selected entities configured in permissions['allowed_entities'].
    100% dynamic - no hardcoded values.
    """
    if not user.is_authenticated:
        return qs.none()

    # Strict security boundary: Superuser is only responsible for Super Admin platform data
    # (Organization, Invoice, top-level client Sites). They must NEVER see any site's operational data.
    is_super = bool(
        user.is_superuser or 
        (hasattr(user, 'employee_profile') and user.employee_profile and user.employee_profile.role == 'super_admin') or
        (hasattr(user, 'groups') and user.groups.filter(name='Super Admin').exists())
    )
    if is_super:
        model_name = qs.model.__name__
        if model_name in ('Organization', 'Invoice', 'Site'):
            return qs
        return qs.none()

    employee = getattr(user, 'employee_profile', None)

    # Resolve strict tenant scope for user dynamically (multi-tenant outer envelope)
    all_tenant_site_ids, tenant_branch_ids, tenant_entity_ids, tenant_site = _get_tenant_scope(user)

    from django.db.models import Q

    if not employee:
        # User without employee profile (e.g. initial contact user)
        if all_tenant_site_ids:
            if qs.model.__name__ == 'Site':
                return qs.filter(id__in=all_tenant_site_ids)
            if hasattr(qs.model, 'site'):
                return qs.filter(site_id__in=all_tenant_site_ids)
        return qs.none()

    # ── DETERMINE USER ROLE AND ACCESS SCOPE ───────────────────────────────────
    role = employee.role
    dynamic_role = getattr(employee, 'dynamic_role', None)

    # By default, employee access scope is strictly 'Self'
    access_scope = 'Self'
    custom_allowed_entities = []

    # Dynamic detection: Site Admin and Admins ALWAYS have Corporate scope within their tenant boundary
    is_site_admin = bool(
        role in ('site_admin', 'admin') or
        (tenant_site and tenant_site.contact_email and user.email and tenant_site.contact_email.strip().lower() == user.email.strip().lower()) or
        (dynamic_role and getattr(dynamic_role, 'code', None) == 'SITE_ADMIN')
    )

    if is_site_admin:
        access_scope = 'Corporate'
    elif dynamic_role:
        raw_scope = dynamic_role.access_scope or 'Self'
        if raw_scope in ['Corporate', 'Region']:
            access_scope = 'Corporate'
        elif raw_scope in ['Location', 'Site']:
            access_scope = 'Location'
        elif raw_scope == 'Custom':
            access_scope = 'Custom'
            if dynamic_role.permissions and isinstance(dynamic_role.permissions, dict):
                custom_allowed_entities = dynamic_role.permissions.get('allowed_entities', [])
        elif dynamic_role.cross_department_access:
            access_scope = 'Corporate'
        else:
            access_scope = 'Self'
    else:
        # Standard legacy roles
        if role == 'hr':
            access_scope = 'Location'
        elif role == 'manager':
            access_scope = 'Manager'
        else:
            access_scope = 'Self'

    # ── CASE 1: SELF DATA ONLY ('Self') ──────────────────────────────────────
    if access_scope == 'Self':
        # Employees: Strictly only themselves
        if qs.model.__name__ == 'Employee':
            return qs.filter(id=employee.id)

        # Direct employee relation: Strictly only their own records
        if hasattr(qs.model, 'employee'):
            return qs.filter(employee=employee)

        # User model
        if qs.model.__name__ == 'User':
            return qs.filter(id=user.id)

        # PayrollRun: Only runs containing their own payslips
        if qs.model.__name__ == 'PayrollRun':
            return qs.filter(payslip__employee=employee).distinct()

        # Structural models: scoped to employee's own assigned structures
        if qs.model.__name__ == 'Entity':
            return qs.filter(id=employee.entity_id) if employee.entity_id else qs.none()

        if qs.model.__name__ == 'Branch':
            return qs.filter(id=employee.branch_id) if employee.branch_id else qs.none()

        if qs.model.__name__ == 'Department':
            return qs.filter(id=employee.department_id) if employee.department_id else qs.none()

        if qs.model.__name__ == 'Designation':
            return qs.filter(id=employee.designation_id) if employee.designation_id else qs.none()

        if qs.model.__name__ == 'Site':
            return qs.filter(Q(id=employee.site_id) | Q(id__in=employee.enrolled_sites.all())).distinct()

        if qs.model.__name__ == 'Role':
            return qs.filter(id=employee.dynamic_role_id) if employee.dynamic_role_id else qs.none()

        if qs.model.__name__ == 'SalaryStructure':
            if employee.salary_structure_id:
                return qs.filter(id=employee.salary_structure_id)
            if all_tenant_site_ids:
                return qs.filter(site_id__in=all_tenant_site_ids)
            return qs.none()

        if qs.model.__name__ == 'AttendancePolicy':
            if all_tenant_site_ids:
                return qs.filter(Q(site_id__in=all_tenant_site_ids) | Q(site__isnull=True, organization__isnull=True)).distinct()
            return qs.filter(site__isnull=True, organization__isnull=True).distinct()

        if qs.model.__name__ == 'Holiday':
            if all_tenant_site_ids:
                return qs.filter(Q(site_id__in=all_tenant_site_ids) | Q(site__isnull=True)).distinct()
            return qs.filter(site__isnull=True).distinct()

        if qs.model.__name__ == 'Organization':
            return qs.filter(id=employee.organization_id) if employee.organization_id else qs.none()

        if hasattr(qs.model, 'site'):
            return qs.filter(site_id=employee.site_id) if employee.site_id else qs.none()

        return qs.none()

    # ── CASE 2: MANAGER (themselves + their reportees) ───────────────────────
    if access_scope == 'Manager':
        if qs.model.__name__ == 'Employee':
            return qs.filter(Q(id=employee.id) | Q(manager=employee)).distinct()

        if hasattr(qs.model, 'employee'):
            return qs.filter(Q(employee=employee) | Q(employee__manager=employee)).distinct()

        if qs.model.__name__ == 'PayrollRun':
            return qs.filter(payslip__employee__in=[employee.id] + list(employee.reportees.values_list('id', flat=True))).distinct()

        # Follow Location/tenant scoping for structural models
        if qs.model.__name__ == 'Entity':
            return qs.filter(id__in=tenant_entity_ids) if tenant_entity_ids else (qs.filter(id=employee.entity_id) if employee.entity_id else qs.none())
        if qs.model.__name__ == 'Branch':
            return qs.filter(id__in=tenant_branch_ids) if tenant_branch_ids else (qs.filter(id=employee.branch_id) if employee.branch_id else qs.none())
        if qs.model.__name__ == 'Department':
            return qs.filter(entity_id__in=tenant_entity_ids) if tenant_entity_ids else qs.none()
        if qs.model.__name__ == 'Designation':
            return qs.filter(department__entity_id__in=tenant_entity_ids) if tenant_entity_ids else qs.none()
        if qs.model.__name__ == 'Site':
            return qs.filter(id__in=all_tenant_site_ids) if all_tenant_site_ids else qs.none()
        if qs.model.__name__ == 'SalaryStructure':
            return qs.filter(Q(site_id__in=all_tenant_site_ids) | Q(site__isnull=True))
        if qs.model.__name__ == 'AttendancePolicy':
            return qs.filter(Q(site_id__in=all_tenant_site_ids) | Q(site__isnull=True, organization__isnull=True)).distinct()
        if qs.model.__name__ == 'Holiday':
            return qs.filter(Q(site_id__in=all_tenant_site_ids) | Q(site__isnull=True)).distinct()
        if qs.model.__name__ == 'Role':
            return qs.filter(Q(site_id__in=all_tenant_site_ids) | Q(site__isnull=True, organization_id=employee.organization_id)).distinct()
        if qs.model.__name__ == 'Organization':
            return qs.filter(id=employee.organization_id) if employee.organization_id else qs.none()
        return qs.none()

    # ── CASE 3: CUSTOM ENTITIES ('Custom') ──────────────────────────────────
    if access_scope == 'Custom':
        effective_entity_ids = [eid for eid in custom_allowed_entities if not tenant_entity_ids or eid in tenant_entity_ids]

        if qs.model.__name__ == 'Entity':
            return qs.filter(id__in=effective_entity_ids)

        if qs.model.__name__ == 'Branch':
            return qs.filter(entity_id__in=effective_entity_ids)

        if qs.model.__name__ == 'Department':
            return qs.filter(entity_id__in=effective_entity_ids)

        if qs.model.__name__ == 'Designation':
            return qs.filter(department__entity_id__in=effective_entity_ids)

        if qs.model.__name__ == 'Employee':
            eq = qs.filter(entity_id__in=effective_entity_ids)
            if all_tenant_site_ids:
                eq = eq.filter(Q(site_id__in=all_tenant_site_ids) | Q(enrolled_sites__id__in=all_tenant_site_ids))
            return eq.exclude(role='super_admin').distinct()

        if hasattr(qs.model, 'employee'):
            return qs.filter(employee__entity_id__in=effective_entity_ids).distinct()

        if qs.model.__name__ == 'PayrollRun':
            return qs.filter(entity_id__in=effective_entity_ids)

        if qs.model.__name__ == 'Site':
            return qs.filter(branch__entity_id__in=effective_entity_ids, id__in=all_tenant_site_ids).distinct() if all_tenant_site_ids else qs.filter(branch__entity_id__in=effective_entity_ids)

        if qs.model.__name__ == 'SalaryStructure':
            return qs.filter(Q(site__branch__entity_id__in=effective_entity_ids) | Q(site__isnull=True))

        if qs.model.__name__ == 'AttendancePolicy':
            return qs.filter(Q(site_id__in=all_tenant_site_ids) | Q(site__isnull=True, organization__isnull=True)).distinct()

        if qs.model.__name__ == 'Holiday':
            return qs.filter(Q(site_id__in=all_tenant_site_ids) | Q(site__isnull=True)).distinct()

        if qs.model.__name__ == 'Role':
            return qs.filter(Q(site_id__in=all_tenant_site_ids) | Q(site__isnull=True, organization_id=employee.organization_id)).distinct()

        if qs.model.__name__ == 'Organization':
            return qs.filter(id=employee.organization_id) if employee.organization_id else qs.none()

        return qs.none()

    # ── CASE 4: LOCATION / SITE ('Location') ─────────────────────────────────
    if access_scope == 'Location':
        if qs.model.__name__ == 'Site':
            return qs.filter(id__in=all_tenant_site_ids) if all_tenant_site_ids else (qs.filter(id=employee.site_id) if employee.site_id else qs.none())

        if qs.model.__name__ == 'Employee':
            if all_tenant_site_ids:
                return qs.filter(
                    Q(site_id__in=all_tenant_site_ids) | Q(enrolled_sites__id__in=all_tenant_site_ids)
                ).exclude(role='super_admin').distinct()
            return qs.filter(id=employee.id)

        if hasattr(qs.model, 'employee'):
            if all_tenant_site_ids:
                return qs.filter(
                    Q(employee__site_id__in=all_tenant_site_ids) | Q(employee__enrolled_sites__id__in=all_tenant_site_ids)
                ).distinct()
            return qs.filter(employee=employee)

        if qs.model.__name__ == 'Entity':
            return qs.filter(id__in=tenant_entity_ids) if tenant_entity_ids else (qs.filter(id=employee.entity_id) if employee.entity_id else qs.none())

        if qs.model.__name__ == 'Branch':
            return qs.filter(id__in=tenant_branch_ids) if tenant_branch_ids else (qs.filter(id=employee.branch_id) if employee.branch_id else qs.none())

        if qs.model.__name__ == 'Department':
            return qs.filter(entity_id__in=tenant_entity_ids) if tenant_entity_ids else qs.none()

        if qs.model.__name__ == 'Designation':
            return qs.filter(department__entity_id__in=tenant_entity_ids) if tenant_entity_ids else qs.none()

        if qs.model.__name__ == 'PayrollRun':
            return qs.filter(entity_id__in=tenant_entity_ids) if tenant_entity_ids else qs.none()

        if qs.model.__name__ == 'Role':
            return qs.filter(Q(site_id__in=all_tenant_site_ids) | Q(site__isnull=True, organization_id=employee.organization_id)).distinct()

        if qs.model.__name__ == 'SalaryStructure':
            return qs.filter(Q(site_id__in=all_tenant_site_ids) | Q(site__isnull=True))

        if qs.model.__name__ == 'AttendancePolicy':
            return qs.filter(Q(site_id__in=all_tenant_site_ids) | Q(site__isnull=True, organization__isnull=True)).distinct()

        if qs.model.__name__ == 'Holiday':
            return qs.filter(Q(site_id__in=all_tenant_site_ids) | Q(site__isnull=True)).distinct()

        if qs.model.__name__ == 'Organization':
            return qs.filter(id=employee.organization_id) if employee.organization_id else qs.none()

        return qs.none()

    # ── CASE 5: ALL DATA OF THE ENTITIES ('Corporate' / Site Admin) ─────────
    # Full access within this tenant boundary
    if qs.model.__name__ == 'Site':
        return qs.filter(id__in=all_tenant_site_ids) if all_tenant_site_ids else qs.none()

    if qs.model.__name__ == 'Employee':
        eq = Q()
        if all_tenant_site_ids:
            eq |= Q(site_id__in=all_tenant_site_ids) | Q(enrolled_sites__id__in=all_tenant_site_ids)
        if tenant_entity_ids:
            eq |= Q(entity_id__in=tenant_entity_ids)
        if tenant_site and tenant_site.organization_id:
            eq |= Q(entity__organization_id=tenant_site.organization_id)
        if eq:
            return qs.filter(eq).exclude(role='super_admin').distinct()
        return qs.filter(id=employee.id)

    if hasattr(qs.model, 'employee'):
        eq = Q()
        if all_tenant_site_ids:
            eq |= Q(employee__site_id__in=all_tenant_site_ids) | Q(employee__enrolled_sites__id__in=all_tenant_site_ids)
        if tenant_entity_ids:
            eq |= Q(employee__entity_id__in=tenant_entity_ids)
        if tenant_site and tenant_site.organization_id:
            eq |= Q(employee__entity__organization_id=tenant_site.organization_id)
        if eq:
            return qs.filter(eq).distinct()
        return qs.filter(employee=employee)

    if qs.model.__name__ == 'Entity':
        if tenant_entity_ids:
            return qs.filter(id__in=tenant_entity_ids)
        if tenant_site and tenant_site.organization_id:
            return qs.filter(organization_id=tenant_site.organization_id)
        return qs.none()

    if qs.model.__name__ == 'Branch':
        if tenant_branch_ids or tenant_entity_ids:
            bq = Q(id__in=tenant_branch_ids)
            if tenant_entity_ids:
                bq |= Q(entity_id__in=tenant_entity_ids)
            return qs.filter(bq)
        if tenant_site and tenant_site.organization_id:
            return qs.filter(entity__organization_id=tenant_site.organization_id)
        return qs.none()

    if qs.model.__name__ == 'Department':
        if tenant_entity_ids:
            return qs.filter(entity_id__in=tenant_entity_ids)
        if tenant_site and tenant_site.organization_id:
            return qs.filter(entity__organization_id=tenant_site.organization_id)
        return qs.none()

    if qs.model.__name__ == 'Designation':
        if tenant_entity_ids:
            return qs.filter(department__entity_id__in=tenant_entity_ids)
        if tenant_site and tenant_site.organization_id:
            return qs.filter(department__entity__organization_id=tenant_site.organization_id)
        return qs.none()

    if qs.model.__name__ == 'PayrollRun':
        if tenant_entity_ids:
            return qs.filter(entity_id__in=tenant_entity_ids)
        if tenant_site and tenant_site.organization_id:
            return qs.filter(entity__organization_id=tenant_site.organization_id)
        return qs.none()

    if qs.model.__name__ == 'Role':
        q = Q(site_id__in=all_tenant_site_ids)
        if not qs.filter(q, name__iexact='Site Admin').exists():
            q |= Q(code='SITE_ADMIN', site__isnull=True)
        org_id = tenant_site.organization_id if tenant_site else getattr(employee, 'organization_id', None)
        if org_id:
            q |= Q(site__isnull=True, organization_id=org_id)
        return qs.filter(q).distinct()

    if qs.model.__name__ == 'SalaryStructure':
        return qs.filter(Q(site_id__in=all_tenant_site_ids) | Q(site__isnull=True))

    if qs.model.__name__ == 'AttendancePolicy':
        return qs.filter(Q(site_id__in=all_tenant_site_ids) | Q(site__isnull=True, organization__isnull=True)).distinct()

    if qs.model.__name__ == 'Holiday':
        if all_tenant_site_ids:
            return qs.filter(Q(site_id__in=all_tenant_site_ids) | Q(site__isnull=True)).distinct()
        return qs.filter(site__isnull=True).distinct()

    if qs.model.__name__ == 'Organization':
        org_id = tenant_site.organization_id if tenant_site else getattr(employee, 'organization_id', None)
        return qs.filter(id=org_id) if org_id else qs.none()

    if hasattr(qs.model, 'site'):
        return qs.filter(site_id__in=all_tenant_site_ids)

    if hasattr(qs.model, 'organization'):
        return qs.filter(organization_id=employee.organization_id) if employee.organization_id else qs.none()

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
        # Strict boundary: Superuser only has CRUD access to platform-level modules (Sites)
        if request.user.is_superuser:
            rbac_module = getattr(view, 'rbac_module', None)
            if not rbac_module or rbac_module in ['Sites']:
                return True
            return False
        employee = getattr(request.user, 'employee_profile', None)
        if employee and employee.role == 'super_admin':
            rbac_module = getattr(view, 'rbac_module', None)
            if not rbac_module or rbac_module in ['Sites']:
                return True
            return False
        if employee and employee.role in ['org_admin', 'admin']:
            return True
        # 3. If view doesn't define rbac_module, don't enforce dynamic CRUD here (let other permissions handle it)
        rbac_module = getattr(view, 'rbac_module', None)
        if not rbac_module:
            return True
            
        # 4. Extract module permissions
        module_perms = {}
        from organisation.models import Site
        site = None
        if employee and employee.site_id:
            site = employee.site
        if not site:
            site = Site.objects.filter(contact_email=request.user.email).first()
        if not site and employee and employee.enrolled_sites.exists():
            site = employee.enrolled_sites.first()

        # Strict site module boundary: If site has modules configured, rbac_module must be allowed
        if site and site.modules is not None:
            allowed_mods = set()
            for m in site.modules:
                allowed_mods.add(m if isinstance(m, str) else m.get('name', ''))
            if 'Sub Sites' in allowed_mods:
                allowed_mods.add('Sites')
            if 'Sites' in allowed_mods:
                allowed_mods.add('Sub Sites')

            if rbac_module not in allowed_mods:
                return False

            is_site_admin = bool(
                (employee and employee.role in ('site_admin', 'admin')) or
                (site.contact_email and request.user.email and site.contact_email.strip().lower() == request.user.email.strip().lower()) or
                (employee and employee.dynamic_role and getattr(employee.dynamic_role, 'code', None) == 'SITE_ADMIN')
            )
            if is_site_admin:
                module_perms = {'view': True, 'create': True, 'update': True, 'delete': True}

        dynamic_perms = {}
        if employee and employee.dynamic_role and employee.dynamic_role.permissions:
            dynamic_perms = employee.dynamic_role.permissions
            if not module_perms:
                module_perms = dynamic_perms.get(rbac_module, {})
                            
        # Special workflow permissions handling for Run Payroll
        if rbac_module == 'Run Payroll':
            action = getattr(view, 'action', None)
            if action in ['approve', 'reject']:
                return _is_truthy(dynamic_perms.get('can_approve_payroll'))
            if action == 'execute':
                return (_is_truthy(dynamic_perms.get('can_run_payroll')) or
                        _is_truthy(module_perms.get('create')))
            if request.method in ['GET', 'HEAD', 'OPTIONS']:
                if any(_is_truthy(dynamic_perms.get(k)) for k in ['can_run_payroll', 'can_view_confidential_payroll', 'can_approve_payroll']):
                    return True

        # If no permissions found, deny
        if not module_perms:
            return False
        
        # 6. Map request method to Create/Read/Update/Delete
        method = request.method
        if method in ['GET', 'HEAD', 'OPTIONS']:
            view_perm = module_perms.get('view')
            return _has_view_perm(view_perm)
        elif method == 'POST':
            return _is_truthy(module_perms.get('create'))
        elif method in ['PUT', 'PATCH']:
            # We will allow the request to proceed to has_object_permission
            # if they are a manager. We'll enforce the strict check there.
            if _is_truthy(module_perms.get('update')):
                return True
            if employee:
                from employees.models import Employee
                if Employee.objects.filter(manager=employee).exists():
                    return True
            return False
        elif method == 'DELETE':
            return _is_truthy(module_perms.get('delete'))
            
        return False

    def has_object_permission(self, request, view, obj):
        if request.user.is_superuser:
            rbac_module = getattr(view, 'rbac_module', None)
            if not rbac_module or rbac_module in ['Sites']:
                return True
            return False
        employee = getattr(request.user, 'employee_profile', None)
        if employee and employee.role == 'super_admin':
            rbac_module = getattr(view, 'rbac_module', None)
            if not rbac_module or rbac_module in ['Sites']:
                return True
            return False
        if employee and employee.role in ['org_admin', 'admin']:
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
        if site and site.modules:
            for mod in site.modules:
                mod_name = mod if isinstance(mod, str) else mod.get('name', '')
                if mod_name == rbac_module:
                    module_perms = {'view': True, 'create': True, 'update': True, 'delete': True}
                    break

        if not module_perms and employee and employee.dynamic_role and employee.dynamic_role.permissions:
            module_perms = employee.dynamic_role.permissions.get(rbac_module, {})
            
        if method in ['PUT', 'PATCH']:
            return _is_truthy(module_perms.get('update'))
        elif method == 'DELETE':
            return _is_truthy(module_perms.get('delete'))
            
        return True
