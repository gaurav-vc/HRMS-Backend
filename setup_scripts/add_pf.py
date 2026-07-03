import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

from payroll.models import ComponentRule, SalaryStructure
from django.utils import timezone

def add_provident_fund():
    client_structure = SalaryStructure.objects.filter(name__icontains='Client Structure').first()
    if not client_structure:
        print("Error: Client Structure not found!")
        return

    rule, created = ComponentRule.objects.get_or_create(
        structure=client_structure,
        name='Provident Fund',
        defaults={
            'type': 'Deduction',
            'calc': '% of Basic',
            'value': 12,
            'formula': 'basic * (12.0 / 100.0)',
            'is_statutory': True,
            'effective_from': timezone.now().date(),
        }
    )
    
    if created:
        print("Successfully created Provident Fund (PF) rule in Client Structure!")
    else:
        # If it already exists, just forcefully update it to perfectly match the 12% requirement
        rule.type = 'Deduction'
        rule.calc = '% of Basic'
        rule.value = 12
        rule.formula = 'basic * (12.0 / 100.0)'
        rule.is_statutory = True
        rule.save()
        print("Successfully updated existing Provident Fund (PF) rule to exactly 12% of Basic Salary!")

if __name__ == '__main__':
    add_provident_fund()
