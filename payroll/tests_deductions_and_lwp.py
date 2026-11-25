import datetime
from decimal import Decimal
from django.test import TestCase
from django.contrib.auth.models import User
from django.utils import timezone

from employees.models import Employee
from payroll.models import (
    SalaryStructure,
    ComponentRule,
    PayrollRun,
    Payslip,
    PayslipLineItem,
    SalaryAdvance,
    SalaryAdvanceInstallment,
    Loan,
    LoanInstallment,
)
from payroll.service import PayrollService
from organisation.models import Entity, Department, Designation, Site


class DeductionsAndLWPTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="test_ded_user", password="123")
        self.entity = Entity.objects.create(name="Test Corp", code="TC01")
        self.site = Site.objects.create(name="HQ")
        self.dept = Department.objects.create(name="Engineering")
        self.desg = Designation.objects.create(title="Software Engineer")

        # Create Salary Structure with Basic (60%), HRA (30%), Balancing (10%), and PF (12% of Basic)
        self.structure = SalaryStructure.objects.create(name="Standard Tech Structure", status="Active")
        
        self.basic_rule = ComponentRule.objects.create(
            structure=self.structure,
            name="Basic Pay",
            variable_code="BASIC_PAY",
            type="Earning",
            calc="% of CTC",
            value=Decimal("60.00"),
            formula="monthly_ctc * 0.60",
            prorate=True,
            effective_from=datetime.date(2026, 1, 1),
        )
        self.hra_rule = ComponentRule.objects.create(
            structure=self.structure,
            name="House Rent Allowance",
            variable_code="HRA",
            type="Earning",
            calc="% of CTC",
            value=Decimal("30.00"),
            formula="monthly_ctc * 0.30",
            prorate=True,
            effective_from=datetime.date(2026, 1, 1),
        )
        self.balancing_rule = ComponentRule.objects.create(
            structure=self.structure,
            name="Special Allowance",
            variable_code="SPECIAL_ALLOWANCE",
            type="Earning",
            calc="Balancing",
            value=Decimal("0.00"),
            formula="0",
            prorate=True,
            effective_from=datetime.date(2026, 1, 1),
        )
        self.pf_rule = ComponentRule.objects.create(
            structure=self.structure,
            name="Provident Fund",
            variable_code="PF",
            type="Deduction",
            calc="% of Basic",
            value=Decimal("12.00"),
            formula="basic * 0.12",
            is_statutory=True,
            prorate=True,  # Even if marked prorate=True, our engine must prevent double-prorating since basic is already prorated
            effective_from=datetime.date(2026, 1, 1),
        )

        # Monthly CTC = Rs. 1,00,000 (Annual CTC = 12,00,000)
        # Full month: Basic = 60,000; HRA = 30,000; Special = 10,000; Gross = 1,00,000; PF = 7,200
        self.employee = Employee.objects.create(
            user=self.user,
            code="EMP_DED_01",
            first_name="Vikram",
            last_name="Reddy",
            status="Active",
            ctc=1200000,
            salary_structure=self.structure,
            entity=self.entity,
            site=self.site,
            department=self.dept,
            designation=self.desg,
            doj=datetime.date(2025, 1, 1),
            pf_applicable=True,
        )
        self.employee._cached_dag = list(self.structure.components.all())

    def test_lwp_proration_and_no_double_proration_on_pf(self):
        """Module 15: Verify 5 LWP days prorates earnings to 25/30 and PF is 12% of earned basic (no double-proration)."""
        mock_run = PayrollRun(id=101, period="2026-06", status="Processing", entity=self.entity)
        # Month of June has 30 days. Employee has 5 LWP days => 25 present/paid days.
        precomputed = {
            "period": "2026-06",
            "total_days": 30,
            "present_days": 25,
            "att_map": {},
            "leave_map": {},
            "lop_map": {self.employee.id: 5},
        }

        emp_override = {"present_days": 25, "total_days": 30, "lop_days": 5}
        gross, deductions, net, line_items = PayrollService.process_employee_in_memory(
            self.employee, mock_run, precomputed, emp_override=emp_override
        )

        line_map = {item["rule"].name: item["amount"] for item in line_items}
        
        # Expected:
        # Proration Ratio = 25 / 30 = 0.83333333
        # Full Basic = 60,000 => Prorated Basic = 60,000 * 25/30 = 50,000.00
        # Full HRA = 30,000   => Prorated HRA = 30,000 * 25/30 = 25,000.00
        # Full Special = 10,000 => Prorated Special = 10,000 * 25/30 = 8,333.33
        # Total Prorated Gross = 50,000 + 25,000 + 8,333.33 = 83,333.33
        self.assertEqual(line_map["Basic Pay"], Decimal("50000.00"))
        self.assertEqual(line_map["House Rent Allowance"], Decimal("25000.00"))
        self.assertEqual(line_map["Special Allowance"], Decimal("8333.33"))
        self.assertEqual(gross, Decimal("83333.33"))

        # PF Verification: 12% of actual earned Basic (Rs. 50,000) = Rs. 6,000.00!
        # MUST NOT be double-prorated to 6000 * 25/30 = 5000!
        self.assertEqual(line_map["Provident Fund"], Decimal("6000.00"))
        self.assertEqual(deductions, Decimal("6000.00"))
        self.assertEqual(net, Decimal("77333.33"))

    def test_advance_and_loan_deductions_are_separated(self):
        """Module 14: Verify Loan EMI and Salary Advance Recovery appear as separate line items."""
        # 1. Create a Loan
        loan = Loan.objects.create(
            employee=self.employee,
            type="Personal Loan",
            amount=Decimal("60000.00"),
            outstanding=Decimal("60000.00"),
            tenure=6,
            emi=Decimal("10000.00"),
            status="Active",
        )
        loan.generate_schedule("2026-06")

        # 2. Create a Salary Advance
        advance = SalaryAdvance.objects.create(
            employee=self.employee,
            amount=Decimal("15000.00"),
            outstanding=Decimal("15000.00"),
            tenure=3,
            start_period="2026-06",
            status="Disbursed",
        )
        advance.generate_schedule("2026-06")

        mock_run = PayrollRun(id=102, period="2026-06", status="Processing", entity=self.entity)
        precomputed = {"period": "2026-06", "total_days": 30, "present_days": 30}

        gross, deductions, net, line_items = PayrollService.process_employee_in_memory(
            self.employee, mock_run, precomputed
        )

        line_map = {item["rule"].name: item["amount"] for item in line_items}

        # Verify separation
        self.assertIn("Loan EMI: Personal Loan", line_map)
        self.assertIn("Salary Advance Recovery", line_map)
        self.assertEqual(line_map["Loan EMI: Personal Loan"], Decimal("10000.00"))
        self.assertEqual(line_map["Salary Advance Recovery"], Decimal("5000.00"))

        # Both deductions are accounted separately
        # Gross = 1,00,000; PF = 7,200; Loan = 10,000; Advance = 5,000 => Deductions = 22,200; Net = 77,800
        self.assertEqual(deductions, Decimal("22200.00"))
        self.assertEqual(net, Decimal("77800.00"))

    def test_deduction_capacity_capping_with_heavy_lwp(self):
        """Module 14 & 15: If employee has heavy LWP (e.g. 27 LWP days), loan/advance is capped at available net pay."""
        loan = Loan.objects.create(
            employee=self.employee,
            type="Personal Loan",
            amount=Decimal("60000.00"),
            outstanding=Decimal("60000.00"),
            tenure=6,
            emi=Decimal("10000.00"),
            status="Active",
        )
        loan.generate_schedule("2026-06")

        advance = SalaryAdvance.objects.create(
            employee=self.employee,
            amount=Decimal("15000.00"),
            outstanding=Decimal("15000.00"),
            tenure=3,
            start_period="2026-06",
            status="Disbursed",
        )
        advance.generate_schedule("2026-06")

        # Employee worked ONLY 3 days in June (27 LWP days)
        # Gross = 1,00,000 * 3/30 = Rs. 10,000.00
        # Basic = 6,000.00; PF = 6,000 * 0.12 = Rs. 720.00
        # Net capacity before Loan/Advance = 10,000 - 720 = Rs. 9,280.00
        # Loan EMI is Rs. 10,000, but only Rs. 9,280 is available!
        # Loan recovery should be capped at 9,280.00
        # Remaining capacity for Salary Advance = 0.00 (Advance recovery deferred/capped at 0)
        mock_run = PayrollRun(id=103, period="2026-06", status="Processing", entity=self.entity)
        precomputed = {
            "period": "2026-06",
            "total_days": 30,
            "present_days": 3,
            "lop_map": {self.employee.id: 27},
        }
        emp_override = {"present_days": 3, "total_days": 30, "lop_days": 27}

        gross, deductions, net, line_items = PayrollService.process_employee_in_memory(
            self.employee, mock_run, precomputed, emp_override=emp_override
        )

        line_map = {item["rule"].name: item["amount"] for item in line_items}

        self.assertEqual(gross, Decimal("10000.00"))
        self.assertEqual(line_map["Provident Fund"], Decimal("720.00"))
        self.assertEqual(line_map["Loan EMI: Personal Loan"], Decimal("9280.00"))
        # Advance could not be recovered due to zero capacity
        self.assertNotIn("Salary Advance Recovery", line_map)
        self.assertEqual(net, Decimal("0.00"))
        self.assertGreaterEqual(net, Decimal("0.00"))
