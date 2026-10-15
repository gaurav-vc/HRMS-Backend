from rest_framework import serializers
from rest_framework_simplejwt.serializers import TokenObtainPairSerializer
from django.contrib.auth.models import User
from employees.models import Employee
from .models import LoginAuditLog
from django.utils import timezone

class CustomTokenObtainPairSerializer(TokenObtainPairSerializer):
    def validate(self, attrs):
        data = super().validate(attrs)
        
        # Automated LWD Deactivation Logic
        if hasattr(self.user, 'employee_profile') and hasattr(self.user.employee_profile, 'exit_process'):
            exit_process = self.user.employee_profile.exit_process
            if exit_process.status == 'Approved' and exit_process.last_working_day <= timezone.now().date():
                self.user.is_active = False
                self.user.save()
                exit_process.status = 'Deactivated'
                exit_process.save()
                from rest_framework.exceptions import AuthenticationFailed
                raise AuthenticationFailed("Account deactivated: Last working day has passed.")
        
        # Log successful login
        request = self.context.get('request')
        ip_address = request.META.get('REMOTE_ADDR') if request else None
        
        LoginAuditLog.objects.create(
            user=self.user,
            ip_address=ip_address,
            status='SUCCESS'
        )
        
        return data

class UserProfileSerializer(serializers.ModelSerializer):
    role = serializers.SerializerMethodField()
    employee_id = serializers.SerializerMethodField()
    first_name = serializers.SerializerMethodField()
    last_name = serializers.SerializerMethodField()
    permissions = serializers.SerializerMethodField()
    role_name = serializers.SerializerMethodField()
    dashboard_type = serializers.SerializerMethodField()
    site_name = serializers.SerializerMethodField()
    org_name = serializers.SerializerMethodField()
    photo_url = serializers.SerializerMethodField()
    is_wfh = serializers.SerializerMethodField()
    branding_text = serializers.SerializerMethodField()
    logo_url = serializers.SerializerMethodField()
    
    class Meta:
        model = User
        fields = ('id', 'username', 'email', 'role', 'employee_id', 'first_name', 'last_name', 'permissions', 'role_name', 'dashboard_type', 'site_name', 'org_name', 'photo_url', 'is_wfh', 'branding_text', 'logo_url', 'is_superuser')

    def _get_employee(self, obj):
        # Strict boundary: Superuser is the system platform admin, NOT a site employee
        if obj.is_superuser:
            return None
        emp = getattr(obj, 'employee_profile', None)
        if not emp:
            from employees.models import Employee
            if obj.email:
                emp = Employee.objects.filter(email__iexact=obj.email).first()
            if not emp and obj.username:
                emp = Employee.objects.filter(code__iexact=obj.username).first()
            if emp and not emp.user:
                try:
                    emp.user = obj
                    emp.save(update_fields=['user'])
                except Exception:
                    pass
        elif emp:
            try:
                emp.refresh_from_db()
            except Exception:
                pass
        return emp

    def get_employee_id(self, obj):
        emp = self._get_employee(obj)
        return emp.code if emp else None

    def get_first_name(self, obj):
        emp = self._get_employee(obj)
        if emp and emp.first_name:
            return emp.first_name
        return obj.first_name

    def get_last_name(self, obj):
        emp = self._get_employee(obj)
        if emp and emp.last_name:
            return emp.last_name
        return obj.last_name

    def get_role(self, obj):
        # Strict security boundary: ONLY superuser accounts can ever be super_admin
        if obj.is_superuser:
            return 'super_admin'
        
        from organisation.models import Site
        if Site.objects.filter(contact_email=obj.email).exists():
            return 'site_admin'
            
        emp = self._get_employee(obj)
        if emp:
            # Self-healing: if an employee was previously assigned 'super_admin' role in the DB, heal it
            if emp.role == 'super_admin':
                emp.role = 'employee'
                try:
                    emp.save(update_fields=['role'])
                except Exception:
                    pass

            if emp.role and emp.role not in ['employee', 'super_admin']:
                return emp.role

            if emp.dynamic_role and getattr(emp.dynamic_role, 'dashboard_type', None):
                dash = str(emp.dynamic_role.dashboard_type).lower()
                if dash in ['manager', 'payroll_admin', 'group_hr', 'entity_hr', 'site_admin']:
                    return dash

            return emp.role if emp.role != 'super_admin' else 'employee'
        return 'employee'

    def get_permissions(self, obj):
        if obj.is_superuser:
            return {}
        permissions = {}
        emp = self._get_employee(obj)
        if emp and emp.dynamic_role:
            permissions.update(emp.dynamic_role.permissions or {})
            permissions['can_approve'] = emp.dynamic_role.can_approve
            
        from organisation.models import Site
        site = Site.objects.filter(contact_email=obj.email).first()
        if site:
            if site.modules:
                for mod in site.modules:
                    mod_name = mod if isinstance(mod, str) else mod.get('name', '')
                    if mod_name:
                        permissions[mod_name] = {'view': True, 'create': True, 'update': True, 'delete': True}
            
        return permissions

    def get_role_name(self, obj):
        if obj.is_superuser:
            return 'Super Admin'
        from organisation.models import Site
        if Site.objects.filter(contact_email=obj.email).exists():
            return 'Site Admin'
        emp = self._get_employee(obj)
        if emp and emp.dynamic_role and emp.dynamic_role.name:
            return emp.dynamic_role.name
        if emp and emp.role:
            from employees.models import ROLE_CHOICES
            return dict(ROLE_CHOICES).get(emp.role, emp.role.replace('_', ' ').title())
        return 'Employee'

    def get_dashboard_type(self, obj):
        if obj.is_superuser:
            return 'superadmin'
        from organisation.models import Site
        if Site.objects.filter(contact_email=obj.email).exists():
            return 'manager' # Site Admins see the manager/executive dashboard
        emp = self._get_employee(obj)
        if emp and emp.dynamic_role and emp.dynamic_role.dashboard_type:
            return emp.dynamic_role.dashboard_type
        return None

    def get_site_name(self, obj):
        if obj.is_superuser:
            return None
        from organisation.models import Site
        site = Site.objects.filter(contact_email=obj.email).first()
        if site:
            return site.name
        emp = self._get_employee(obj)
        if emp and hasattr(emp, 'site') and emp.site:
            return emp.site.name
        return None

    def get_org_name(self, obj):
        if obj.is_superuser:
            return None
        from organisation.models import Site
        site = Site.objects.filter(contact_email=obj.email).first()
        if site and site.organization:
            return site.organization.name
        emp = self._get_employee(obj)
        if emp and hasattr(emp, 'site') and emp.site:
            if emp.site.organization:
                return emp.site.organization.name
        return None

    def get_photo_url(self, obj):
        if obj.is_superuser:
            return None
        emp = self._get_employee(obj)
        if emp and emp.photo:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(emp.photo.url)
            return emp.photo.url
        return None

    def get_is_wfh(self, obj):
        if obj.is_superuser:
            return False
        emp = self._get_employee(obj)
        if emp:
            from organisation.models import AttendancePolicy
            return AttendancePolicy.objects.filter(wfh_employees=emp).exists()
        return False

    def _get_main_site(self, obj):
        from authentication.permissions import _get_tenant_site
        return _get_tenant_site(obj)

    def get_branding_text(self, obj):
        if obj.is_superuser:
            return None
        site = self._get_main_site(obj)
        if site:
            return site.branding_text
        return None

    def get_logo_url(self, obj):
        if obj.is_superuser:
            return None
        site = self._get_main_site(obj)
        if site and site.logo:
            request = self.context.get('request')
            if request:
                return request.build_absolute_uri(site.logo.url)
            return site.logo.url
        return None

