import os
import django
from datetime import date

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

from payroll.models import SalaryStructure, ComponentRule

def create_structure():
    print("Creating new salary structure based on requirements...")
    struct, created = SalaryStructure.objects.get_or_create(
        name="Sanjay Sir Structure",
        defaults={
            "description": "Custom structure containing Basic (60%), HRA (30%), LTA (5%), Convenience (5%), and Deductions.",
            "status": "Active"
        }
    )
    
    if not created:
        print("Structure already exists, clearing old rules...")
        ComponentRule.objects.filter(structure=struct).delete()
    
    today = date.today()

    rules = [
        # EARNINGS
        {
            "name": "Basic",
            "type": "Earning",
            "formula": "monthly_ctc * 0.60",
            "prorate": True,
        },
        {
            "name": "HRA",
            "type": "Earning",
            "formula": "monthly_ctc * 0.30",
            "prorate": True,
        },
        {
            "name": "LTA",
            "type": "Earning",
            "formula": "monthly_ctc * 0.05",
            "prorate": True,
        },
        {
            "name": "Convenience",
            "type": "Earning",
            "formula": "monthly_ctc * 0.05",
            "prorate": True,
        },
        {
            "name": "Overtime",
            "type": "Earning",
            "formula": "0.0",
            "prorate": False,
        },
        
        # DEDUCTIONS
        {
            "name": "Professional Tax",
            "type": "Deduction",
            "formula": "200.0",
            "prorate": False,
            "is_statutory": True,
        },
        {
            "name": "Loan Deductions",
            "type": "Deduction",
            "formula": "0.0", # Managed by dynamic integration elsewhere
            "prorate": False,
        },
        {
            "name": "Income Tax",
            "type": "Deduction",
            "formula": "0.0", # Managed by tax engine
            "prorate": False,
            "is_statutory": True,
        },
        {
            "name": "Professional Fees",
            "type": "Deduction",
            "formula": "0.0",
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
        print(f"Added Rule: {r['name']} -> {r['formula']}")

    print("Success! Structure 'Sanjay Sir Structure' is ready.")

if __name__ == '__main__':
    create_structure()
