import threading
from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser
from django.db.models import Q
from django.core.mail import send_mail
from django.conf import settings
from .models import Announcement, AnnouncementReceipt
from .serializers import AnnouncementSerializer
from employees.models import Employee

class AnnouncementViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser, JSONParser]
    serializer_class = AnnouncementSerializer

    def _get_employee(self, user):
        if not user or not user.is_authenticated:
            return None
        emp = getattr(user, 'employee_profile', None)
        if not emp:
            if user.email:
                emp = Employee.objects.filter(email__iexact=user.email).first()
            if not emp and user.username:
                emp = Employee.objects.filter(code__iexact=user.username).first()
            if emp and not emp.user:
                try:
                    emp.user = user
                    emp.save(update_fields=['user'])
                except Exception:
                    pass
        return emp

    def _is_site_module_allowed(self):
        user = self.request.user
        if not user or not user.is_authenticated:
            return False
        if user.is_superuser:
            return True
        emp = self._get_employee(user)
        dynamic_role = getattr(emp, 'dynamic_role', None) if emp else None

        # Corporate or Region access scope transcends single site module boundaries
        if dynamic_role and dynamic_role.access_scope in ('Corporate', 'Region'):
            return True

        # Users with dynamic management access bypass single site module boundaries
        if self._has_announcement_management_access(emp, user):
            return True

        site = getattr(emp, 'site', None) if emp else None
        if not site:
            from organisation.models import Site
            site = Site.objects.filter(contact_email=user.email).first()
        if not site and emp and emp.enrolled_sites.exists():
            site = emp.enrolled_sites.first()

        if site and site.modules is not None and len(site.modules) > 0:
            mods = [m if isinstance(m, str) else m.get('name', '') for m in site.modules]
            return 'Announcements' in mods
        return True

    def _has_all_entity_access(self, emp, user):
        """
        Dynamically checks whether the user/employee has access across all entities of data.
        Role-agnostic: evaluates dynamic access_scope, cross_department_access, entity-level permissions.
        """
        if not user or not user.is_authenticated:
            return False
        if user.is_superuser:
            return True
        if not emp:
            return False

        dynamic_role = getattr(emp, 'dynamic_role', None)
        if dynamic_role:
            scope = str(dynamic_role.access_scope or '').strip().lower()
            if scope in ('corporate', 'region', 'all', 'all entities', 'global'):
                return True
            if dynamic_role.cross_department_access:
                return True
            if dynamic_role.can_manage_users:
                return True
            perms = dynamic_role.permissions or {}
            allowed_ent = perms.get('allowed_entities')
            if allowed_ent == 'all' or (isinstance(allowed_ent, list) and len(allowed_ent) > 1):
                return True
            if perms.get('all_entities') is True:
                return True
            ent_perm = perms.get('Entities') or perms.get('entities') or {}
            if isinstance(ent_perm, dict) and (ent_perm.get('manage') or ent_perm.get('view') in (True, 'all')):
                return True

        return False

    def _has_announcement_management_access(self, emp, user):
        """
        Dynamically checks whether the employee/user has permission to publish announcements.
        Strict requirement: ONLY roles that have access across all entity data are permitted to publish.
        100% role-agnostic and capability-scoped.
        """
        if not user or not user.is_authenticated:
            return False
        if user.is_superuser:
            return True
        return self._has_all_entity_access(emp, user)

    def get_queryset(self):
        user = self.request.user
        if not user.is_authenticated:
            return Announcement.objects.none()

        emp = self._get_employee(user)

        # 1. System superusers or roles with access to all entities see all announcements
        if user.is_superuser or self._has_all_entity_access(emp, user):
            return Announcement.objects.all()

        # 2. Targeted feed: Returns any announcement targeted to the user, their role, their department, or everyone
        q_filter = Q(created_by=user)

        if emp:
            # Individual employee assignment: ALWAYS visible if targeted
            q_filter |= Q(target_employees=emp, is_active=True)

            # Department assignment:
            if emp.department_id:
                q_filter |= Q(target_departments=emp.department_id, is_active=True)

            # Role assignment: checks dynamic_role and dynamically matches role code/name
            target_role_ids = set()
            if emp.dynamic_role_id:
                target_role_ids.add(emp.dynamic_role_id)
            if emp.role:
                from organisation.models import Role
                matching_roles = Role.objects.filter(
                    Q(code__iexact=emp.role) | Q(name__iexact=emp.role)
                ).values_list('id', flat=True)
                target_role_ids.update(matching_roles)

            if target_role_ids and hasattr(Announcement, 'target_roles'):
                q_filter |= Q(target_roles__in=list(target_role_ids), is_active=True)

            # Everyone audience:
            if emp.entity_id:
                q_filter |= Q(audience_type='EVERYONE', entity_id=emp.entity_id, is_active=True)
                q_filter |= Q(audience_type='EVERYONE', entity__isnull=True, is_active=True)
            else:
                q_filter |= Q(audience_type='EVERYONE', is_active=True)
        else:
            q_filter |= Q(audience_type='EVERYONE', is_active=True)

        return Announcement.objects.filter(q_filter).distinct()

    def perform_create(self, serializer):
        user = self.request.user
        emp = self._get_employee(user)

        if not self._has_announcement_management_access(emp, user):
            from rest_framework.exceptions import PermissionDenied
            raise PermissionDenied("You do not have permission to publish announcements.")

        entity = emp.entity if emp else None
        
        file_obj = self.request.FILES.get('attachment')
        attachment_name = self.request.data.get('attachment_name') or (file_obj.name if file_obj else '')
        
        announcement = serializer.save(
            created_by=user,
            entity=entity,
            attachment_name=attachment_name
        )
        
        # Dispatch in-app notifications and email broadcast
        self._dispatch_announcements(announcement)

    def _dispatch_announcements(self, announcement):
        from employees.models import Notification

        # 1. Resolve target active employees
        target_employees = set()
        if announcement.audience_type == 'EVERYONE':
            if announcement.entity:
                qs = Employee.objects.filter(entity=announcement.entity, status='Active')
            else:
                qs = Employee.objects.filter(status='Active')
            target_employees.update(qs)
        elif announcement.audience_type == 'ROLE' and hasattr(announcement, 'target_roles'):
            roles = announcement.target_roles.all()
            qs = Employee.objects.filter(dynamic_role__in=roles, status='Active')
            target_employees.update(qs)
        elif announcement.audience_type == 'DEPARTMENT':
            depts = announcement.target_departments.all()
            qs = Employee.objects.filter(department__in=depts, status='Active')
            target_employees.update(qs)
        elif announcement.audience_type == 'INDIVIDUAL':
            target_employees.update(announcement.target_employees.filter(status='Active'))

        # Also include the creator in notification feed if they are an active employee
        creator_emp = self._get_employee(announcement.created_by) if announcement.created_by else None
        if creator_emp and creator_emp.status == 'Active':
            target_employees.add(creator_emp)

        # 2. Synchronously create In-App Notifications
        try:
            notifs = []
            for emp in target_employees:
                notifs.append(
                    Notification(
                        recipient=emp,
                        title=f"Announcement: {announcement.title}",
                        message=announcement.content[:180],
                        is_read=False
                    )
                )
            if notifs:
                Notification.objects.bulk_create(notifs, ignore_conflicts=True)
        except Exception as ex:
            print(f"[Announcement In-App Notification Error] {ex}")

        # 3. Asynchronously dispatch Email broadcast
        def _send_email():
            try:
                recipients = set()
                for e in target_employees:
                    if e.email:
                        recipients.add(e.email)

                if not recipients:
                    return

                login_url = getattr(settings, 'HRMS_PORTAL_URL', "https://hrms.vibecopilot.ai/")
                subject = f"[{announcement.priority.upper()}] Announcement: {announcement.title}"
                has_attachment = bool(announcement.attachment)
                org_label = announcement.entity.name if announcement.entity else "Organization Team"
                
                body = f"""Hello Team,

A new company announcement has been published:

Title: {announcement.title}
Priority: {announcement.priority}

Details:
{announcement.content}

{'Note: This announcement includes an attachment. Please view it on the web portal or mobile app.' if has_attachment else ''}

Portal URL: {login_url}

Best regards,
{org_label}
"""
                send_mail(
                    subject,
                    body,
                    getattr(settings, 'DEFAULT_FROM_EMAIL', 'noreply@vibecopilot.ai'),
                    list(recipients),
                    fail_silently=True
                )
            except Exception as ex:
                print(f"[Announcement Email Error] {ex}")

        t = threading.Thread(target=_send_email, daemon=True)
        t.start()

    @action(detail=True, methods=['POST'], url_path='mark_read')
    def mark_read(self, request, pk=None):
        announcement = self.get_object()
        emp = self._get_employee(request.user)
        if not emp:
            return Response({"error": "No employee profile found."}, status=status.HTTP_400_BAD_REQUEST)
            
        receipt, created = AnnouncementReceipt.objects.get_or_create(
            announcement=announcement,
            employee=emp
        )
        return Response({"success": True, "read_at": receipt.read_at})
