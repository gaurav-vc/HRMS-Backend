import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

from leaves.models import LeaveBalance, LeaveRequest

def restore_leaves():
    print("Starting leave restoration...")
    
    # 1. Delete all LeaveRequests since they consume leaves
    req_deleted, _ = LeaveRequest.objects.all().delete()
    print(f"Deleted {req_deleted} LeaveRequests.")

    # 2. Reset the used_days and remaining_days on all LeaveBalances
    balances = LeaveBalance.objects.all()
    count = 0
    for balance in balances:
        balance.used_days = 0
        balance.remaining_days = balance.allocated_days
        balance.save()
        count += 1
        
    print(f"Restored {count} LeaveBalance records (reset used_days to 0 and remaining_days to allocated_days).")
    print("Leave restoration completed successfully!")

if __name__ == "__main__":
    restore_leaves()
