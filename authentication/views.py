from rest_framework import status
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework_simplejwt.views import TokenObtainPairView
from rest_framework_simplejwt.tokens import RefreshToken
from django.utils import timezone
from .models import LoginAuditLog, PasswordResetOTP
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

from rest_framework.parsers import MultiPartParser, FormParser, JSONParser

class UserProfileView(APIView):
    permission_classes = [IsAuthenticated]
    parser_classes = (MultiPartParser, FormParser, JSONParser)
    
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

        serializer = UserProfileSerializer(request.user, context={'request': request})
        return Response(serializer.data)

    def patch(self, request):
        user = request.user
        name = request.data.get('name')
        
        if name:
            parts = name.split(' ', 1)
            first_name = parts[0]
            last_name = parts[1] if len(parts) > 1 else ''
            
            user.first_name = first_name
            user.last_name = last_name
            user.save(update_fields=['first_name', 'last_name'])
            
            if hasattr(user, 'employee_profile') and user.employee_profile:
                user.employee_profile.first_name = first_name
                user.employee_profile.last_name = last_name
                user.employee_profile.save(update_fields=['first_name', 'last_name'])
                
        # Handle photo upload
        photo = request.FILES.get('photo')
        if photo and hasattr(user, 'employee_profile') and user.employee_profile:
            user.employee_profile.photo = photo
            user.employee_profile.save(update_fields=['photo'])
                
        serializer = UserProfileSerializer(user, context={'request': request})
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
    permission_classes = [AllowAny]
    def post(self, request):
        email = request.data.get('email')
        if not email:
            return Response({"error": "Email is required"}, status=status.HTTP_400_BAD_REQUEST)
            
        user = User.objects.filter(email=email).first()
        if user:
            otp = PasswordResetOTP.generate_otp(user)
            
            try:
                send_mail(
                    "Password Reset OTP",
                    f"Your OTP for password reset is: {otp}\n\nThis OTP is valid for 10 minutes.",
                    settings.DEFAULT_FROM_EMAIL,
                    [user.email],
                    fail_silently=True,
                )
            except Exception:
                pass
                
        # Always return success to prevent email enumeration
        return Response({"message": "If the email exists, an OTP has been sent."}, status=status.HTTP_200_OK)

class PasswordResetVerifyOTPView(APIView):
    permission_classes = [AllowAny]
    def post(self, request):
        email = request.data.get('email')
        otp_code = request.data.get('otp')
        
        if not email or not otp_code:
            return Response({"error": "Email and OTP are required"}, status=status.HTTP_400_BAD_REQUEST)
            
        user = User.objects.filter(email=email).first()
        if not user:
            return Response({"error": "Invalid OTP"}, status=status.HTTP_400_BAD_REQUEST)
            
        otp_obj = PasswordResetOTP.objects.filter(user=user, otp=otp_code).order_by('-created_at').first()
        
        if not otp_obj or not otp_obj.is_valid():
            return Response({"error": "Invalid or expired OTP"}, status=status.HTTP_400_BAD_REQUEST)
            
        return Response({"message": "OTP verified successfully"}, status=status.HTTP_200_OK)

class PasswordResetConfirmView(APIView):
    permission_classes = [AllowAny]
    def post(self, request):
        email = request.data.get('email')
        otp_code = request.data.get('otp')
        new_password = request.data.get('password')
        
        if not email or not otp_code or not new_password:
            return Response({"error": "Missing parameters"}, status=status.HTTP_400_BAD_REQUEST)
            
        user = User.objects.filter(email=email).first()
        if not user:
            return Response({"error": "Invalid OTP"}, status=status.HTTP_400_BAD_REQUEST)
            
        otp_obj = PasswordResetOTP.objects.filter(user=user, otp=otp_code).order_by('-created_at').first()
        
        if not otp_obj or not otp_obj.is_valid():
            return Response({"error": "Invalid or expired OTP"}, status=status.HTTP_400_BAD_REQUEST)
            
        user.set_password(new_password)
        user.save()
        
        # Invalidate OTP after use
        otp_obj.delete()
        
        # Generate tokens to auto-login
        refresh = RefreshToken.for_user(user)
        
        return Response({
            "message": "Password has been reset successfully.",
            "access": str(refresh.access_token),
            "refresh": str(refresh),
        }, status=status.HTTP_200_OK)

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
