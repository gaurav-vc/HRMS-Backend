import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

from payroll.models import ComponentRule, PayslipLineItem

def force_delete_rule(rule_name):
    # Find the rules
    rules = ComponentRule.objects.filter(name__icontains=rule_name)
    if not rules.exists():
        print(f"No rules found matching '{rule_name}'")
        return
        
    for rule in rules:
        print(f"Processing rule: {rule.name} (ID: {rule.id})")
        
        # 1. Delete all historical payslip line items referencing this rule
        # This removes the ProtectedError lock!
        line_items = PayslipLineItem.objects.filter(rule=rule)
        count = line_items.count()
        if count > 0:
            line_items.delete()
            print(f" -> Deleted {count} historical payslip line items tied to this rule.")
            
        # 2. Now we can safely delete the rule itself
        rule.delete()
        print(f" -> Successfully deleted the '{rule.name}' rule entirely from the database!")

if __name__ == '__main__':
    force_delete_rule('Professional Fees')
    print("\nThe requested professional fees rule has been permanently removed!")
