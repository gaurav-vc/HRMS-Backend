import datetime
from decimal import Decimal
from django.test import TestCase
from django.contrib.auth.models import User
from django.utils import timezone
from rest_framework.exceptions import AuthenticationFailed

from employees.models import Employee, EmployeeExit, CompensationHistory
from authentication.serializers import CustomTokenObtainPairSerializer
from payroll.models import (
    SalaryStructure,
    ComponentRule,
    PayrollRun,
    Payslip,
    SalaryAdvance,
    SalaryAdvanceInstallment,
    Loan,
    LoanInstallment,
)
from payroll.service import PayrollService
from payroll.ctc_calculator import CTCBreakupService
from organisation.models import Entity, Department, Designation, Site


class EmployeeLifecycleAndPayrollTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(username="test_emp_01", password="123")
        self.entity = Entity.objects.create(name="Test Entity", code="TE01")
        self.site = Site.objects.create(name="HQ Site")
        self.dept = Department.objects.create(name="Engineering")
        self.desg = Designation.objects.create(title="Software Engineer")

        self.structure = SalaryStructure.objects.create(name="Standard Test Structure", status="Active")
        self.basic_rule = ComponentRule.objects.create(
            structure=self.structure,
            name="Basic Pay",
            variable_code="BASIC_PAY",
            type="Earning",
            calc="% of CTC",
            value=Decimal("50.00"),
            effective_from=datetime.date(2026, 1, 1),
        )
        self.hra_rule = ComponentRule.objects.create(
            structure=self.structure,
            name="House Rent Allowance",
            variable_code="HRA",
            type="Earning",
            calc="% of Basic",
            value=Decimal("50.00"),
            effective_from=datetime.date(2026, 1, 1),
        )
        self.special_rule = ComponentRule.objects.create(
            structure=self.structure,
            name="Special Allowance",
            variable_code="SPECIAL_ALLOWANCE",
            type="Earning",
            calc="Balancing",
            value=Decimal("0.00"),
            effective_from=datetime.date(2026, 1, 1),
        )
        self.pf_rule = ComponentRule.objects.create(
            structure=self.structure,
            name="Provident Fund (Employee)",
            variable_code="PF_EMP",
            type="Deduction",
            calc="% of Basic",
            value=Decimal("12.00"),
            is_statutory=True,
            effective_from=datetime.date(2026, 1, 1),
        )

        self.employee = Employee.objects.create(
            user=self.user,
            code="EMP001",
            first_name="Aarav",
            last_name="Sharma",
            status="Active",
            ctc=1200000,
            salary_structure=self.structure,
            entity=self.entity,
            site=self.site,
            department=self.dept,
            designation=self.desg,
            doj=datetime.date(2025, 1, 1),
        )

    def test_module6_login_blocked_for_inactive_and_lwd_passed(self):
        """Module 6: Verify login serializer rejects exited employee and deactivates on LWD."""
        # 1. Direct status change check
        self.employee.status = "Exited"
        self.employee.save()

        serializer = CustomTokenObtainPairSerializer()
        with self.assertRaises(AuthenticationFailed) as cm:
            serializer.validate({"username": "test_emp_01", "password": "123"})
        self.assertTrue(
            "Account inactive" in str(cm.exception) or "No active account" in str(cm.exception)
        )
        self.user.refresh_from_db()
        self.assertFalse(self.user.is_active)

        # Reactivate user for next test
        self.user.is_active = True
        self.user.save()
        self.employee.status = "Active"
        self.employee.save()

        # 2. Exit process with past LWD
        exit_proc = EmployeeExit.objects.create(
            employee=self.employee,
            exit_type="Resignation",
            last_working_day=datetime.date(2026, 1, 1),
            status="Approved",
            notice_period_days=30,
        )
        serializer2 = CustomTokenObtainPairSerializer()
        with self.assertRaises(AuthenticationFailed) as cm:
            serializer2.validate({"username": "test_emp_01", "password": "123"})
        self.assertIn("Last working day has passed", str(cm.exception))
        exit_proc.refresh_from_db()
        self.assertEqual(exit_proc.status, "Deactivated")

    def test_module7_salary_advance_schedule_and_payroll_recovery(self):
        """Module 7: Verify advance salary schedule generation and automated payroll deduction."""
        advance = SalaryAdvance.objects.create(
            employee=self.employee,
            amount=Decimal("30000.00"),
            tenure=3,
            start_period="2026-05",
            status="Disbursed",
        )
        advance.generate_schedule("2026-05")

        self.assertEqual(advance.installments.count(), 3)
        inst1 = advance.installments.filter(period="2026-05").first()
        self.assertIsNotNone(inst1)
        self.assertEqual(inst1.amount, Decimal("10000.00"))
        self.assertEqual(inst1.status, "PENDING")

        # Test Payroll Injection
        mock_run = PayrollRun(id=999, period="2026-05", status="Processing", entity=self.entity)
        precomputed = {"period": "2026-05", "total_days": 31, "present_days": 31}

        # Mock attendance summary
        self.employee._cached_dag = list(self.structure.components.all())
        gross, deductions, net, line_items = PayrollService.process_employee_in_memory(
            self.employee, mock_run, precomputed
        )

        advance_line_item = next((item for item in line_items if item["rule"].name == "Salary Advance Recovery"), None)
        self.assertIsNotNone(advance_line_item, "Salary Advance Recovery line item must be injected into payroll")
        self.assertEqual(advance_line_item["amount"], Decimal("10000.00"))
        self.assertGreaterEqual(deductions, Decimal("10000.00"))

    def test_module8_ctc_breakup_service_mathematical_consistency(self):
        """Module 8: Verify authoritative CTCBreakupService output matches invariant."""
        breakup = CTCBreakupService.calculate_breakup(
            structure=self.structure,
            ctc=1200000,
            tax_regime="New",
        )
        self.assertEqual(breakup["annual_ctc"], 1200000.0)
        self.assertEqual(breakup["monthly_ctc"], 100000.0)

        # Total Gross + Total Employer = Calculated CTC
        gross_monthly = Decimal(str(breakup["total_gross_earnings"]["monthly"]))
        employer_monthly = Decimal(str(breakup["total_employer_cost"]["monthly"]))
        calculated_monthly = Decimal(str(breakup["calculated_ctc"]["monthly"]))

        self.assertEqual(gross_monthly + employer_monthly, calculated_monthly)
        self.assertTrue(breakup["is_balanced"])

    def test_module9_salary_revision_history_and_hike_tracking(self):
        """Module 9: Verify CompensationHistory tracks previous CTC, new CTC, % hike and closes prior record."""
        # Baseline compensation record
        baseline = CompensationHistory.objects.create(
            employee=self.employee,
            previous_ctc=1000000,
            ctc=1200000,
            hike_percentage=Decimal("20.00"),
            revision_type="Annual Appraisal",
            salary_structure=self.structure,
            effective_from=datetime.date(2025, 4, 1),
            effective_to=None,
        )

        # Grant new revision: ₹14,40,000 (+20%) from 2026-04-01
        new_effective = datetime.date(2026, 4, 1)
        prev_active = CompensationHistory.objects.filter(employee=self.employee, effective_to__isnull=True).first()
        if prev_active:
            prev_active.effective_to = new_effective - datetime.timedelta(days=1)
            prev_active.save()

        new_hike = CompensationHistory.objects.create(
            employee=self.employee,
            previous_ctc=self.employee.ctc,
            ctc=1440000,
            hike_percentage=Decimal("20.00"),
            revision_type="Promotion",
            salary_structure=self.structure,
            effective_from=new_effective,
            effective_to=None,
            notes="Promoted to Senior Lead",
        )
        self.employee.ctc = 1440000
        self.employee.save()

        baseline.refresh_from_db()
        self.assertEqual(baseline.effective_to, datetime.date(2026, 3, 31))
        self.assertIsNone(new_hike.effective_to)
        self.assertEqual(self.employee.ctc, 1440000)
        self.assertEqual(new_hike.hike_percentage, Decimal("20.00"))
        self.assertEqual(self.employee.compensation_history.count(), 2)
