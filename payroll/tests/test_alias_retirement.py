from django.test import TestCase
from decimal import Decimal
from payroll.models import SalaryStructure, ComponentRule
from payroll.engine import evaluate_component

class AliasRetirementValidationTest(TestCase):
    def setUp(self):
        self.struct = SalaryStructure.objects.create(name='Test Struct')
        self.basic_rule = ComponentRule.objects.create(
            structure=self.struct,
            name='Basic Pay',
            variable_code='BASIC_PAY',
            type='Earning',
            value=Decimal('50000.00'),
            effective_from='2026-01-01'
        )
        self.deduction_rule = ComponentRule.objects.create(
            structure=self.struct,
            name='Deduction',
            variable_code='PF_DEDUCTION',
            type='Deduction',
            effective_from='2026-01-01'
        )

    def test_a_legacy_formula_with_alias_active(self):
        """Test A: Stored Formula uses legacy alias 'basic'. Expected: Success."""
        self.deduction_rule.formula = 'basic * 0.12'
        self.deduction_rule.save()
        
        # Simulating alias active (as in pre-Phase 11)
        context = {
            'BASIC_PAY': Decimal('50000.00'),
            'basic': Decimal('50000.00')
        }
        val = evaluate_component(self.deduction_rule, context)
        self.assertEqual(val, Decimal('6000.00'))

    def test_b_migration_completed_no_aliases_in_formulas(self):
        """Test B: Formulas migrated, no legacy formulas remain. Expected: Alias Retirement Eligible = TRUE"""
        self.deduction_rule.formula = 'BASIC_PAY * 0.12'
        self.deduction_rule.save()
        
        rules = ComponentRule.objects.all()
        alias_remaining = any(r.formula and 'basic' in r.formula for r in rules)
        self.assertFalse(alias_remaining)

    def test_c_one_formula_contains_basic(self):
        """Test C: One formula still contains 'basic'. Expected: Alias Retirement Eligible = FALSE"""
        self.deduction_rule.formula = 'basic * 0.12'
        self.deduction_rule.save()
        
        rules = ComponentRule.objects.all()
        alias_remaining = any(r.formula and 'basic' in r.formula for r in rules)
        self.assertTrue(alias_remaining)

    def test_d_alias_removal_attempted_while_references_remain(self):
        """Test D: Alias removal attempted while references remain. Expected: Error during evaluation."""
        self.deduction_rule.formula = 'basic * 0.12'
        self.deduction_rule.save()
        
        # Simulating alias layer completely removed from context
        context = {
            'BASIC_PAY': Decimal('50000.00')
        }
        
        with self.assertRaises(RuntimeError) as ctx:
            evaluate_component(self.deduction_rule, context)
        self.assertIn("Error evaluating rule", str(ctx.exception))

    def test_e_zero_alias_references_alias_layer_removed(self):
        """Test E: Zero alias references, alias layer removed. Expected: Success."""
        self.deduction_rule.formula = 'BASIC_PAY * 0.12'
        self.deduction_rule.save()
        
        # Simulating alias layer completely removed from context
        context = {
            'BASIC_PAY': Decimal('50000.00')
        }
        
        val = evaluate_component(self.deduction_rule, context)
        self.assertEqual(val, Decimal('6000.00'))
