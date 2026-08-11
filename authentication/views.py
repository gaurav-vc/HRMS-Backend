from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated
from rest_framework_simplejwt.views import TokenObtainPairView
from rest_framework_simplejwt.tokens import RefreshToken
from django.utils import timezone
from .models import LoginAuditLog
from .serializers import CustomTokenObtainPairSerializer, UserProfileSerializer

from django.contrib.auth.models import User
from django.contrib.auth.tokens import default_token_generator
from django.utils.http import urlsafe_base64_encode, urlsafe_base64_decode
from django.utils.encoding import force_bytes, force_str
from django.core.mail import send_mail
from django.conf import settings

class CustomTokenObtainPairView(TokenObtainPairView):
    serializer_class = CustomTokenObtainPairSerializer

    def post(self, request, *args, **kwargs):
        try:
            return super().post(request, *args, **kwargs)
        except Exception as e:
            ip_address = request.META.get('REMOTE_ADDR')
            attempted_username = request.data.get('username') or request.data.get('email')
            user = User.objects.filter(username=attempted_username).first() or User.objects.filter(email=attempted_username).first()
            
            LoginAuditLog.objects.create(
                user=user,
                attempted_username=attempted_username,
                ip_address=ip_address,
                status='FAILED'
            )
            raise e

class UserProfileView(APIView):
    permission_classes = [IsAuthenticated]
    
    def get(self, request):
        # Auto-create employee profile for superadmin if missing
        if request.user.is_superuser and not hasattr(request.user, 'employee_profile'):
            try:
                from employees.models import Employee
                from organisation.models import Role
                
                super_role = Role.objects.filter(name='Super Admin').first()
                Employee.objects.create(
                    user=request.user,
                    first_name=request.user.first_name or request.user.username,
                    last_name=request.user.last_name or '',
                    email=request.user.email or request.user.username,
                    code=f"EMP-{request.user.id:04d}",
                    role='super_admin',
                    dynamic_role=super_role,
                    status='Active',
                    doj=timezone.now().date()
                )
                # Refresh user object to ensure attribute is loaded
                request.user.refresh_from_db()
            except Exception as e:
                print(f"Failed to auto-create employee profile: {e}")

        serializer = UserProfileSerializer(request.user)
        return Response(serializer.data)

class LogoutView(APIView):
    permission_classes = [IsAuthenticated]
    
    def post(self, request):
        try:
            refresh_token = request.data.get("refresh")
            token = RefreshToken(refresh_token)
            token.blacklist()
            
            # Update audit log
            latest_log = LoginAuditLog.objects.filter(user=request.user, status='SUCCESS').order_by('-login_time').first()
            if latest_log:
                latest_log.logout_time = timezone.now()
                latest_log.save()
                
            return Response(status=status.HTTP_205_RESET_CONTENT)
        except Exception as e:
            return Response(status=status.HTTP_400_BAD_REQUEST)

class PasswordResetRequestView(APIView):
    def post(self, request):
        email = request.data.get('email')
        if not email:
            return Response({"error": "Email is required"}, status=status.HTTP_400_BAD_REQUEST)
            
        user = User.objects.filter(email=email).first()
        if user:
            token = default_token_generator.make_token(user)
            uid = urlsafe_base64_encode(force_bytes(user.pk))
            # Frontend URL
            reset_link = f"https://hrms.vibesandbox.live/reset-password?uid={uid}&token={token}"
            
            try:
                send_mail(
                    "Password Reset Request",
                    f"Please click the link below to reset your password:\n\n{reset_link}",
                    settings.DEFAULT_FROM_EMAIL,
                    [user.email],
                    fail_silently=True,
                )
            except Exception:
                pass
                
        # Always return success to prevent email enumeration
        return Response({"message": "If the email exists, a reset link has been sent."}, status=status.HTTP_200_OK)

class PasswordResetConfirmView(APIView):
    def post(self, request):
        uidb64 = request.data.get('uid')
        token = request.data.get('token')
        new_password = request.data.get('password')
        
        if not uidb64 or not token or not new_password:
            return Response({"error": "Missing parameters"}, status=status.HTTP_400_BAD_REQUEST)
            
        try:
            uid = force_str(urlsafe_base64_decode(uidb64))
            user = User.objects.get(pk=uid)
        except (TypeError, ValueError, OverflowError, User.DoesNotExist):
            user = None
            
        if user and default_token_generator.check_token(user, token):
            user.set_password(new_password)
            user.save()
            return Response({"message": "Password has been reset successfully."}, status=status.HTTP_200_OK)
            
        return Response({"error": "Invalid or expired token"}, status=status.HTTP_400_BAD_REQUEST)

class ChangePasswordView(APIView):
    permission_classes = [IsAuthenticated]

    def post(self, request):
        user = request.user
        current_password = request.data.get('current_password')
        new_password = request.data.get('new_password')

        if not current_password or not new_password:
            return Response({'error': 'Missing parameters'}, status=status.HTTP_400_BAD_REQUEST)

        if not user.check_password(current_password):
            return Response({'error': 'Incorrect current password'}, status=status.HTTP_400_BAD_REQUEST)
        
        user.set_password(new_password)
        user.save()
        return Response({'message': 'Password updated successfully'}, status=status.HTTP_200_OK)
