from django.contrib.auth.backends import ModelBackend
from django.contrib.auth.models import User
from django.db.models import Q


class PhoneOrEmailBackend(ModelBackend):
    """
    Custom authentication backend allowing users to authenticate via:
    1. Username (User.username or Employee.code)
    2. Email (User.email or Employee.email)
    3. Phone number (Employee.phone or User.username)
    
    Fully backward compatible with Django's ModelBackend and SimpleJWT.
    """
    def authenticate(self, request, username=None, password=None, **kwargs):
        if username is None:
            username = kwargs.get('email') or kwargs.get('phone') or kwargs.get('identifier')

        if not username or not password:
            return None

        clean_identifier = str(username).strip()
        clean_digits = ''.join(filter(str.isdigit, clean_identifier))

        user = None

        # 1. Try finding user directly by username or email
        user = User.objects.filter(
            Q(username__iexact=clean_identifier) | 
            Q(email__iexact=clean_identifier)
        ).first()

        # 2. If not found, search via Employee profile
        if not user:
            from employees.models import Employee
            
            # Build phone search query
            phone_q = Q(phone=clean_identifier)
            if clean_digits:
                phone_q |= Q(phone=clean_digits)
                if len(clean_digits) >= 10:
                    phone_q |= Q(phone__endswith=clean_digits[-10:])

            emp = Employee.objects.filter(
                Q(code__iexact=clean_identifier) |
                Q(email__iexact=clean_identifier) |
                phone_q
            ).select_related('user').first()

            if emp:
                if emp.user:
                    user = emp.user
                elif emp.email:
                    user = User.objects.filter(Q(email__iexact=emp.email) | Q(username__iexact=emp.email)).first()

        # 3. If still not found and clean_digits has >= 10 digits, check User.username
        if not user and clean_digits and len(clean_digits) >= 10:
            user = User.objects.filter(
                Q(username__endswith=clean_digits[-10:]) |
                Q(username=clean_digits)
            ).first()

        # 4. Verify password and active status
        if user:
            emp = getattr(user, 'employee_profile', None)
            if emp and emp.status != 'Active':
                return None

            if not user.is_active or not self.user_can_authenticate(user):
                return None

            if user.check_password(password):
                return user

        return None
