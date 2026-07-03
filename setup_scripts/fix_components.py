import os
import django

os.environ.setdefault("DJANGO_SETTINGS_MODULE", "core.settings")
django.setup()

from payroll.models import ComponentRule

rules = {
    "Basic": {"calc": "% of CTC", "value": 40},
    "HRA": {"calc": "% of Basic", "value": 50},
    "Special Allowance": {"calc": "Balancing", "value": 0},
    "Conveyance": {"calc": "Fixed", "value": 1600},
    "Medical": {"calc": "Fixed", "value": 1250},
    "PF": {"calc": "% of Basic", "value": 12},
    "Professional Tax": {"calc": "Fixed", "value": 200},
    "Income Tax": {"calc": "% of CTC", "value": 8},
}

for rule in ComponentRule.objects.all():
    for name, data in rules.items():
        if name.lower() in rule.name.lower():
            rule.calc = data["calc"]
            rule.value = data["value"]
            if rule.formula and 'ctc' in rule.formula and 'monthly_ctc' not in rule.formula:
                rule.formula = rule.formula.replace('ctc', 'monthly_ctc')
            rule.save()
            print(f"Updated {rule.name} -> {rule.calc}: {rule.value} | Formula: {rule.formula}")
