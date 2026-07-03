import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings")
django.setup()

from payroll.models import TaxRegimeSlab

def seed_old_regime():
    # 0 to 2,50,000 : 0%
    # 2,50,001 to 5,00,000 : 5%
    # 5,00,001 to 10,00,000 : 20%
    # Above 10,00,000 : 30%
    slabs = [
        {'min_income': 0, 'max_income': 250000, 'tax_rate': 0},
        {'min_income': 250000.01, 'max_income': 500000, 'tax_rate': 5},
        {'min_income': 500000.01, 'max_income': 1000000, 'tax_rate': 20},
        {'min_income': 1000000.01, 'max_income': None, 'tax_rate': 30},
    ]

    print("Seeding Old Tax Regime Slabs...")
    for slab in slabs:
        TaxRegimeSlab.objects.get_or_create(
            regime='Old',
            min_income=slab['min_income'],
            max_income=slab['max_income'],
            defaults={'tax_rate': slab['tax_rate']}
        )
    print("Done seeding Old Regime Slabs!")

if __name__ == "__main__":
    seed_old_regime()
