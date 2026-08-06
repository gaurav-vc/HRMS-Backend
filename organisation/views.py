from rest_framework import viewsets
from .models import Entity, Branch, Site, Department, Designation, Role, AttendancePolicy
from .serializers import (
    EntitySerializer, BranchSerializer, SiteSerializer,
    DepartmentSerializer, DesignationSerializer, RoleSerializer,
    AttendancePolicySerializer
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
    queryset = AttendancePolicy.objects.all()
    serializer_class = AttendancePolicySerializer
    filterset_fields = ['site', 'organization', 'employee']


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

def provision_contact_person(site, origin=None):
    if not site.contact_email:
        return
        
    email = site.contact_email
    user = User.objects.filter(email=email).first() or User.objects.filter(username=email).first()
    
    if user:
        if not user.is_superuser:
            password = generate_random_password()
            user.set_password(password)
            user.save()
        else:
            password = "[Your existing password]"
        login_url = f"{origin}/" if origin else "http://localhost:5173/"
        subject = f"You have been assigned to Site: {site.name}"
        message = f"Hello {site.contact_name or 'User'},\n\nYou have been assigned as the Site Admin for {site.name}.\n\nWebsite URL: {login_url}\nLogin ID: {email}\nPassword: {password}\n\nPlease log in and change your password.\n\nBest regards,\nVibeCopilot Team"
        import threading
        def send_async():
            try:
                send_mail(subject, message, getattr(settings, 'EMAIL_HOST_USER', 'noreply@vibecopilot.ai'), [email], fail_silently=False)
            except Exception as e:
                print(f"SITE EMAIL FAILED. Google SMTP Error: {str(e)}")
        threading.Thread(target=send_async).start()
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
            from organisation.models import Role
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
            }
            role_obj, created = Role.objects.get_or_create(name='Site Admin', defaults={'code': 'SITE_ADMIN', 'permissions': default_perms})
            if not created and not role_obj.permissions:
                role_obj.permissions = default_perms
                role_obj.save(update_fields=['permissions'])
            Employee.objects.create(
                user=user,
                first_name=site.contact_name or email.split('@')[0],
                email=email,
                code=f"EMP-{user.id:04d}",
                role='site_admin',
                dynamic_role=role_obj,
                site=site,
                status='Active'
            )
        except Exception as e:
            print(f"Failed to create employee profile: {e}")
            
        subject = f"Welcome to VibeCopilot - Site Admin Credentials"
        message = f"Hello {site.contact_name or 'User'},\n\nAn account has been created for you as the Site Admin for {site.name}.\n\nWebsite URL: http://localhost:5173\nLogin ID: {email}\nPassword: {password}\n\nPlease log in and change your password.\n\nBest regards,\nVibeCopilot Team"
        
        import threading
        def send_async_new():
            try:
                send_mail(subject, message, getattr(settings, 'EMAIL_HOST_USER', 'noreply@vibecopilot.ai'), [email], fail_silently=False)
            except Exception as e:
                print(f"SITE EMAIL FAILED. Google SMTP Error: {str(e)}")
        threading.Thread(target=send_async_new).start()


class SiteViewSet(DataIsolationMixin, viewsets.ModelViewSet):
    rbac_module = 'Sites'
    queryset = Site.objects.all()
    serializer_class = SiteSerializer
    
    from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
    parser_classes = (MultiPartParser, FormParser, JSONParser)

    def get_permissions(self):
        if self.action in ['list', 'retrieve']:
            from rest_framework.permissions import IsAuthenticated
            return [IsAuthenticated()]
        return super().get_permissions()

    def perform_create(self, serializer):
        site = serializer.save()
        origin = self.request.headers.get('Origin')
        provision_contact_person(site, origin=origin)
        
    def perform_update(self, serializer):
        old_email = serializer.instance.contact_email
        site = serializer.save()
        if site.contact_email and site.contact_email != old_email:
            origin = self.request.headers.get('Origin')
            provision_contact_person(site, origin=origin)

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
        role = serializer.save()
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
