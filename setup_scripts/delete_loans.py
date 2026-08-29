import os
import sys
import django

# Set up Django environment
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

from payroll.models import Loan

def delete_all_loans():
    count, _ = Loan.objects.all().delete()
    print(f"Successfully deleted {count} loan(s).")

if __name__ == '__main__':
    delete_all_loans()
