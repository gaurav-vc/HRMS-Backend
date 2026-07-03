import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

from leaves.models import LeaveType, LeaveRequest

def setup_leave_types():
    print("Setting up standardized Leave Types...")
    
    # Optional: Delete all existing requests if this is just a dev environment reset
    # (Commented out to prevent accidental data loss, but we update existing ones if needed)
    
    # 1. Create Annual Leave
    al, _ = LeaveType.objects.get_or_create(
        code='AL',
        defaults={
            'name': 'Annual Leave',
            'annual_entitlement': 15.0,
            'carry_forward_allowed': True,
            'max_carry_forward': 15.0,
            'active': True
        }
    )
    if not _:
        al.name = 'Annual Leave'
        al.save()
        
    # 2. Create LOP
    lop, _ = LeaveType.objects.get_or_create(
        code='LOP',
        defaults={
            'name': 'Loss of Pay',
            'annual_entitlement': 0.0,
            'carry_forward_allowed': False,
            'max_carry_forward': 0.0,
            'active': True
        }
    )
    if not _:
        lop.name = 'Loss of Pay'
        lop.save()
        
    # 3. Clean up legacy types
    legacy = LeaveType.objects.exclude(code__in=['AL', 'LOP'])
    count = legacy.count()
    if count > 0:
        print(f"Deleting {count} legacy leave types...")
        # Move all legacy requests to Annual Leave to prevent ProtectedError
        for leg in legacy:
            LeaveRequest.objects.filter(leave_type=leg).update(leave_type=al)
        legacy.delete()
        
    print("Leave types configured to strictly 'Annual Leave' and 'LOP'!")

if __name__ == '__main__':
    setup_leave_types()
