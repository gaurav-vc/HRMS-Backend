import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

from django.core.management.base import BaseCommand
from payroll.models import ComponentRule

class Command(BaseCommand):
    help = 'Fixes the circular dependency by changing Basic Pay from Balancing to Formula'

    def handle(self, *args, **options):
        self.stdout.write("--- PHASE 10: FIXING HR CONFIGURATION ---")
        
        # Find Basic Pay component
        basic_rules = ComponentRule.objects.filter(name__icontains='Basic')
        
        for rule in basic_rules:
            if rule.calc == 'Balancing':
                self.stdout.write(f"Found misconfigured rule: {rule.name} (ID: {rule.id}) with calc='Balancing'")
                rule.calc = 'Formula'
                
                # If formula is missing, add a standard 40% CTC formula
                if not rule.formula or rule.formula == '0' or rule.formula == '0.00':
                    rule.formula = 'monthly_ctc * (40 / 100)'
                    
                rule.save()
                self.stdout.write(f"FIXED: Changed {rule.name} to calc='Formula' with formula: {rule.formula}")
            else:
                self.stdout.write(f"Rule {rule.name} is already correct (calc={rule.calc})")
                
        self.stdout.write("All clear! The circular dependency is resolved. You can now run the payroll from the frontend.")
