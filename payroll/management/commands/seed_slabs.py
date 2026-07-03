import os
import django

# Set up Django environment manually in case this is run as a standalone script
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'backend.settings')
django.setup()

from django.core.management.base import BaseCommand
from payroll.models import TaxRegimeSlab

class Command(BaseCommand):
    help = 'Seeds Income Tax Slabs for the New Regime'

    def handle(self, *args, **kwargs):
        # 1. Clear out existing New Regime slabs to prevent duplication
        TaxRegimeSlab.objects.filter(regime='New').delete()
        self.stdout.write("Cleared existing New Regime slabs.")

        # 2. Define slabs based on user specifications
        slabs_data = [
            # 0 to 4,00,000 : 0%
            {'min_income': 0, 'max_income': 400000, 'tax_rate': 0},
            
            # 4,00,001 to 8,00,000 : 5%
            {'min_income': 400000.01, 'max_income': 800000, 'tax_rate': 5},
            
            # 8,00,001 to 12,00,000 : 10%
            {'min_income': 800000.01, 'max_income': 1200000, 'tax_rate': 10},
            
            # 12,00,001 to 16,00,000 : 15%
            {'min_income': 1200000.01, 'max_income': 1600000, 'tax_rate': 15},
            
            # 16,00,001 to 20,00,000 : 20%
            {'min_income': 1600000.01, 'max_income': 2000000, 'tax_rate': 20},
            
            # 20,00,001 to 24,00,000 : 25%
            {'min_income': 2000000.01, 'max_income': 2400000, 'tax_rate': 25},
            
            # 24,00,001 to 1 Crore : 30%
            {'min_income': 2400000.01, 'max_income': 10000000, 'tax_rate': 30},
            
            # Above 1 Crore : 45% (Using None to represent infinity)
            {'min_income': 10000000.01, 'max_income': None, 'tax_rate': 45},
        ]

        # 3. Create records
        for s in slabs_data:
            TaxRegimeSlab.objects.create(
                regime='New',
                effective_from='2026-04-01',  # Financial Year 2026-2027 start
                min_income=s['min_income'],
                max_income=s['max_income'],
                tax_rate=s['tax_rate']
            )

        self.stdout.write(self.style.SUCCESS('Successfully seeded Income Tax slabs for New Regime (2026-27).'))
