import os
import django
from datetime import date

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

from payroll.models import SalaryStructure, ComponentRule

def setup():
    today = date.today()

    print("1. Cleaning up Client Structure...")
    # Find existing Client Structure (assuming it's named 'Client Structure' or similar)
    # The previous script created "Sanjay Sir Structure". We will check for both.
    client_structures = SalaryStructure.objects.filter(name__icontains='Client')
    if not client_structures.exists():
        client_structures = SalaryStructure.objects.filter(name__icontains='Sanjay Sir Structure')
        
    for struct in client_structures:
        # Disable Professional Fees rule instead of deleting (to avoid ProtectedError from old payslips)
        rules_to_disable = ComponentRule.objects.filter(structure=struct, name__icontains='Professional Fees')
        if rules_to_disable.exists():
            for r in rules_to_disable:
                r.formula = "0.0"
                r.value = 0.0
                r.save()
            print(f" -> Disabled Professional Fees in '{struct.name}' (Set formula to 0.0)")
        else:
            print(f" -> No Professional Fees found in '{struct.name}'")

    print("\n2. Creating Service Structure...")
    struct, created = SalaryStructure.objects.get_or_create(
        name="Service Structure",
        defaults={
            "description": "Structure for Service Employees. Flat 10% deduction on monthly salary.",
            "status": "Active"
        }
    )
    
    if not created:
        print(" -> Service Structure already exists. Recreating rules...")
        ComponentRule.objects.filter(structure=struct).delete()
    else:
        print(" -> Created new Service Structure.")

    rules = [
        # EARNINGS
        {
            "name": "Service Pay",
            "type": "Earning",
            "formula": "monthly_ctc * 1.0",
            "prorate": True,
        },
        # DEDUCTIONS
        {
            "name": "Service Deduction",
            "type": "Deduction",
            "formula": "monthly_ctc * 0.10",
            "prorate": False,
        }
    ]

    for r in rules:
        ComponentRule.objects.create(
            structure=struct,
            name=r["name"],
            type=r["type"],
            calc="Formula",
            value=0.0,
            formula=r["formula"],
            prorate=r["prorate"],
            is_statutory=r.get("is_statutory", False),
            effective_from=today
        )
        print(f" -> Added Rule: {r['name']} ({r['formula']})")

    print("\nSetup complete!")

if __name__ == '__main__':
    setup()
