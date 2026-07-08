from rest_framework import viewsets
from rest_framework.decorators import action
from rest_framework.response import Response
from authentication.permissions import IsSuperAdmin
from .models import Organization, Invoice
from .serializers import OrganizationSerializer, InvoiceSerializer
from django.core.mail import send_mail
from django.conf import settings
from django.contrib.auth.models import User
import random
import string
import threading
from django.core.mail import send_mail
from django.conf import settings

def send_mail_sync(subject, message, recipient_list):
    try:
        send_mail(
            subject,
            message,
            getattr(settings, 'EMAIL_HOST_USER', 'noreply@vibecopilot.ai'),
            recipient_list,
            fail_silently=False
        )
    except Exception as e:
        raise Exception(f"SMTP Error: {str(e)}")

def generate_random_password(length=12):
    characters = string.ascii_letters + string.digits + "!@#$%^&*"
    return ''.join(random.choice(characters) for i in range(length))

def provision_organization_admin(org):
    email = org.billing_contact_email
    if not email:
        if org.sub_domain and '@' in org.sub_domain:
            email = org.sub_domain
        elif org.sub_domain:
            domain_part = org.sub_domain.replace('https://', '').replace('.peoplepulse.com', '')
            email = f"admin@{domain_part}.peoplepulse.com"
        else:
            return
            
    password = generate_random_password()
    
    user = User.objects.filter(username=email).first()
    if user:
        if not user.is_superuser:
            user.set_password(password)
            user.save()
        subject = f"You have been assigned as Admin for {org.name}"
        message = f"Hello Admin,\n\nYou have been assigned as the Admin for {org.name}.\n\nWebsite URL: http://localhost:5173\nLogin ID: {email}\nPassword: {password if not user.is_superuser else '[Your existing password]'}\n\nPlease log in and change your password.\n\nBest regards,\nVibeCopilot Team"
        
        import threading
        threading.Thread(target=send_mail_sync, args=(subject, message, [email])).start()
    else:
        password = generate_random_password()
        user = User.objects.create_user(
            username=email,
            email=email,
            password=password,
            first_name="Org Admin"
        )
        try:
            from employees.models import Employee
            from organisation.models import Role
            role_obj, _ = Role.objects.get_or_create(name='Org Admin', defaults={'code': 'ORG_ADMIN'})
            Employee.objects.create(
                user=user,
                first_name="Org",
                last_name="Admin",
                email=email,
                code=f"EMP-{user.id:04d}",
                role='admin',
                dynamic_role=role_obj,
                status='Active',
                organization=org
            )
        except Exception as e:
            print(f"Failed to create employee profile: {e}")
            
        subject = f"Welcome to VibeCopilot - Admin Credentials"
        message = f"Hello Admin,\n\nAn account has been created for you as the Admin for {org.name}.\n\nWebsite URL: http://localhost:5173\nLogin ID: {email}\nPassword: {password}\n\nPlease log in and change your password.\n\nBest regards,\nVibeCopilot Team"
        
        import threading
        threading.Thread(target=send_mail_sync, args=(subject, message, [email])).start()


class OrganizationViewSet(viewsets.ModelViewSet):
    permission_classes = [IsSuperAdmin]
    queryset = Organization.objects.all()
    serializer_class = OrganizationSerializer

    def perform_create(self, serializer):
        org = serializer.save()
        provision_organization_admin(org)
        
    @action(detail=True, methods=['post'], url_path='resend-email')
    def resend_email(self, request, pk=None):
        org = self.get_object()
        try:
            provision_organization_admin(org)
            return Response({"status": "Email sent successfully"})
        except Exception as e:
            return Response({"error": str(e)}, status=500)

class InvoiceViewSet(viewsets.ModelViewSet):
    permission_classes = [IsSuperAdmin]
    queryset = Invoice.objects.all()
    serializer_class = InvoiceSerializer
    filterset_fields = ['organization']
