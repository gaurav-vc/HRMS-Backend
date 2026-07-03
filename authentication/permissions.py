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

class DataIsolationMixin:
    """
    Mixin for ViewSets to enforce RBAC data isolation.
    Requires the model to have 'employee', 'site', or 'entity' fields or relations.
    """
    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user
        
        if not user.is_authenticated:
            return qs.none() # SECURITY FIX: Removed local testing bypass
            
        if user.is_superuser:
            return qs
            
        employee = getattr(user, 'employee_profile', None)
        if not employee:
            return qs.none()
            
        role = employee.role
        dynamic_role = employee.dynamic_role
        
        if role == 'super_admin':
            return qs
            
        # Check dynamic role permissions or scope
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
                    if hasattr(qs.model, 'employee'):
                        return qs.filter(employee__entity_id__in=custom_allowed)
                    if qs.model.__name__ == 'Employee':
                        return qs.filter(entity_id__in=custom_allowed)
                        
                if hasattr(qs.model, 'entity'):
                    return qs.filter(entity=employee.entity) if employee.entity else qs
                if hasattr(qs.model, 'employee'):
                    return qs.filter(employee__entity=employee.entity) if employee.entity else qs
                if qs.model.__name__ == 'Employee':
                    return qs.filter(entity=employee.entity)
            else:
                if hasattr(qs.model, 'employee'):
                    return qs.filter(employee=employee)
                elif qs.model.__name__ == 'Employee':
                    return qs.filter(id=employee.id)
                return qs.none()

        # Legacy Role Logic (Fallback for users without dynamic_role)
        if role == 'org_admin':
            if hasattr(qs.model, 'entity'):
                return qs.filter(entity=employee.entity) if employee.entity else qs
            if hasattr(qs.model, 'employee'):
                return qs.filter(employee__entity=employee.entity) if employee.entity else qs
            if qs.model.__name__ == 'Employee':
                return qs.filter(entity=employee.entity)
                
        if role == 'site_admin':
            if hasattr(qs.model, 'site'):
                return qs.filter(site=employee.site)
            if hasattr(qs.model, 'employee'):
                return qs.filter(employee__site=employee.site)
            if qs.model.__name__ == 'Employee':
                return qs.filter(site=employee.site)
                
        if role == 'hr' or role == 'manager':
            if hasattr(qs.model, 'entity'):
                return qs.filter(entity=employee.entity)
            if hasattr(qs.model, 'employee'):
                return qs.filter(employee__entity=employee.entity)
            if qs.model.__name__ == 'Employee':
                return qs.filter(entity=employee.entity)
                
        # Default Employee view: only their own data
        if hasattr(qs.model, 'employee'):
            return qs.filter(employee=employee)
        elif qs.model.__name__ == 'Employee':
            return qs.filter(id=employee.id)
            
        return qs.none()

