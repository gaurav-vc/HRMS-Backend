from django.contrib.auth.backends import ModelBackend
from django.contrib.auth.models import User
from django.db.models import Q


class PhoneOrEmailBackend(ModelBackend):
    """
    Custom authentication backend allowing users to authenticate via:
    1. Email (User.email or User.username)
    2. Phone number (Employee.phone or User.username)
    3. Employee Code / Username (User.username or Employee.code)
    
    Fully backward compatible with Django's ModelBackend and SimpleJWT.
    """
    def authenticate(self, request, username=None, password=None, **kwargs):
        if username is None:
            username = kwargs.get('email') or kwargs.get('phone')

        if not username or not password:
            return None

        clean_identifier = str(username).strip()

        # 1. Try finding user directly by username or email
        user = User.objects.filter(
            Q(username__iexact=clean_identifier) | 
            Q(email__iexact=clean_identifier)
        ).first()

        # 2. If not found, try finding via Employee.phone or Employee.code
        if not user:
            from employees.models import Employee
            
            # Clean phone (remove spaces, hyphens)
            clean_digits = ''.join(filter(str.isdigit, clean_identifier))
            
            emp = Employee.objects.filter(
                Q(code__iexact=clean_identifier) |
                Q(phone=clean_identifier) |
                (Q(phone__endswith=clean_digits[-10:]) if len(clean_digits) >= 10 else Q(pk__isnull=True))
            ).select_related('user').first()

            if emp and emp.user:
                user = emp.user

        # 3. Verify password and active status
        if user:
            emp = getattr(user, 'employee_profile', None)
            if emp and emp.status != 'Active':
                return None

            if not user.is_active or not self.user_can_authenticate(user):
                return None

            if user.check_password(password):
                return user

        return None
