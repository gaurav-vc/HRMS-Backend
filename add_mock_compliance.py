import os
import django
import datetime

# Setup Django environment
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

from payroll.models import ComplianceReport

def create_mock_data():
    # 1. Create a 'Filed' report for the previous month
    ComplianceReport.objects.create(
        category='Provident Fund',
        key='PF-2026-09',
        desc='Monthly PF Return',
        period='September 2026',
        amount=45000.00,
        challan_number='CHLN-PF-83492',
        due=datetime.date(2026, 10, 15),
        filed_on=datetime.date(2026, 10, 12),
        status='Filed'
    )
    
    # 2. Create a 'Pending' report for the current month
    ComplianceReport.objects.create(
        category='Provident Fund',
        key='PF-2026-10',
        desc='Monthly PF Return',
        period='October 2026',
        amount=46250.00,
        due=datetime.date(2026, 11, 15),
        status='Pending'
    )
    
    print("Successfully created mock compliance reports! Refresh your browser to see the data.")

if __name__ == "__main__":
    create_mock_data()
