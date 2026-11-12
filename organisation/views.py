from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import AllowAny
from .models import Entity, Branch, Site, Department, Designation, Role, AttendancePolicy, PunctualitySlab
from .serializers import (
    EntitySerializer, BranchSerializer, SiteSerializer,
    DepartmentSerializer, DesignationSerializer, RoleSerializer,
    AttendancePolicySerializer, PunctualitySlabSerializer
)
from authentication.permissions import DataIsolationMixin


class EntityViewSet(DataIsolationMixin, viewsets.ModelViewSet):
    rbac_module = 'Entities'
    queryset = Entity.objects.all()
    serializer_class = EntitySerializer

    def perform_create(self, serializer):
        user = self.request.user
        org = None
        if hasattr(user, 'employee_profile') and user.employee_profile and user.employee_profile.organization:
            org = user.employee_profile.organization
        else:
            from organisation.models import Site
            site = Site.objects.filter(contact_email=user.email).first()
            if site and site.organization:
                org = site.organization
        serializer.save(organization=org)

    def get_permissions(self):
        if self.action in ['list', 'retrieve']:
            from rest_framework.permissions import IsAuthenticated
            return [IsAuthenticated()]
        return super().get_permissions()

class AttendancePolicyViewSet(DataIsolationMixin, viewsets.ModelViewSet):
    rbac_module = 'Attendance'
    queryset = AttendancePolicy.objects.all()
    serializer_class = AttendancePolicySerializer

    def get_queryset(self):
        qs = super().get_queryset()
        
        is_global = self.request.query_params.get('is_global')
        if is_global == 'true':
            return qs.filter(employee__isnull=True, site__isnull=True, organization__isnull=True)

        site_id = self.request.query_params.get('site')
        if site_id:
            return qs.filter(site_id=site_id)

        org_id = self.request.query_params.get('organization')
        if org_id:
            return qs.filter(organization_id=org_id)

        emp_id = self.request.query_params.get('employee')
        if emp_id:
            return qs.filter(employee_id=emp_id)

        return qs

    def create(self, request, *args, **kwargs):
        site_id = request.data.get('site')
        org_id = request.data.get('organization')
        emp_id = request.data.get('employee')

        existing = None
        if site_id:
            existing = AttendancePolicy.objects.filter(site_id=site_id).first()
        elif org_id:
            existing = AttendancePolicy.objects.filter(organization_id=org_id).first()
        elif emp_id:
            existing = AttendancePolicy.objects.filter(employee_id=emp_id).first()
        else:
            is_explicit_global = request.query_params.get('is_global') == 'true' or (not site_id and not org_id and not emp_id)
            if is_explicit_global:
                existing = AttendancePolicy.objects.filter(
                    site__isnull=True, organization__isnull=True, employee__isnull=True
                ).first()

        if existing:
            serializer = self.get_serializer(existing, data=request.data, partial=True)
            serializer.is_valid(raise_exception=True)
            policy = serializer.save()
            raw_wfh = request.data.get('wfh_employees')
            if raw_wfh is None:
                raw_wfh = request.data.get('wfhEmployees')
            if raw_wfh is not None:
                policy.wfh_employees.set(raw_wfh)
            return Response(self.get_serializer(policy).data, status=status.HTTP_200_OK)

        serializer = self.get_serializer(data=request.data)
        serializer.is_valid(raise_exception=True)
        policy = serializer.save()
        raw_wfh = request.data.get('wfh_employees')
        if raw_wfh is None:
            raw_wfh = request.data.get('wfhEmployees')
        if raw_wfh is not None:
            policy.wfh_employees.set(raw_wfh)
        return Response(self.get_serializer(policy).data, status=status.HTTP_201_CREATED)

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop('partial', False)
        instance = self.get_object()

        site_id = request.data.get('site')
        org_id = request.data.get('organization')
        emp_id = request.data.get('employee')

        if site_id:
            target = AttendancePolicy.objects.filter(site_id=site_id).first()
            if target:
                instance = target
        elif org_id:
            target = AttendancePolicy.objects.filter(organization_id=org_id).first()
            if target:
                instance = target
        elif emp_id:
            target = AttendancePolicy.objects.filter(employee_id=emp_id).first()
            if target:
                instance = target

        serializer = self.get_serializer(instance, data=request.data, partial=partial)
        serializer.is_valid(raise_exception=True)
        policy = serializer.save()
        raw_wfh = request.data.get('wfh_employees')
        if raw_wfh is None:
            raw_wfh = request.data.get('wfhEmployees')
        if raw_wfh is not None:
            policy.wfh_employees.set(raw_wfh)
        return Response(self.get_serializer(policy).data, status=status.HTTP_200_OK)

    def get_object(self):
        queryset = AttendancePolicy.objects.all()
        lookup_url_kwarg = self.lookup_url_kwarg or self.lookup_field
        filter_kwargs = {self.lookup_field: self.kwargs[lookup_url_kwarg]}
        from django.shortcuts import get_object_or_404
        obj = get_object_or_404(queryset, **filter_kwargs)
        self.check_object_permissions(self.request, obj)
        return obj

    def partial_update(self, request, *args, **kwargs):
        kwargs['partial'] = True
        return self.update(request, *args, **kwargs)


class PunctualitySlabViewSet(DataIsolationMixin, viewsets.ModelViewSet):
    rbac_module = 'Attendance'
    queryset = PunctualitySlab.objects.all().select_related('policy').prefetch_related('applicable_designations')
    serializer_class = PunctualitySlabSerializer

    def get_permissions(self):
        if self.action in ['list', 'retrieve', 'available_roles']:
            from rest_framework.permissions import IsAuthenticated
            return [IsAuthenticated()]
        return super().get_permissions()

    def get_queryset(self):
        qs = super().get_queryset()
        policy_id = self.request.query_params.get('policy')
        if policy_id:
            qs = qs.filter(policy_id=policy_id)
        site_id = self.request.query_params.get('site')
        if site_id:
            qs = qs.filter(policy__site_id=site_id)
        return qs

    @action(detail=False, methods=['get'], url_path='available-roles')
    def available_roles(self, request):
        site_id = request.query_params.get('site')
        policy_id = request.query_params.get('policy')
        if not site_id and policy_id:
            policy = AttendancePolicy.objects.filter(id=policy_id).first()
            if policy and policy.site_id:
                site_id = policy.site_id

        if not site_id and request.user and request.user.is_authenticated:
            from authentication.permissions import _get_tenant_site
            tenant_site = _get_tenant_site(request.user)
            if tenant_site:
                site_id = tenant_site.id

        from employees.models import Employee
        from organisation.models import Role, Designation
        from django.db.models import Q

        results = []
        if site_id:
            # Dynamic roles specifically assigned to this site OR held by active employees in this site
            site_emp_role_ids = Employee.objects.filter(site_id=site_id, dynamic_role__isnull=False).values_list('dynamic_role_id', flat=True)
            roles = Role.objects.filter(Q(site_id=site_id) | Q(id__in=site_emp_role_ids)).distinct().order_by('name')

            for r in roles:
                results.append({
                    "id": r.id,
                    "type": "ROLE",
                    "title": r.name,
                    "code": r.code,
                    "category": f"Dynamic Role ({r.code})"
                })

            # Designations held by active employees in this site
            site_emp_desig_ids = Employee.objects.filter(site_id=site_id, designation__isnull=False).values_list('designation_id', flat=True)
            desigs = Designation.objects.filter(id__in=site_emp_desig_ids).distinct().order_by('title')
            for d in desigs:
                results.append({
                    "id": d.id,
                    "type": "DESIGNATION",
                    "title": d.title,
                    "code": getattr(d, 'grade', '') or "",
                    "category": "Designation"
                })
        else:
            # Global fallback: Dynamic roles
            for r in Role.objects.all().order_by('name'):
                site_label = f" ({r.site.name})" if r.site else ""
                results.append({
                    "id": r.id,
                    "type": "ROLE",
                    "title": r.name,
                    "code": r.code,
                    "category": f"Dynamic Role{site_label}"
                })

        return Response(results)



class BranchViewSet(DataIsolationMixin, viewsets.ModelViewSet):
    rbac_module = 'Branches'
    queryset = Branch.objects.all()
    serializer_class = BranchSerializer

    def get_permissions(self):
        if self.action in ['list', 'retrieve']:
            from rest_framework.permissions import IsAuthenticated
            return [IsAuthenticated()]
        return super().get_permissions()

import string
import random
from django.contrib.auth.models import User
from django.core.mail import send_mail
from django.conf import settings

def generate_random_password(length=12):
    characters = string.ascii_letters + string.digits + "!@#$%^&*"
    return ''.join(random.choice(characters) for i in range(length))

def provision_contact_person(site, origin=None, is_update=False):
    if not site.contact_email:
        return
        
    email = site.contact_email
    user = User.objects.filter(email=email).first() or User.objects.filter(username=email).first()
    
    password = None
    if user:
        if not user.is_superuser:
            if not is_update:
                password = generate_random_password()
                user.set_password(password)
                user.save()
        else:
            password = "[Your existing password]"
    else:
        password = generate_random_password()
        user = User.objects.create_user(
            username=email,
            email=email,
            password=password,
            first_name=site.contact_name or ''
        )

    try:
        from employees.models import Employee
        from organisation.models import Role, Entity, Branch
        default_perms = {
            'Entities': {'view': True, 'create': True, 'update': True, 'delete': True},
            'Branches': {'view': True, 'create': True, 'update': True, 'delete': True},
            'Sites': {'view': True, 'create': True, 'update': True, 'delete': True},
            'Departments': {'view': True, 'create': True, 'update': True, 'delete': True},
            'Designations': {'view': True, 'create': True, 'update': True, 'delete': True},
            'Roles & Users': {'view': True, 'create': True, 'update': True, 'delete': True},
            'Employees': {'view': True, 'create': True, 'update': True, 'delete': True},
            'Attendance': {'view': True, 'create': True, 'update': True, 'delete': True},
            'Leaves': {'view': True, 'create': True, 'update': True, 'delete': True},
            'Payroll': {'view': True, 'create': True, 'update': True, 'delete': True},
            'Organization Tree': {'view': True, 'create': True, 'update': True, 'delete': True},
            'Reports': {'view': True, 'create': True, 'update': True, 'delete': True},
            'Settings': {'view': True, 'create': True, 'update': True, 'delete': True},
        }

        # Build site admin permissions strictly based on assigned site.modules
        if site.modules is not None and len(site.modules) > 0:
            target_perms = {}
            for m in site.modules:
                m_name = m if isinstance(m, str) else m.get('name', '')
                if m_name:
                    target_perms[m_name] = {'view': True, 'create': True, 'update': True, 'delete': True}
            if 'Sub Sites' in target_perms:
                target_perms['Sites'] = {'view': True, 'create': True, 'update': True, 'delete': True}
        else:
            target_perms = default_perms

        role_obj = Role.objects.filter(name='Site Admin').first()
        if not role_obj:
            role_obj = Role.objects.create(name='Site Admin', code='SITE_ADMIN', access_scope='Corporate', permissions=target_perms)
            created = True
        else:
            created = False
            
        # Preserve any existing special workflow permissions configured for this role
        existing_special = {
            k: v for k, v in (role_obj.permissions or {}).items()
            if k in (
                'can_approve',
                'can_run_payroll',
                'can_approve_payroll',
                'can_view_confidential_payroll',
                'can_release_salary',
                'can_add_ctc',
                'can_add_compensation',
                'can_view_confidential',
                'can_process_payroll',
                'allowed_entities',
            )
        }
        merged_target_perms = {**existing_special, **target_perms}

        # Always ensure Site Admin has Corporate scope and strictly aligned permissions
        changed = False
        if role_obj.access_scope != 'Corporate':
            role_obj.access_scope = 'Corporate'
            changed = True
        if role_obj.permissions != merged_target_perms:
            role_obj.permissions = merged_target_perms
            changed = True
        if changed:
            role_obj.save(update_fields=['access_scope', 'permissions'])

        if not user.is_superuser:
            emp = getattr(user, 'employee_profile', None)
            
            branch = site.branch if hasattr(site, 'branch') and site.branch else None
            entity = branch.entity if branch else None
            if not entity and getattr(site, 'organization_id', None):
                entity = Entity.objects.filter(organization_id=site.organization_id).first()
                if entity and not branch:
                    branch = entity.branches.first()
            
            if not emp:
                name_parts = (site.contact_name or email.split('@')[0]).split(' ', 1)
                f_name = name_parts[0]
                l_name = name_parts[1] if len(name_parts) > 1 else ''
                
                emp = Employee.objects.create(
                    user=user,
                    first_name=f_name,
                    last_name=l_name,
                    email=email,
                    code=f"EMP-{user.id:04d}",
                    role='site_admin',
                    dynamic_role=role_obj,
                    site=site,
                    branch=branch,
                    entity=entity,
                    organization=site.organization if hasattr(site, 'organization') else None,
                    status='Active'
                )
            else:
                if not emp.site:
                    emp.site = site
                if emp.role == 'employee':
                    emp.role = 'site_admin'
                    emp.dynamic_role = role_obj
                emp.save()
                
            if site not in emp.enrolled_sites.all():
                emp.enrolled_sites.add(site)
            
    except Exception as e:
        print(f"Failed to create/update employee profile: {e}")

    if not is_update and password and password != "[Your existing password]":
        login_url = f"{origin}/" if origin else "https://hrms.vibecopilot.ai/"
        subject = f"You have been assigned to Site: {site.name}"
        message = f"Hello {site.contact_name or 'User'},\n\nYou have been assigned as the Site Admin for {site.name}.\n\nWebsite URL: {login_url}\nLogin ID: {email}\nPassword: {password}\n\nPlease log in and change your password.\n\nBest regards,\nVibeCopilot Team"
        
        import threading
        def send_async():
            try:
                send_mail(subject, message, getattr(settings, 'EMAIL_HOST_USER', 'noreply@vibecopilot.ai'), [email], fail_silently=False)
            except Exception as e:
                print(f"SITE EMAIL FAILED. Google SMTP Error: {str(e)}")
        threading.Thread(target=send_async).start()


from rest_framework.parsers import MultiPartParser, FormParser, JSONParser

class SiteViewSet(DataIsolationMixin, viewsets.ModelViewSet):
    rbac_module = 'Sites'
    queryset = Site.objects.all()
    serializer_class = SiteSerializer
    parser_classes = (MultiPartParser, FormParser, JSONParser)
    

    def get_permissions(self):
        if self.action in ['list', 'retrieve']:
            from rest_framework.permissions import IsAuthenticated
            return [IsAuthenticated()]
        if self.action == 'branding':
            return [AllowAny()]
        return super().get_permissions()

    def get_queryset(self):
        qs = super().get_queryset()
        is_sub = self.request.query_params.get('is_sub_site')
        parent_id = self.request.query_params.get('parent_site')

        if is_sub is not None:
            if str(is_sub).lower() in ['true', '1']:
                qs = qs.filter(is_sub_site=True)
            elif str(is_sub).lower() in ['false', '0']:
                qs = qs.filter(is_sub_site=False, parent_site__isnull=True)
        elif parent_id is not None:
            qs = qs.filter(parent_site_id=parent_id)
        else:
            user = self.request.user
            show_all = str(self.request.query_params.get('all', '')).lower() in ['true', '1']
            if user.is_authenticated and user.is_superuser and not show_all:
                qs = qs.filter(is_sub_site=False, parent_site__isnull=True)
        return qs

    @action(detail=False, methods=['get'])
    def branding(self, request):
        """
        Public API for mobile apps to fetch site branding by site_code or sub_domain
        """
        site_code = request.query_params.get('site_code')
        if not site_code:
            return Response({'error': 'site_code query parameter is required'}, status=status.HTTP_400_BAD_REQUEST)
            
        site = Site.objects.filter(site_code=site_code).first()
        if not site:
            return Response({'error': 'Site not found'}, status=status.HTTP_404_NOT_FOUND)
            
        logo_url = None
        if site.logo:
            logo_url = request.build_absolute_uri(site.logo.url)
            
        return Response({
            'site_name': site.name,
            'branding_text': site.branding_text,
            'logo_url': logo_url
        })

    @action(detail=True, methods=['POST'])
    def generate_kiosk_token(self, request, pk=None):
        """
        Generates or regenerates a cryptographically secure terminal token for this site's tablet kiosk.
        Strictly isolated to Site Admins authorized for this site.
        """
        site = self.get_object()
        import secrets
        site.kiosk_token = secrets.token_hex(24)
        if not site.kiosk_pin:
            site.kiosk_pin = '1234'
        site.save(update_fields=['kiosk_token', 'kiosk_pin'])
        return Response({
            'kiosk_token': site.kiosk_token,
            'kiosk_pin': site.kiosk_pin,
            'kiosk_enabled': site.kiosk_enabled,
            'site_id': site.id,
            'site_name': site.name
        }, status=status.HTTP_200_OK)

    def perform_create(self, serializer):
        user = self.request.user
        from authentication.permissions import _get_tenant_site
        
        save_kwargs = {}
        raw_is_sub = self.request.data.get('is_sub_site')
        is_explicitly_sub = raw_is_sub is True or str(raw_is_sub).lower() in ['true', '1']
        is_super = bool(user.is_authenticated and user.is_superuser)

        if is_super and not is_explicitly_sub:
            # Top-level client site created in Super Admin: strictly isolated, never a subsite
            save_kwargs['is_sub_site'] = False
            save_kwargs['parent_site'] = None
        else:
            # Sub-site created in Sites: strictly belongs to the main site
            save_kwargs['is_sub_site'] = True
            
            # Resolve parent_site:
            req_parent = self.request.data.get('parent_site') or self.request.data.get('parentSite')
            tenant_site = _get_tenant_site(user)
            
            parent_obj = None
            if req_parent:
                from .models import Site
                parent_obj = Site.objects.filter(id=req_parent, is_sub_site=False).first()
            if not parent_obj and tenant_site:
                parent_obj = tenant_site.parent_site if (tenant_site.is_sub_site and tenant_site.parent_site) else tenant_site
            
            # Strict Rule: Sub-sites NEVER have modules stored on them; modules belong ONLY to the main site!
            save_kwargs['modules'] = None

            if parent_obj:
                save_kwargs['parent_site'] = parent_obj
                if not serializer.validated_data.get('organization') and parent_obj.organization:
                    save_kwargs['organization'] = parent_obj.organization
                if not serializer.validated_data.get('branch') and parent_obj.branch:
                    save_kwargs['branch'] = parent_obj.branch
                if not serializer.validated_data.get('contact_email') and parent_obj.contact_email:
                    save_kwargs['contact_email'] = parent_obj.contact_email
                if not serializer.validated_data.get('contact_name') and parent_obj.contact_name:
                    save_kwargs['contact_name'] = parent_obj.contact_name
                if not serializer.validated_data.get('contact_phone') and parent_obj.contact_phone:
                    save_kwargs['contact_phone'] = parent_obj.contact_phone
            elif tenant_site:
                if tenant_site.organization and 'organization' not in serializer.validated_data:
                    save_kwargs['organization'] = tenant_site.organization
                if tenant_site.branch and 'branch' not in serializer.validated_data:
                    save_kwargs['branch'] = tenant_site.branch
                if not serializer.validated_data.get('contact_email') and tenant_site.contact_email:
                    save_kwargs['contact_email'] = tenant_site.contact_email

            # Clean kiosk_token: empty string or blank must be saved as None to avoid unique constraint collisions
            if not serializer.validated_data.get('kiosk_token'):
                save_kwargs['kiosk_token'] = None

            # Clean site_code: ensure empty string is replaced with a generated unique subsite code
            site_code_val = serializer.validated_data.get('site_code')
            if not site_code_val or not str(site_code_val).strip():
                p_code = parent_obj.site_code if parent_obj and parent_obj.site_code else 'SUB'
                save_kwargs['site_code'] = f"{p_code}-{random.randint(100, 9999)}"
            
        site = serializer.save(**save_kwargs)
        
        # Auto-enroll creator into the new site only if it's an operational subsite, never for superadmin sites
        if not is_super and save_kwargs.get('is_sub_site') is True:
            if hasattr(user, 'employee_profile') and user.employee_profile:
                emp = user.employee_profile
                if site not in emp.enrolled_sites.all():
                    emp.enrolled_sites.add(site)
                
        # ONLY call provision_contact_person for top-level Main Sites, NEVER for sub-sites!
        if not save_kwargs.get('is_sub_site'):
            origin = self.request.headers.get('Origin')
            provision_contact_person(site, origin=origin)
        
    def perform_update(self, serializer):
        old_email = serializer.instance.contact_email
        if serializer.instance.is_sub_site:
            # Sub-sites NEVER have modules stored on them; modules belong strictly to the main site!
            site = serializer.save(modules=None)
        else:
            site = serializer.save()
            origin = self.request.headers.get('Origin')
            email_changed = bool(site.contact_email and site.contact_email != old_email)
            provision_contact_person(site, origin=origin, is_update=not email_changed)

class DepartmentViewSet(DataIsolationMixin, viewsets.ModelViewSet):
    rbac_module = 'Departments'
    queryset = Department.objects.all()
    serializer_class = DepartmentSerializer

    def get_permissions(self):
        if self.action in ['list', 'retrieve']:
            from rest_framework.permissions import IsAuthenticated
            return [IsAuthenticated()]
        return super().get_permissions()

class DesignationViewSet(DataIsolationMixin, viewsets.ModelViewSet):
    rbac_module = 'Designations'
    queryset = Designation.objects.all()
    serializer_class = DesignationSerializer

    def get_permissions(self):
        if self.action in ['list', 'retrieve']:
            from rest_framework.permissions import IsAuthenticated
            return [IsAuthenticated()]
        return super().get_permissions()

from org_engine.models import OrganizationNode
from org_engine.engine import HierarchyEngine

class RoleViewSet(DataIsolationMixin, viewsets.ModelViewSet):
    rbac_module = 'Roles & Users'
    queryset = Role.objects.all()
    serializer_class = RoleSerializer

    def perform_create(self, serializer):
        user = self.request.user
        from authentication.permissions import _get_tenant_site
        tenant_site = _get_tenant_site(user)
        save_kwargs = {}
        if tenant_site:
            save_kwargs['site'] = tenant_site
            if tenant_site.organization:
                save_kwargs['organization'] = tenant_site.organization
        role = serializer.save(**save_kwargs)
        try:
            from org_engine.models import OrganizationNode, OrganizationNodeType
            role_type, _ = OrganizationNodeType.objects.get_or_create(name='Role')
            
            parent_node = None
            if role.reporting_to:
                parent_node = OrganizationNode.objects.filter(name=role.reporting_to.name, node_type__name='Role').first()
            elif role.department:
                parent_node = OrganizationNode.objects.filter(name=role.department.name, node_type__name='Department').first()
                
            if not parent_node:
                parent_node = OrganizationNode.objects.filter(
                    parent__isnull=True
                ).exclude(node_type__name__in=['Role', 'Employee', 'Department']).first()
                
            OrganizationNode.objects.create(
                name=role.name,
                node_type=role_type,
                parent=parent_node
            )
        except Exception as e:
            print(f"Failed to create org engine node for role: {e}")

    def perform_update(self, serializer):
        old_reporting_to = serializer.instance.reporting_to
        old_name = serializer.instance.name
        role = serializer.save()

        # Update the Organization Graph
        try:
            # Attempt to find the corresponding OrganizationNode (matching by name since legacy_role_id may be null)
            role_node = OrganizationNode.objects.filter(name=old_name, node_type__name='Role').first()
            
            if role_node:
                # If name changed, update it
                if old_name != role.name:
                    role_node.name = role.name
                    role_node.save(update_fields=['name'])

                # If reporting structure changed, move the node
                if role.reporting_to != old_reporting_to:
                    new_parent_node = None
                    if role.reporting_to:
                        new_parent_node = OrganizationNode.objects.filter(name=role.reporting_to.name, node_type__name='Role').first()
                    elif role.department:
                        new_parent_node = OrganizationNode.objects.filter(name=role.department.name, node_type__name='Department').first()
                    
                    if new_parent_node and role_node.parent_id != new_parent_node.id:
                        HierarchyEngine.move_node(role_node, new_parent_node)
        except Exception as e:
            print(f"Failed to sync org engine graph: {e}")

    def perform_destroy(self, instance):
        try:
            # Sync deletion to Org Engine
            role_node = OrganizationNode.objects.filter(name=instance.name, node_type__name='Role').first()
            if role_node:
                # If there are children, you might want to handle it properly, but cascading is fine for now
                role_node.delete()
        except Exception as e:
            print(f"Failed to delete org engine graph node: {e}")
            
        instance.delete()
