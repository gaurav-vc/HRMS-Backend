import csv
import io
from rest_framework import viewsets, exceptions, status
from rest_framework.decorators import action
from rest_framework.parsers import MultiPartParser
from rest_framework.response import Response
from django.contrib.auth.models import User
from django.core.mail import send_mail
from django.conf import settings
from .models import Employee
from .serializers import EmployeeSerializer
from authentication.permissions import DataIsolationMixin
from rest_framework.permissions import IsAuthenticated
import json

class EmployeeViewSet(DataIsolationMixin, viewsets.ModelViewSet):
    rbac_module = 'Employees'
    queryset = Employee.objects.all()
    serializer_class = EmployeeSerializer
    permission_classes = [IsAuthenticated]

    @action(detail=False, methods=['POST'], parser_classes=[MultiPartParser])
    def bulk_import(self, request):
        file_obj = request.FILES.get('file')
        if not file_obj:
            return Response({"error": "No file uploaded"}, status=status.HTTP_400_BAD_REQUEST)
        
        try:
            decoded_file = file_obj.read().decode('utf-8')
            io_string = io.StringIO(decoded_file)
            reader = csv.DictReader(io_string)
            
            success_count = 0
            errors = []
            
            for row in reader:
                first_name = row.get('First Name', '').strip()
                last_name = row.get('Last Name', '').strip()
                email = row.get('Email', '').strip()
                code = row.get('Employee Code', '').strip()
                phone = row.get('Phone', '').replace('\t', '').strip()
                gender = row.get('Gender', 'Male').strip()
                address = row.get('Address', '').strip()
                
                if not email or not code:
                    errors.append(f"Row {reader.line_num}: Email and Employee Code are required")
                    continue
                    
                if User.objects.filter(username=email).exists() or User.objects.filter(email=email).exists():
                    errors.append(f"Row {reader.line_num}: User with email {email} already exists")
                    continue
                
                # Fetch related models
                from organisation.models import Entity, Department, Designation, Branch, Site
                
                entity_name = row.get('Entity', '').strip()
                dept_name = row.get('Department', '').strip()
                desg_name = row.get('Designation', '').strip()
                branch_name = row.get('Branch', '').strip()
                site_name = row.get('Site', '').strip()
                manager_val = row.get('Reporting Manager', '').strip()
                
                ent = Entity.objects.filter(code__iexact=entity_name).first() or Entity.objects.filter(name__iexact=entity_name).first() if entity_name and entity_name.lower() != 'none' else None
                dept = Department.objects.filter(name__iexact=dept_name).first() if dept_name and dept_name.lower() != 'none' else None
                desg = Designation.objects.filter(title__iexact=desg_name).first() if desg_name and desg_name.lower() != 'none' else None
                branch = Branch.objects.filter(name__iexact=branch_name).first() if branch_name and branch_name.lower() != 'none' else None
                site = Site.objects.filter(name__iexact=site_name).first() if site_name and site_name.lower() != 'none' else None
                
                manager = None
                if manager_val and manager_val.lower() != 'none':
                    manager = Employee.objects.filter(code__iexact=manager_val).first() or Employee.objects.filter(email__iexact=manager_val).first()
                
                # Organization fallback
                org = None
                if not ent and hasattr(request.user, 'employee_profile'):
                    org = request.user.employee_profile.organization
                    ent = request.user.employee_profile.entity
                elif ent:
                    org = ent.organization

                # Dates (dd-mm-yyyy)
                def parse_date(ds):
                    if not ds: return None
                    try:
                        from datetime import datetime
                        return datetime.strptime(ds, '%d-%m-%Y').strftime('%Y-%m-%d')
                    except Exception:
                        return ds

                dob = parse_date(row.get('Date of Birth', '').strip())
                doj = parse_date(row.get('Date of Joining', '').strip())
                status = row.get('Status', 'Active').strip() or 'Active'

                # 1. Create User
                user = User.objects.create_user(
                    username=email,
                    email=email,
                    password="Password123!",
                    first_name=first_name,
                    last_name=last_name
                )
                
                # 2. Create Employee
                emp = Employee.objects.create(
                    user=user,
                    first_name=first_name,
                    last_name=last_name,
                    email=email,
                    code=code,
                    phone=phone,
                    gender=gender,
                    address=address,
                    dob=dob,
                    doj=doj,
                    status=status,
                    organization=org,
                    entity=ent,
                    department=dept,
                    designation=desg,
                    branch=branch,
                    site=site,
                    manager=manager,
                    pan=row.get('PAN', '').strip(),
                    aadhaar=row.get('Aadhaar', '').replace('\t', '').strip(),
                    uan=row.get('UAN', '').replace('\t', '').strip(),
                    esi=row.get('ESI No.', '').replace('\t', '').strip(),
                    bank_name=row.get('Bank Name', '').strip(),
                    bank_account=row.get('Bank Account No.', '').replace('\t', '').strip(),
                    ifsc=row.get('IFSC Code', '').strip()
                )
                
                # Notify HR/Admin
                from .models import Notification
                
                # 3. Create Org Engine Node (Only if they have a role, which they don't during bulk import usually, but just in case)
                try:
                    from org_engine.models import OrganizationNode, OrganizationNodeType
                    if emp.dynamic_role:
                        emp_type, _ = OrganizationNodeType.objects.get_or_create(name='Employee')
                        parent_node = OrganizationNode.objects.filter(name=emp.dynamic_role.name, node_type__name='Role').first()
                        if parent_node:
                            OrganizationNode.objects.create(
                                name=f"{first_name} {last_name}",
                                node_type=emp_type,
                                parent=parent_node,
                                tenant_id=1
                            )
                except Exception as e:
                    print(f"Failed to create Org Engine node during bulk import: {e}")
                success_count += 1
                
            return Response({"success": success_count, "errors": errors})
        except Exception as e:
            return Response({"error": str(e)}, status=status.HTTP_400_BAD_REQUEST)



    def perform_create(self, serializer):
        req_user = self.request.user
        validated_data = serializer.validated_data
        raw_data = self.request.data
        
        # 1. Site Isolation Enforcement
        if req_user and req_user.is_authenticated and not req_user.is_superuser:
            admin_profile = getattr(req_user, 'employee_profile', None)
            if admin_profile:
                if admin_profile.role == 'site_admin':
                    # Force site matching
                    if not admin_profile.site:
                        raise exceptions.PermissionDenied("You are a site admin without a designated site.")
                    validated_data['site'] = admin_profile.site

        import secrets
        import string
        
        status_val = validated_data.get('status', 'Active')
        
        email = validated_data.get('email')
        first_name = validated_data.get('first_name', '')
        last_name = validated_data.get('last_name', '')
        
        if not validated_data.get('code'):
            import random
            validated_data['code'] = f"EMP-{random.randint(10000, 99999)}"
            while Employee.objects.filter(code=validated_data['code']).exists():
                validated_data['code'] = f"EMP-{random.randint(10000, 99999)}"
        
        # If saving as draft, skip User creation and Email
        if status_val == 'Draft':
            employee = serializer.save(user=None)
            return
            
        # Generate a random 10-character password
        alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
        password = raw_data.get('password') or ''.join(secrets.choice(alphabet) for _ in range(10))

        if not email:
            raise exceptions.ValidationError({"email": "Email is required to create a user account."})

        # Check if user already exists
        if User.objects.filter(username=email).exists() or User.objects.filter(email=email).exists():
            raise exceptions.ValidationError({"email": "A user with this email already exists."})

        # 3. Create Django User
        user = User.objects.create_user(
            username=email,
            email=email,
            password=password,
            first_name=first_name,
            last_name=last_name
        )

        # 4. Save Employee with linked user
        employee = serializer.save(user=user)

        # 4.0 Add Create Audit Log
        try:
            from .models import EmployeeAuditLog
            performed_by = req_user.username if req_user and req_user.is_authenticated else 'System'
            EmployeeAuditLog.objects.create(
                employee=employee,
                action='Create',
                performed_by=performed_by,
                changes={"all": "Initial creation of record."}
            )
        except Exception as e:
            print(f"Failed to create audit log: {e}")


        # 4.1 Generate Offer Letter
        from .models import OfferLetter
        import uuid
        offer_num = f"OFF-{employee.code or str(uuid.uuid4())[:8].upper()}"
        OfferLetter.objects.create(
            employee=employee,
            offer_number=offer_num,
            status='Pending Approval'
        )

        # 5. Dispatch Welcome Email
        origin = self.request.headers.get('Origin', 'https://hrms.vibecopilot.ai')
        login_url = f"{origin}/" 
        subject = "Welcome to HRMS - Your Login Credentials"
        message = f"""Hello {first_name},

Welcome to the HRMS portal! Your account has been successfully created.

Website: {login_url}
Login ID: {email}
Password: {password}

Please log in and change your password immediately.

Regards,
HRMS Admin
"""
        try:
            import threading
            # Send email in background to prevent slow saving
            threading.Thread(target=send_mail, args=(
                subject,
                message,
                settings.DEFAULT_FROM_EMAIL,
                [email]
            ), kwargs={'fail_silently': True}).start()
        except Exception as e:
            print(f"Failed to send email to {email}: {e}")

        # 6. Sync with Organization Engine
        try:
            from org_engine.models import OrganizationNode, OrganizationNodeType
            emp_type, _ = OrganizationNodeType.objects.get_or_create(name='Employee')
            emp_name = f"{first_name} {last_name}"
            
            # Determine parent node based on assigned role
            parent_node = None
            if employee.dynamic_role:
                parent_node = OrganizationNode.objects.filter(
                    name=employee.dynamic_role.name, 
                    node_type__name='Role'
                ).first()
                if parent_node:
                    emp_node = OrganizationNode.objects.create(
                        name=emp_name,
                        node_type=emp_type,
                        parent=parent_node,
                        tenant_id=1
                    )
        except Exception as e:
            print(f"Failed to create Org Engine node for employee: {e}")

        # 7. CTC Notification Workflow
        creator_profile = getattr(req_user, 'employee_profile', None)
        creator_has_ctc = req_user.is_superuser or (creator_profile and creator_profile.dynamic_role and creator_profile.dynamic_role.permissions.get('can_add_ctc'))
        
        if (not employee.ctc or employee.ctc == 0) and not creator_has_ctc:
            from .models import Notification
            # Find all users with can_add_ctc or superusers
            superusers = User.objects.filter(is_superuser=True)
            for su in superusers:
                if hasattr(su, 'employee_profile'):
                    Notification.objects.create(
                        recipient=su.employee_profile,
                        title=f"New Employee Onboarded: {emp_name}",
                        message=f"Please add their CTC, PF, and Bonus credentials.",
                        related_employee_id=employee.id
                    )
            
            # Find roles with can_add_ctc
            from organisation.models import Role
            ctc_roles = [r for r in Role.objects.all() if r.permissions.get('can_add_ctc')]
            ctc_employees = Employee.objects.filter(dynamic_role__in=ctc_roles)
            for ctc_emp in ctc_employees:
                Notification.objects.create(
                    recipient=ctc_emp,
                    title=f"New Employee Onboarded: {emp_name}",
                    message=f"Please add their CTC, PF, and Bonus credentials.",
                    related_employee_id=employee.id
                )

    def update(self, request, *args, **kwargs):
        try:
            with open("update_debug.log", "w") as f:
                f.write(f"REQUEST DATA: {json.dumps(request.data)}\n")
        except:
            pass
        return super().update(request, *args, **kwargs)

    def perform_update(self, serializer):
        try:
            with open("update_debug.log", "a") as f:
                f.write(f"VALIDATED DATA: {serializer.validated_data}\n")
        except:
            pass
            
        validated_data = serializer.validated_data
        
        # Prevent wiping out the employee code during update
        if 'code' in validated_data and not validated_data['code']:
            validated_data.pop('code')
            
        old_status = serializer.instance.status
        new_status = validated_data.get('status', old_status)
            
        old_first = serializer.instance.first_name
        old_last = serializer.instance.last_name
        old_name = f"{old_first} {old_last}"
        old_role = serializer.instance.dynamic_role
        
        # Calculate diff before saving
        changes = {}
        for attr, new_val in validated_data.items():
            old_val = getattr(serializer.instance, attr, None)
            if old_val != new_val:
                changes[attr] = {'old': str(old_val), 'new': str(new_val)}
                
        emp = serializer.save()
        
        if changes:
            try:
                from .models import EmployeeAuditLog
                req_user = self.request.user
                performed_by = req_user.username if req_user and req_user.is_authenticated else 'System'
                EmployeeAuditLog.objects.create(
                    employee=emp,
                    action='Update',
                    performed_by=performed_by,
                    changes=changes
                )
            except Exception as e:
                print(f"Failed to create audit log for update: {e}")
        new_name = f"{emp.first_name} {emp.last_name}"
        
        # Draft to Active Transition
        if old_status == 'Draft' and new_status == 'Active' and not emp.user:
            email = emp.email
            from django.contrib.auth.models import User
            if email and not User.objects.filter(username=email).exists():
                import secrets
                import string
                import threading
                from django.core.mail import send_mail
                from django.conf import settings
                
                alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
                password = ''.join(secrets.choice(alphabet) for _ in range(10))
                
                user = User.objects.create_user(
                    username=email,
                    email=email,
                    password=password,
                    first_name=emp.first_name,
                    last_name=emp.last_name
                )
                emp.user = user
                emp.save(update_fields=['user'])
                
                origin = self.request.headers.get('Origin', 'https://hrms.vibecopilot.ai')
                login_url = f"{origin}/"
                subject = "Welcome to HRMS - Your Login Credentials"
                message = f"Hello {emp.first_name},\n\nWelcome to the HRMS portal! Your account has been successfully created.\n\nWebsite: {login_url}\nLogin ID: {email}\nPassword: {password}\n\nPlease log in and change your password immediately.\n\nRegards,\nHRMS Admin"
                try:
                    threading.Thread(target=send_mail, args=(subject, message, settings.DEFAULT_FROM_EMAIL, [email]), kwargs={'fail_silently': True}).start()
                except:
                    pass
                    
                # Generate Offer Letter
                from .models import OfferLetter
                import uuid
                offer_num = f"OFF-{emp.code or str(uuid.uuid4())[:8].upper()}"
                OfferLetter.objects.create(
                    employee=emp,
                    offer_number=offer_num,
                    status='Pending Approval'
                )

        try:
            from org_engine.models import OrganizationNode
            from org_engine.engine import HierarchyEngine
            
            emp_node = OrganizationNode.objects.filter(name=old_name, node_type__name='Employee').first()
            if emp_node:
                if old_name != new_name:
                    emp_node.name = new_name
                    emp_node.save(update_fields=['name'])
                    
                # If role changed
                if old_role != emp.dynamic_role:
                    if emp.dynamic_role:
                        new_parent_node = OrganizationNode.objects.filter(
                            name=emp.dynamic_role.name, 
                            node_type__name='Role'
                        ).first()
                        if new_parent_node and emp_node.parent_id != new_parent_node.id:
                            HierarchyEngine.move_node(emp_node, new_parent_node)
                    else:
                        # Role was removed, so remove them from the tree
                        emp_node.delete()
            else:
                # Node didn't exist, create it ONLY if they have a role
                if emp.dynamic_role:
                    from org_engine.models import OrganizationNodeType
                    emp_type, _ = OrganizationNodeType.objects.get_or_create(name='Employee')
                    
                    new_parent_node = OrganizationNode.objects.filter(
                        name=emp.dynamic_role.name, 
                        node_type__name='Role'
                    ).first()
                        
                    if new_parent_node:
                        OrganizationNode.objects.create(
                            name=new_name,
                            node_type=emp_type,
                            parent=new_parent_node,
                            tenant_id=1
                        )
        except Exception as e:
            print(f"Failed to sync org engine graph update: {e}")

    def perform_destroy(self, instance):
        try:
            from org_engine.models import OrganizationNode
            emp_name = f"{instance.first_name} {instance.last_name}"
            emp_node = OrganizationNode.objects.filter(name=emp_name, node_type__name='Employee').first()
            if emp_node:
                emp_node.delete()
        except Exception as e:
            print(f"Failed to sync org engine graph deletion: {e}")
        instance.delete()

    @action(detail=True, methods=['get'])
    def audit_logs(self, request, pk=None):
        employee = self.get_object()
        logs = employee.audit_logs.all().order_by('-timestamp')
        data = []
        for log in logs:
            data.append({
                'id': log.id,
                'action': log.action,
                'performed_by': log.performed_by,
                'changes': log.changes,
                'timestamp': log.timestamp.isoformat()
            })
        return Response(data)

from .models import EmployeeDocument, EmployeeTransfer, EmployeeExit
from .serializers import EmployeeDocumentSerializer, EmployeeTransferSerializer, EmployeeExitSerializer

class EmployeeDocumentViewSet(DataIsolationMixin, viewsets.ModelViewSet):
    queryset = EmployeeDocument.objects.all()
    serializer_class = EmployeeDocumentSerializer
    parser_classes = [MultiPartParser]
    
    def get_queryset(self):
        queryset = super().get_queryset()
        employee_id = self.request.query_params.get('employee')
        if employee_id:
            queryset = queryset.filter(employee_id=employee_id)
        return queryset

class EmployeeTransferViewSet(DataIsolationMixin, viewsets.ModelViewSet):
    queryset = EmployeeTransfer.objects.all()
    serializer_class = EmployeeTransferSerializer
    
    def perform_update(self, serializer):
        transfer = serializer.save()
        # Auto-apply transfer if status changes to Executed
        if transfer.status == 'Executed':
            emp = transfer.employee
            if transfer.new_department: emp.department = transfer.new_department
            if transfer.new_designation: emp.designation = transfer.new_designation
            if transfer.new_site: emp.site = transfer.new_site
            if transfer.new_manager: emp.manager = transfer.new_manager
            emp.save()

class EmployeeExitViewSet(DataIsolationMixin, viewsets.ModelViewSet):
    queryset = EmployeeExit.objects.all()
    serializer_class = EmployeeExitSerializer
    
    def perform_update(self, serializer):
        exit_process = serializer.save()
        if exit_process.status == 'Completed':
            emp = exit_process.employee
            emp.status = 'Exited'
            emp.save()
            if emp.user:
                emp.user.is_active = False
                emp.user.save()

class NotificationViewSet(viewsets.ViewSet):
    permission_classes = [IsAuthenticated]
    
    def list(self, request):
        user = request.user
        if not hasattr(user, 'employee_profile'):
            return Response([])
            
        from .models import Notification
        notifs = Notification.objects.filter(recipient=user.employee_profile, is_read=False).order_by('-created_at')
        
        data = []
        for n in notifs:
            data.append({
                'id': n.id,
                'title': n.title,
                'message': n.message,
                'related_run_id': n.related_run_id,
                'related_employee_id': n.related_employee_id,
                'created_at': n.created_at.isoformat()
            })
        return Response(data)
        
    @action(detail=True, methods=['post'])
    def mark_read(self, request, pk=None):
        from .models import Notification
        try:
            n = Notification.objects.get(pk=pk, recipient=request.user.employee_profile)
            n.is_read = True
            n.save()
            return Response({'status': 'success'})
        except Notification.DoesNotExist:
            return Response({'error': 'Not found'}, status=404)

from .models import OfferLetter, OfferTemplate
from .serializers import OfferLetterSerializer, OfferTemplateSerializer

from rest_framework.parsers import MultiPartParser, FormParser, JSONParser

class OfferTemplateViewSet(DataIsolationMixin, viewsets.ModelViewSet):
    rbac_module = 'Offer Templates'
    queryset = OfferTemplate.objects.all()
    serializer_class = OfferTemplateSerializer
    permission_classes = [IsAuthenticated]
    parser_classes = [MultiPartParser, FormParser, JSONParser]

class OfferLetterViewSet(viewsets.ModelViewSet):
    rbac_module = 'Offer Letters'
    queryset = OfferLetter.objects.all().order_by('-created_at')
    serializer_class = OfferLetterSerializer
    permission_classes = [IsAuthenticated]

    @action(detail=False, methods=['get'])
    def dashboard_metrics(self, request):
        from django.db.models import Count
        metrics = self.queryset.values('status').annotate(count=Count('status'))
        metrics_dict = {m['status']: m['count'] for m in metrics}
        
        # Default all statuses to 0
        all_statuses = dict(OfferLetter.STATUS_CHOICES)
        final_metrics = {k: metrics_dict.get(k, 0) for k in all_statuses.keys()}
        
        from datetime import date
        from django.db.models.functions import Coalesce
        today = date.today()
        upcoming_qs = self.queryset.annotate(
            effective_joining_date=Coalesce('joining_date', 'employee__doj')
        ).filter(
            status__in=['Pending Approval', 'Awaiting Acceptance', 'Accepted'],
            effective_joining_date__gte=today
        ).order_by('effective_joining_date')[:5]
        
        upcoming = OfferLetterSerializer(upcoming_qs, many=True).data
        
        recent_qs = self.queryset.all().order_by('-created_at')[:5]
        recent = OfferLetterSerializer(recent_qs, many=True).data
        
        return Response({
            'metrics': final_metrics,
            'upcoming': upcoming,
            'recent': recent
        })

    def _render_offer_html(self, employee, template_id, request_user=None):
        from .models import OfferTemplate
        import re
        import datetime
        from django.conf import settings
        
        template = OfferTemplate.objects.get(id=template_id)
        body = template.body_html or ""
        
        # Safe access to related fields
        first_name = employee.first_name or ""
        last_name = employee.last_name or ""
        candidate_name = f"{first_name} {last_name}".strip()
        
        designation = "Employee"
        if employee.designation:
            designation = employee.designation.title
            
        entity_name = "Our Company"
        if employee.site and employee.site.branch and employee.site.branch.entity:
            entity_name = employee.site.branch.entity.name
        
        # Additional Safe Access
        department = employee.department.name if employee.department else "N/A"
        reporting_manager = f"{employee.manager.first_name} {employee.manager.last_name}".strip() if employee.manager else "N/A"
        employment_type = employee.employee_type or "Full Time"
        work_location = employee.site.name if employee.site else "N/A"
        joining_date = employee.doj.strftime("%Y-%m-%d") if employee.doj else "TBD"
        employee_id = employee.code or "TBD"
        
        # CTC Calculations (50% Basic, 25% HRA, 25% Special Allowance)
        ctc_annual = float(employee.ctc or 0)
        ctc_monthly = round(ctc_annual / 12, 2)
        
        variable_annual = float(employee.bonus_value or 0)
        fixed_annual = ctc_annual - variable_annual if ctc_annual > variable_annual else ctc_annual
        fixed_monthly = round(fixed_annual / 12, 2)
        
        basic_annual = round(fixed_annual * 0.50, 2)
        basic_monthly = round(fixed_monthly * 0.50, 2)
        hra_annual = round(fixed_annual * 0.25, 2)
        hra_monthly = round(fixed_monthly * 0.25, 2)
        special_annual = fixed_annual - basic_annual - hra_annual
        special_monthly = fixed_monthly - basic_monthly - hra_monthly
        
        # Deductions (Default estimates)
        professional_tax_monthly = 200.00 if fixed_monthly > 15000 else 0.00
        provident_fund_monthly = 0.00
        esi_monthly = 0.00
        tds_monthly = 0.00
        
        total_deductions_monthly = professional_tax_monthly + provident_fund_monthly + esi_monthly + tds_monthly
        net_pay_monthly = fixed_monthly - total_deductions_monthly
        
        professional_tax_annual = professional_tax_monthly * 12
        provident_fund_annual = provident_fund_monthly * 12
        esi_annual = esi_monthly * 12
        tds_annual = tds_monthly * 12
        total_deductions_annual = total_deductions_monthly * 12
        net_pay_annual = net_pay_monthly * 12
        
        # Simple Number to Words fallback
        try:
            # You can install num2words in the future: from num2words import num2words
            net_pay_in_words = f"{int(net_pay_monthly)} Rupees Only"
        except:
            net_pay_in_words = f"{net_pay_monthly} Rupees Only"
        
        acceptance_deadline = (datetime.datetime.now() + datetime.timedelta(days=7)).strftime("%Y-%m-%d")
        
        # Dynamic HR Details
        hr_name = "HR Department"
        hr_designation = "Human Resources"
        hr_email = getattr(settings, 'DEFAULT_FROM_EMAIL', 'hr@example.com')
        hr_contact = "+91 9876543210"

        if request_user and request_user.is_authenticated:
            hr_name = f"{request_user.first_name} {request_user.last_name}".strip() or request_user.username
            hr_email = request_user.email or hr_email
            if hasattr(request_user, 'employee_profile') and request_user.employee_profile:
                if request_user.employee_profile.designation:
                    hr_designation = request_user.employee_profile.designation.title
                if request_user.employee_profile.phone:
                    hr_contact = request_user.employee_profile.phone
        
        # Comprehensive placeholder replacement
        replacements = {
            '{{companyName}}': entity_name,
            '{{entity_name}}': entity_name,
            '{{currentDate}}': datetime.datetime.now().strftime("%Y-%m-%d"),
            '{{issue_date}}': datetime.datetime.now().strftime("%Y-%m-%d"),
            '{{candidateName}}': candidate_name,
            '{{candidate_name}}': candidate_name,
            '{{candidateAddress}}': employee.address or "Address on file",
            '{{candidate_address}}': employee.address or "Address on file",
            '{{designation}}': designation,
            '{{department}}': department,
            '{{employmentType}}': employment_type,
            '{{employment_type}}': employment_type,
            '{{workLocation}}': work_location,
            '{{work_location}}': work_location,
            '{{joiningDate}}': joining_date,
            '{{joining_date}}': joining_date,
            '{{reportingManager}}': reporting_manager,
            '{{reporting_manager}}': reporting_manager,
            '{{probationPeriod}}': "6 months",
            '{{probation_period}}': "6 months",
            '{{workingHours}}': "9:00 AM to 6:00 PM",
            '{{working_hours}}': "9:00 AM to 6:00 PM",
            '{{employee_id}}': employee_id,
            '{{working_days}}': "Monday to Friday",
            
            # CTC Details
            '{{totalCtcAnnual}}': f"{ctc_annual:,.2f}",
            '{{ctc}}': f"{ctc_annual:,.2f}",
            '{{totalCtcMonthly}}': f"{ctc_monthly:,.2f}",
            '{{monthly_gross}}': f"{ctc_monthly:,.2f}",
            '{{totalFixedAnnual}}': f"{fixed_annual:,.2f}",
            '{{total_fixed_annual}}': f"{fixed_annual:,.2f}",
            '{{totalFixedMonthly}}': f"{fixed_monthly:,.2f}",
            '{{total_fixed_monthly}}': f"{fixed_monthly:,.2f}",
            '{{basicSalaryAnnual}}': f"{basic_annual:,.2f}",
            '{{basic_salary_annual}}': f"{basic_annual:,.2f}",
            '{{basicSalaryMonthly}}': f"{basic_monthly:,.2f}",
            '{{basic_salary_monthly}}': f"{basic_monthly:,.2f}",
            '{{hraAnnual}}': f"{hra_annual:,.2f}",
            '{{hra_annual}}': f"{hra_annual:,.2f}",
            '{{hraMonthly}}': f"{hra_monthly:,.2f}",
            '{{hra_monthly}}': f"{hra_monthly:,.2f}",
            '{{specialAllowanceAnnual}}': f"{special_annual:,.2f}",
            '{{special_allowance_annual}}': f"{special_annual:,.2f}",
            '{{specialAllowanceMonthly}}': f"{special_monthly:,.2f}",
            '{{special_allowance_monthly}}': f"{special_monthly:,.2f}",
            '{{variableAnnual}}': f"{variable_annual:,.2f}",
            '{{variable_pay}}': f"{variable_annual:,.2f}",
            '{{bonus}}': f"{variable_annual:,.2f}",
            
            # Deductions Details
            '{{professionalTaxMonthly}}': f"{professional_tax_monthly:,.2f}",
            '{{professional_tax_monthly}}': f"{professional_tax_monthly:,.2f}",
            '{{professionalTaxAnnual}}': f"{professional_tax_annual:,.2f}",
            '{{professional_tax_annual}}': f"{professional_tax_annual:,.2f}",
            '{{providentFundMonthly}}': f"{provident_fund_monthly:,.2f}",
            '{{provident_fund_monthly}}': f"{provident_fund_monthly:,.2f}",
            '{{providentFundAnnual}}': f"{provident_fund_annual:,.2f}",
            '{{provident_fund_annual}}': f"{provident_fund_annual:,.2f}",
            '{{esiMonthly}}': f"{esi_monthly:,.2f}",
            '{{esi_monthly}}': f"{esi_monthly:,.2f}",
            '{{esiAnnual}}': f"{esi_annual:,.2f}",
            '{{esi_annual}}': f"{esi_annual:,.2f}",
            '{{tdsMonthly}}': f"{tds_monthly:,.2f}",
            '{{tds_monthly}}': f"{tds_monthly:,.2f}",
            '{{tdsAnnual}}': f"{tds_annual:,.2f}",
            '{{tds_annual}}': f"{tds_annual:,.2f}",
            '{{totalDeductionsMonthly}}': f"{total_deductions_monthly:,.2f}",
            '{{total_deductions_monthly}}': f"{total_deductions_monthly:,.2f}",
            '{{totalDeductionsAnnual}}': f"{total_deductions_annual:,.2f}",
            '{{total_deductions_annual}}': f"{total_deductions_annual:,.2f}",
            '{{netPayMonthly}}': f"{net_pay_monthly:,.2f}",
            '{{net_payable_monthly}}': f"{net_pay_monthly:,.2f}",
            '{{netPayAnnual}}': f"{net_pay_annual:,.2f}",
            '{{net_payable_annual}}': f"{net_pay_annual:,.2f}",
            '{{netPayInWords}}': net_pay_in_words,
            
            # HR Details
            '{{acceptanceDueDate}}': acceptance_deadline,
            '{{acceptance_deadline}}': acceptance_deadline,
            '{{hrManagerName}}': hr_name,
            '{{hr_name}}': hr_name,
            '{{hrDesignation}}': hr_designation,
            '{{hr_designation}}': hr_designation,
            '{{hrEmail}}': hr_email,
            '{{hrContact}}': hr_contact,
        }
        
        for key, val in replacements.items():
            body = body.replace(key, str(val))
        
        # If any placeholders remain unresolved, highlight them (user requested black text)
        body = re.sub(r'\{\{[^}]+\}\}', '<span style="color: black; font-weight: bold;">[Data Missing]</span>', body)
        
        # (Removed aggressive table regex replacements to preserve custom HTML layouts)        
        # Clean up doctype to avoid nested wrapping issues
        body = re.sub(r'<!DOCTYPE[^>]*>', '', body, flags=re.IGNORECASE).strip()
        
        # Determine dynamic header and footer
        if template.header_html:
            header_content = f'<div id="header_content">{template.header_html}</div>'
        else:
            header_content = '<div id="header_content"></div>'

        if template.footer_html:
            footer_content = f'<div id="footer_content">{template.footer_html}</div>'
        else:
            footer_content = '<div id="footer_content"></div>'

        # Fix page breaks for xhtml2pdf (robust regex for any tag with page-break-before/after: always)
        # First, handle self-closing tags like <hr>
        body = re.sub(r'<hr[^>]*?page-break-[^>]*?>', '<pdf:nextpage />', body, flags=re.IGNORECASE)
        # Handle empty divs used for page breaks
        body = re.sub(r'<div[^>]*?page-break-[^>]*?>\s*</div>', '<pdf:nextpage />', body, flags=re.IGNORECASE)
        # Handle <p> tags with page break
        body = re.sub(r'<p[^>]*?page-break-[^>]*?>\s*</p>', '<pdf:nextpage />', body, flags=re.IGNORECASE)
        
        # Clean up consecutive or trailing page breaks to prevent blank pages
        body = re.sub(r'(<pdf:nextpage />\s*)+', '<pdf:nextpage />', body, flags=re.IGNORECASE)
        body = re.sub(r'<pdf:nextpage />\s*$', '', body, flags=re.IGNORECASE)
        
        # Wrap in HTML skeleton with basic styles for PDF/Email compatibility
        if not body.lower().startswith('<html'):
            body = f"""
            <html>
            <head>
                <meta charset="UTF-8">
                <style>
                    @page {{
                        size: a4 portrait;
                        margin-top: 80pt;
                        margin-bottom: 80pt;
                        margin-left: 50pt;
                        margin-right: 50pt;
                        @frame header_frame {{
                            -pdf-frame-content: header_content;
                            left: 30pt; width: 535pt; top: 15pt; height: 65pt;
                        }}
                        @frame footer_frame {{
                            -pdf-frame-content: footer_content;
                            left: 30pt; width: 535pt; bottom: 15pt; height: 65pt;
                        }}
                    }}
                    body {{
                        font-family: Helvetica, Arial, sans-serif;
                        font-size: 10pt;
                        line-height: 1.4;
                        color: #333333;
                    }}
                    p {{
                        margin-top: 0;
                        margin-bottom: 10pt;
                    }}
                    h1, h2, h3, h4 {{
                        color: #0f172a;
                        margin-bottom: 8px;
                        margin-top: 12px;
                    }}
                    .text-right {{ text-align: right; }}
                    .text-center {{ text-align: center; }}
                    .font-bold {{ font-weight: bold; }}
                </style>
            </head>
            <body>
                {header_content}
                {footer_content}
                <div style="padding-top: 5pt;">
                    {body}
                </div>
            </body>
            </html>
            """
            
        return body, entity_name

    def send_offer_email(self, instance, template_id, email_body_text=""):
            from django.core.mail import EmailMessage
            from django.conf import settings
            from django.core.files.base import ContentFile
            import os

            def link_callback(uri, rel):
                sUrl = settings.STATIC_URL
                sRoot = getattr(settings, 'STATIC_ROOT', None)
                mUrl = settings.MEDIA_URL
                mRoot = settings.MEDIA_ROOT
                
                # Handle absolute URLs by stripping the domain
                import urllib.parse
                parsed = urllib.parse.urlparse(uri)
                path = parsed.path
                
                # Handle the proxy prefix
                if path.startswith('/api/media/'):
                    path = path.replace('/api/media/', '/media/')
                    
                if path.startswith(mUrl):
                    local_path = os.path.join(mRoot, path.replace(mUrl, ""))
                elif sUrl and path.startswith(sUrl):
                    local_path = os.path.join(sRoot, path.replace(sUrl, ""))
                else:
                    return uri
                    
                if not os.path.isfile(local_path):
                    return uri
                return local_path

            try:
                request_user = getattr(self, 'request', None).user if getattr(self, 'request', None) else None
                subject = f"Offer of Employment - {entity_name}"
                
                email_body_text = self.request.data.get('email_body_text', '')
                if email_body_text:
                    formatted_lines = []
                    for line in email_body_text.splitlines():
                        if line.strip():
                            formatted_lines.append(f"<div>{line}</div>")
                        else:
                            formatted_lines.append("<br>")
                    formatted_text = "\n".join(formatted_lines)
                    email_body = f"""
                    <html>
                    <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
                        {formatted_text}
                    </body>
                    </html>
                    """
                else:
                    designation = instance.employee.designation.title if getattr(instance.employee, 'designation', None) else 'Employee'
                    email_body = f"""
                    <html>
                    <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
                        <p>Dear <strong>{instance.employee.first_name}</strong>,</p>
                        <p>Congratulations!</p>
                        <p>We are thrilled to extend an offer for the position of <strong>{designation}</strong> at <strong>{entity_name}</strong>.</p>
                        <p>Please find your detailed offer letter attached to this email. Kindly review the document, and if you choose to accept, follow the instructions provided within the attachment.</p>
                        <p>If you have any questions or need further clarification, please feel free to reach out.</p>
                        <br>
                        <p>Best regards,</p>
                        <p><strong>HR Department</strong><br>{entity_name}</p>
                    </body>
                    </html>
                    """
                
                msg = EmailMessage(
                    subject=subject,
                    body=email_body,
                    from_email=getattr(settings, 'EMAIL_HOST_USER', getattr(settings, 'DEFAULT_FROM_EMAIL', 'hr@example.com')),
                    to=[instance.employee.email],
                )
                msg.content_subtype = "html"
                
                # Generate PDF
                pdf_bytes = None
                try:
                    from xhtml2pdf import pisa
                    from io import BytesIO
                    result = BytesIO()
                    
                    # xhtml2pdf does not support SVG and it breaks layout, strip it for PDF only
                    import re
                    pdf_body = re.sub(r'<svg.*?>.*?</svg>', '', body, flags=re.DOTALL | re.IGNORECASE)
                    
                    pdf = pisa.pisaDocument(BytesIO(pdf_body.encode("UTF-8")), result, link_callback=link_callback)
                    if not pdf.err:
                        pdf_bytes = result.getvalue()
                        instance.pdf_file.save(f"{instance.offer_number}.pdf", ContentFile(pdf_bytes), save=True)
                        msg.attach(f"Offer_Letter_{instance.employee.first_name}_{instance.employee.last_name}.pdf", pdf_bytes, 'application/pdf')
                except ImportError:
                    print("xhtml2pdf not installed. Skipping PDF attachment.")
                except Exception as e:
                    print("PDF generation failed:", e)
                
                import threading
                def send_async_email(email_msg):
                    try:
                        email_msg.send(fail_silently=False)
                    except Exception as ex:
                        print("Async email send failed:", ex)
                threading.Thread(target=send_async_email, args=(msg,), daemon=True).start()
            except Exception as e:
                print("Failed to prepare offer email:", e)

    @action(detail=False, methods=['post'])
    def preview_email(self, request):
        employee_id = request.data.get('employee_id')
        template_id = request.data.get('template_id')
        if not employee_id or not template_id:
            return Response({"error": "employee_id and template_id are required"}, status=400)
            
        try:
            employee = Employee.objects.get(id=employee_id)
            html, _ = self._render_offer_html(employee, template_id, request.user)
            return Response({"html": html})
        except Employee.DoesNotExist:
            return Response({"error": "Employee not found"}, status=404)
        except Exception as e:
            return Response({"error": str(e)}, status=500)

    @action(detail=False, methods=['post'])
    def send_custom_email(self, request):
        employee_id = request.data.get('employee_id')
        template_id = request.data.get('template_id')
        html_content = request.data.get('html_content')
        
        import re
        
        # Clean up doctype to avoid nested wrapping issues
        html_content = re.sub(r'<!DOCTYPE[^>]*>', '', html_content, flags=re.IGNORECASE).strip()
        
        # (Removed aggressive table regex replacements to preserve custom HTML layouts)
        # Wrap in HTML skeleton with basic styles if missing
        if html_content and not html_content.lower().startswith('<html'):
            html_content = f"""
            <html>
            <head>
                <style>
                    @page {{
                        size: a4 portrait;
                        margin: 2cm;
                    }}
                    body {{
                        font-family: Helvetica, Arial, sans-serif;
                        font-size: 10pt;
                        line-height: 1.6;
                        color: #333333;
                    }}
                    h1, h2, h3, h4 {{
                        color: #0f172a;
                        margin-bottom: 12px;
                        margin-top: 16px;
                    }}
                    .text-right {{ text-align: right; }}
                    .text-center {{ text-align: center; }}
                    .font-bold {{ font-weight: bold; }}
                </style>
            </head>
            <body>
                {html_content}
            </body>
            </html>
            """
        
        if not employee_id or not template_id or not html_content:
            return Response({"error": "employee_id, template_id, and html_content are required"}, status=400)
            
        try:
            employee = Employee.objects.get(id=employee_id)
            
            from .models import OfferLetter
            import uuid
            
            offer = OfferLetter.objects.filter(employee=employee).first()
            if not offer:
                offer_num = f"OFF-{employee.code or str(uuid.uuid4())[:8].upper()}"
                offer = OfferLetter.objects.create(
                    employee=employee,
                    offer_number=offer_num,
                    status='Awaiting Acceptance'
                )
            else:
                offer.status = 'Awaiting Acceptance'
                offer.save()
            
            from django.core.mail import EmailMessage
            from django.conf import settings
            from django.core.files.base import ContentFile
            
            entity_name = "Our Company"
            if employee.site and employee.site.branch and employee.site.branch.entity:
                entity_name = employee.site.branch.entity.name
                
            subject = f"Offer of Employment - {entity_name}"
            
            email_body_text = request.data.get('email_body_text', '')
            if email_body_text:
                formatted_lines = []
                for line in email_body_text.splitlines():
                    if line.strip():
                        formatted_lines.append(f"<div>{line}</div>")
                    else:
                        formatted_lines.append("<br>")
                formatted_text = "\n".join(formatted_lines)
                email_body = f"""
                <html>
                <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
                    {formatted_text}
                </body>
                </html>
                """
            else:
                designation = employee.designation.title if getattr(employee, 'designation', None) else 'Employee'
                email_body = f"""
                <html>
                <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
                    <p>Dear <strong>{employee.first_name}</strong>,</p>
                    <p>Congratulations!</p>
                    <p>We are thrilled to extend an offer for the position of <strong>{designation}</strong> at <strong>{entity_name}</strong>.</p>
                    <p>Please find your detailed offer letter attached to this email. Kindly review the document, and if you choose to accept, follow the instructions provided within the attachment.</p>
                    <p>If you have any questions or need further clarification, please feel free to reach out.</p>
                    <br>
                    <p>Best regards,</p>
                    <p><strong>HR Department</strong><br>{entity_name}</p>
                </body>
                </html>
                """
            
            msg = EmailMessage(
                subject=subject,
                body=email_body,
                from_email=getattr(settings, 'EMAIL_HOST_USER', getattr(settings, 'DEFAULT_FROM_EMAIL', 'hr@example.com')),
                to=[employee.email],
            )
            msg.content_subtype = "html"
            
            # Generate PDF using xhtml2pdf if installed
            pdf_bytes = None
            try:
                from xhtml2pdf import pisa
                from io import BytesIO
                import os
                
                def link_callback(uri, rel):
                    sUrl = settings.STATIC_URL
                    sRoot = getattr(settings, 'STATIC_ROOT', None)
                    mUrl = settings.MEDIA_URL
                    mRoot = settings.MEDIA_ROOT
                    
                    # Handle absolute URLs by stripping the domain
                    import urllib.parse
                    parsed = urllib.parse.urlparse(uri)
                    path = parsed.path
                    
                    # Handle the proxy prefix
                    if path.startswith('/api/media/'):
                        path = path.replace('/api/media/', '/media/')
                        
                    if path.startswith(mUrl):
                        local_path = os.path.join(mRoot, path.replace(mUrl, ""))
                    elif sUrl and path.startswith(sUrl):
                        local_path = os.path.join(sRoot, path.replace(sUrl, ""))
                    else:
                        return uri
                        
                    if not os.path.isfile(local_path):
                        return uri
                    return local_path

                result = BytesIO()
                
                # xhtml2pdf does not support SVG and it breaks layout, strip it for PDF only
                pdf_html_content = re.sub(r'<svg.*?>.*?</svg>', '', html_content, flags=re.DOTALL | re.IGNORECASE)
                
                # Ensure the HTML has the correct meta charset for xhtml2pdf
                if '<head>' in pdf_html_content.lower() and 'charset' not in pdf_html_content.lower():
                    pdf_html_content = re.sub(r'<head>', '<head><meta charset="UTF-8">', pdf_html_content, flags=re.IGNORECASE)

                pdf = pisa.pisaDocument(BytesIO(pdf_html_content.encode("UTF-8")), result, encoding="UTF-8", link_callback=link_callback)
                if not pdf.err:
                    pdf_bytes = result.getvalue()
                    # Save PDF to model
                    if offer:
                        offer.pdf_file.save(f"{offer.offer_number}.pdf", ContentFile(pdf_bytes), save=True)
                    # Attach to email
                    msg.attach(f"Offer_Letter_{employee.first_name}_{employee.last_name}.pdf", pdf_bytes, 'application/pdf')
            except ImportError:
                print("xhtml2pdf not installed. Skipping PDF attachment.")
            except Exception as e:
                print("PDF generation failed:", e)
            
            import threading
            def send_async_email(email_msg):
                try:
                    email_msg.send(fail_silently=False)
                except Exception as ex:
                    print("Async email send failed:", ex)
            threading.Thread(target=send_async_email, args=(msg,), daemon=True).start()
            
            return Response({"status": "success", "message": "Custom offer sent with PDF attachment (if xhtml2pdf installed)"})
        except Employee.DoesNotExist:
            return Response({"error": "Employee not found"}, status=404)
        except Exception as e:
            return Response({"error": str(e)}, status=500)

    def perform_create(self, serializer):
        instance = serializer.save()
        template_id = self.request.data.get('template_id')
        email_body_text = self.request.data.get('email_body_text', '')
        if instance.status == 'Awaiting Acceptance' and template_id:
            self.send_offer_email(instance, template_id, email_body_text)

    def perform_update(self, serializer):
        old_status = self.get_object().status
        instance = serializer.save()
        
        template_id = self.request.data.get('template_id')
        email_body_text = self.request.data.get('email_body_text', '')
        if instance.status == 'Awaiting Acceptance' and template_id:
            self.send_offer_email(instance, template_id, email_body_text)
        
        # Trigger email if accepted
        if old_status != 'Accepted' and instance.status == 'Accepted':
            from django.core.mail import send_mail
            from django.conf import settings
            subject = f"Offer Accepted - {instance.employee.first_name} {instance.employee.last_name}"
            message = f"Offer letter {instance.offer_number} has been accepted by {instance.employee.first_name} {instance.employee.last_name}."
            send_mail(
                subject,
                message,
                getattr(settings, 'EMAIL_HOST_USER', getattr(settings, 'DEFAULT_FROM_EMAIL', 'hr@example.com')),
                [instance.employee.email, getattr(settings, 'EMAIL_HOST_USER', getattr(settings, 'DEFAULT_FROM_EMAIL', 'hr@example.com'))],
                fail_silently=True,
            )


from rest_framework.views import APIView
from django.db.models import Q
from authentication.permissions import isolate_queryset

class GlobalSearchAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, *args, **kwargs):
        q = request.query_params.get('q', '').strip()
        if not q:
            return Response([])

        results = []

        # Search Employees
        emp_qs = Employee.objects.filter(
            Q(first_name__icontains=q) | 
            Q(last_name__icontains=q) | 
            Q(email__icontains=q) | 
            Q(code__icontains=q)
        )
        emp_qs = isolate_queryset(emp_qs, request.user)[:5]
        for emp in emp_qs:
            results.append({
                'id': emp.id,
                'type': 'employee',
                'title': f"{emp.first_name} {emp.last_name}",
                'subtitle': f"{emp.code} • {emp.email}",
                'url': f"/employees?edit={emp.id}&tab=personal"
            })

        # Search Sites
        from organisation.models import Site
        site_qs = Site.objects.filter(name__icontains=q)
        site_qs = isolate_queryset(site_qs, request.user)[:5]
        for site in site_qs:
            city = site.branch.city if site.branch and hasattr(site.branch, 'city') else 'No City'
            code = site.site_code if site.site_code else ''
            results.append({
                'id': site.id,
                'type': 'site',
                'title': site.name,
                'subtitle': f"{city} • {code}",
                'url': f"/organisation/sites"
            })

        return Response(results)
