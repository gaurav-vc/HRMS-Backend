import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

from payroll.models import ComponentRule

def update_overtime():
    c = ComponentRule.objects.filter(name='Overtime', structure__name='Client Structure').first()
    if c:
        # Overtime is straight 1.0x hourly rate (monthly_ctc / 30 days / 8 hours)
        c.calc = 'Formula'
        c.formula = 'overtime_hours * ((monthly_ctc / 30) / 8)'
        c.save()
        print("Updated Overtime formula successfully!")
    else:
        print("Could not find Overtime component in Sanjay Sir Structure.")

if __name__ == '__main__':
    update_overtime()
