from rest_framework import viewsets, status
from rest_framework.decorators import action
from rest_framework.views import APIView
from rest_framework.response import Response
from .models import (
    PayrollRun,
    Loan,
    LoanInstallment,
    SalaryAdvance,
    SalaryAdvanceInstallment,
    Reimbursement,
    ComponentRule,
    ComplianceReport,
    SalaryStructure,
    PayrollException,
    WalletPolicy,
    EmployeeWallet,
    WalletLedgerEntry,
    DisciplinaryInfractionCategory,
    EmployeeDisciplinaryMemo,
    EmiReliefRequest,
)
from .serializers import (
    PayrollRunSerializer,
    LoanSerializer,
    LoanInstallmentSerializer,
    SalaryAdvanceSerializer,
    SalaryAdvanceInstallmentSerializer,
    ReimbursementSerializer,
    ComponentRuleSerializer,
    ComplianceReportSerializer,
    SalaryStructureSerializer,
    WalletPolicySerializer,
    EmployeeWalletSerializer,
    WalletLedgerEntrySerializer,
    DisciplinaryInfractionCategorySerializer,
    EmployeeDisciplinaryMemoSerializer,
    EmiReliefRequestSerializer,
)
from employees.models import Employee
from django.utils import timezone

from authentication.permissions import DataIsolationMixin
from rest_framework.permissions import IsAuthenticated


class SalaryStructureViewSet(DataIsolationMixin, viewsets.ModelViewSet):
    rbac_module = "Salary Structure"
    permission_classes = [IsAuthenticated]
    queryset = SalaryStructure.objects.all()
    serializer_class = SalaryStructureSerializer

    @action(detail=True, methods=["get", "post"], url_path="calculate-breakup")
    def calculate_breakup(self, request, pk=None):
        from .ctc_calculator import CTCBreakupService

        structure = self.get_object()
        ctc_val = request.data.get("ctc") or request.query_params.get("ctc", 0)
        regime = request.data.get("tax_regime") or request.query_params.get(
            "tax_regime", "New"
        )
        tds_app = request.data.get("tds_applicable")
        if tds_app is None:
            tds_app = request.query_params.get("tds_applicable")
        if tds_app is not None:
            tds_app = str(tds_app).lower() in ["true", "1", "yes"]

        worker_t = request.data.get("worker_type") or request.query_params.get(
            "worker_type", "Salaried"
        )
        tds_rate = request.data.get("tds_rate") or request.query_params.get("tds_rate")
        tds_sec = request.data.get("tds_section") or request.query_params.get("tds_section")
        pan_val = request.data.get("pan") or request.query_params.get("pan")
        emp_id = request.data.get("employee_id") or request.query_params.get("employee_id")
        if not emp_id and hasattr(request.user, "employee_profile"):
            emp_id = request.user.employee_profile.id

        breakup = CTCBreakupService.calculate_breakup(
            structure=structure,
            ctc=ctc_val,
            tax_regime=regime,
            tds_applicable=tds_app,
            tds_rate=tds_rate,
            tds_section=tds_sec,
            worker_type=worker_t,
            pan=pan_val,
            employee_id=emp_id,
        )
        return Response(breakup)

    @action(detail=False, methods=["get", "post"], url_path="calculate-breakup")
    def calculate_breakup_general(self, request):
        from .ctc_calculator import CTCBreakupService

        structure_id = request.data.get("structure_id") or request.query_params.get(
            "structure_id"
        )
        ctc_val = request.data.get("ctc") or request.query_params.get("ctc", 0)
        regime = request.data.get("tax_regime") or request.query_params.get(
            "tax_regime", "New"
        )
        tds_app = request.data.get("tds_applicable")
        if tds_app is None:
            tds_app = request.query_params.get("tds_applicable")
        if tds_app is not None:
            tds_app = str(tds_app).lower() in ["true", "1", "yes"]

        worker_t = request.data.get("worker_type") or request.query_params.get(
            "worker_type", "Salaried"
        )
        tds_rate = request.data.get("tds_rate") or request.query_params.get("tds_rate")
        tds_sec = request.data.get("tds_section") or request.query_params.get("tds_section")
        pan_val = request.data.get("pan") or request.query_params.get("pan")
        emp_id = request.data.get("employee_id") or request.query_params.get("employee_id")
        if not emp_id and hasattr(request.user, "employee_profile"):
            emp_id = request.user.employee_profile.id

        breakup = CTCBreakupService.calculate_breakup(
            structure_id=structure_id,
            ctc=ctc_val,
            tax_regime=regime,
            tds_applicable=tds_app,
            tds_rate=tds_rate,
            tds_section=tds_sec,
            worker_type=worker_t,
            pan=pan_val,
            employee_id=emp_id,
        )
        return Response(breakup)


class ComponentRuleViewSet(DataIsolationMixin, viewsets.ModelViewSet):
    rbac_module = "Salary Structure"
    permission_classes = [IsAuthenticated]
    queryset = ComponentRule.objects.all()
    serializer_class = ComponentRuleSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        structure_id = self.request.query_params.get("structure", None)
        if structure_id is not None:
            qs = qs.filter(structure_id=structure_id)
        return qs

    def destroy(self, request, *args, **kwargs):
        import django.db.models.deletion

        try:
            return super().destroy(request, *args, **kwargs)
        except django.db.models.deletion.ProtectedError:
            return Response(
                {
                    "detail": "Cannot delete this rule because it is linked to past payslips. Please edit the rule and set its value to 0 instead."
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

    def _derive_formula(self, data):
        # Automatically derive formula if not provided or empty
        if "calc" in data and not data.get("formula"):
            calc = (
                data.get("calc")[0]
                if isinstance(data.get("calc"), list)
                else data.get("calc")
            )
            val = (
                data.get("value")[0]
                if isinstance(data.get("value"), list)
                else data.get("value", 0)
            )

            if calc == "Fixed":
                data["formula"] = str(val)
            elif calc == "% of Basic":
                data["formula"] = f"basic * ({val} / 100)"
            elif calc == "% of CTC":
                data["formula"] = f"monthly_ctc * ({val} / 100)"
            else:
                data["formula"] = str(val)
        return data

    def create(self, request, *args, **kwargs):
        data = request.data.copy()
        data = self._derive_formula(data)

        # Engine Phase 1: Set effective_from by default if not provided
        if "effective_from" not in data:
            from django.utils import timezone

            data["effective_from"] = timezone.now().date().isoformat()

        serializer = self.get_serializer(data=data)
        serializer.is_valid(raise_exception=True)
        self.perform_create(serializer)
        return Response(serializer.data, status=201)

    def update(self, request, *args, **kwargs):
        partial = kwargs.pop("partial", False)
        instance = self.get_object()
        data = request.data.copy()

        data = self._derive_formula(data)

        serializer = self.get_serializer(instance, data=data, partial=partial)
        serializer.is_valid(raise_exception=True)
        self.perform_update(serializer)
        return Response(serializer.data)


class ComplianceReportViewSet(DataIsolationMixin, viewsets.ModelViewSet):
    rbac_module = "Compliance"
    queryset = ComplianceReport.objects.all().order_by("due")
    serializer_class = ComplianceReportSerializer

    @action(detail=False, methods=["get"])
    def generate_return(self, request):
        category = request.query_params.get("category")
        if not category:
            return Response({"error": "Category is required"}, status=400)

        import csv
        from django.http import HttpResponse

        if (
            category.upper() in ["TDS", "26Q", "TDS_26Q"]
            or request.query_params.get("form") == "26Q"
        ):
            from payroll.models import Payslip

            period = request.query_params.get("period")
            slips = Payslip.objects.all().select_related("employee")
            if period:
                slips = slips.filter(period=period)

            response = HttpResponse(content_type="text/csv")
            response["Content-Disposition"] = (
                'attachment; filename="Form_26Q_Professional_TDS_Return.csv"'
            )
            writer = csv.writer(response)
            writer.writerow(
                [
                    "Deductee Code",
                    "PAN",
                    "Name",
                    "Section Code",
                    "Payment Nature",
                    "Period",
                    "Gross Payout",
                    "TDS Rate",
                    "TDS Deducted",
                    "Net Paid",
                    "Certificate 197",
                ]
            )
            for s in slips:
                w_type = getattr(s.employee, "worker_type", "Salaried")
                tds_val = float(s.tds)
                if w_type in ["Professional", "Contractor"] or tds_val > 0:
                    sec = getattr(s.employee, "tds_section", "194J_10")
                    sec_display = "194C" if "194C" in sec else "194J"
                    rate = float(getattr(s.employee, "tds_rate", 10.0))
                    pan_val = s.employee.pan or ""
                    is_pen = not pan_val or len(pan_val.strip()) < 10
                    effective_rate = 20.0 if is_pen else rate
                    writer.writerow(
                        [
                            s.employee.code,
                            pan_val or "PANNOTAVBL",
                            f"{s.employee.first_name} {s.employee.last_name}",
                            sec_display,
                            (
                                "Professional Fees"
                                if sec_display == "194J"
                                else "Contractor Retainer"
                            ),
                            s.period,
                            float(s.gross),
                            f"{effective_rate}%",
                            tds_val,
                            float(s.net),
                            getattr(s.employee, "tds_lower_deduction_cert", "")
                            or "N/A",
                        ]
                    )
            return response

        pending_reports = self.get_queryset().filter(
            category=category, status="Pending"
        )

        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = (
            f'attachment; filename="Compliance_Return_{category.replace(" ", "_")}.csv"'
        )

        writer = csv.writer(response)
        writer.writerow(
            ["Category", "Key", "Description", "Period", "Amount", "Due Date"]
        )

        for report in pending_reports:
            writer.writerow(
                [
                    report.category,
                    report.key,
                    report.desc,
                    report.period,
                    report.amount,
                    report.due.strftime("%Y-%m-%d") if report.due else "",
                ]
            )

        return response


from rest_framework.decorators import action
from .service import PayrollService, PayrollPrerequisiteError
from authentication.permissions import DataIsolationMixin


def resolve_employee_salary_structure(emp, default_struct=None):
    if emp.salary_structure and emp.salary_structure.components.exists():
        return emp.salary_structure
    from payroll.models import SalaryStructure

    if getattr(emp, "site", None):
        site_struct = SalaryStructure.objects.filter(
            site=emp.site, status="Active"
        ).first()
        if site_struct and site_struct.components.exists():
            return site_struct
    emp_entity = getattr(emp, "entity", None)
    if (
        not emp_entity
        and getattr(emp, "site", None)
        and getattr(emp.site, "branch", None)
    ):
        emp_entity = getattr(emp.site.branch, "entity", None)
    if emp_entity:
        entity_struct = SalaryStructure.objects.filter(
            site__branch__entity=emp_entity, status="Active"
        ).first()
        if entity_struct and entity_struct.components.exists():
            return entity_struct
    if default_struct and default_struct.components.exists():
        return default_struct
    return SalaryStructure.objects.filter(status="Active").first()


class PayrollRunViewSet(DataIsolationMixin, viewsets.ModelViewSet):
    rbac_module = "Run Payroll"
    queryset = PayrollRun.objects.all().order_by("-period")
    serializer_class = PayrollRunSerializer

    def create(self, request, *args, **kwargs):
        period = request.data.get("period")
        entity_id = request.data.get("entity")
        run_type = request.data.get("run_type", "Live")

        # Prevent multiple runs for the same period and entity
        if period and entity_id:
            existing_run = PayrollRun.objects.filter(
                period=period, entity_id=entity_id, run_type=run_type
            ).first()
            if existing_run:
                serializer = self.get_serializer(existing_run)
                return Response(serializer.data, status=200)

        return super().create(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        run = self.get_object()
        user = request.user

        from authentication.permissions import (
            check_user_permission,
            user_can_approve,
            check_module_permission,
        )

        can_run = check_user_permission(user, "can_run_payroll")
        can_approve = user_can_approve(user, module="Run Payroll")
        has_del = check_module_permission(user, "Run Payroll", action="delete")

        if not (user.is_superuser or can_run or can_approve or has_del):
            return Response(
                {
                    "error": "Permission denied. You do not have permission to delete this payroll run."
                },
                status=403,
            )

        if run.status == "Disbursed":
            return Response(
                {"error": "Cannot delete an already disbursed payroll run."}, status=400
            )

        from django.db import transaction

        with transaction.atomic():
            # 1. Revert disciplinary memos attached to this run
            from .models import (
                EmployeeDisciplinaryMemo,
                WalletLedgerEntry,
                Payslip,
                SimulatedPayslip,
            )

            EmployeeDisciplinaryMemo.objects.filter(payroll_run=run).update(
                status="PENDING",
                is_active=True,
                payroll_run=None,
                payslip=None,
                deducted_at=None,
            )
            # 2. Reset Loan Installments linked to this run
            from .models import LoanInstallment
            from decimal import Decimal

            debited_insts = LoanInstallment.objects.filter(
                debited_in_run=run
            ).select_related("loan")
            for inst in debited_insts:
                loan = inst.loan
                loan.outstanding += inst.paid_amount
                if loan.status == "Closed":
                    loan.status = "Active"
                loan.save(update_fields=["outstanding", "status", "updated_at"])
                inst.status = "PENDING"
                inst.paid_amount = Decimal("0.00")
                inst.debited_in_run = None
                inst.debited_in_payslip = None
                inst.debited_at = None
                inst.save(
                    update_fields=[
                        "status",
                        "paid_amount",
                        "debited_in_run",
                        "debited_in_payslip",
                        "debited_at",
                    ]
                )

            # Revert Salary Advance installments
            from .models import SalaryAdvanceInstallment

            debited_adv_insts = SalaryAdvanceInstallment.objects.filter(
                debited_in_run=run
            ).select_related("advance")
            for inst in debited_adv_insts:
                adv = inst.advance
                adv.outstanding += inst.recovered_amount
                if adv.status == "Recovered":
                    adv.status = "Disbursed"
                adv.save(update_fields=["outstanding", "status", "updated_at"])
                inst.status = "PENDING"
                inst.recovered_amount = Decimal("0.00")
                inst.debited_in_run = None
                inst.debited_in_payslip = None
                inst.debited_at = None
                inst.save(
                    update_fields=[
                        "status",
                        "recovered_amount",
                        "debited_in_run",
                        "debited_in_payslip",
                        "debited_at",
                    ]
                )

            # 3. Delete wallet transactions linked to this run
            WalletLedgerEntry.objects.filter(payroll_run=run).delete()
            # 4. Delete payslips and simulated payslips
            Payslip.objects.filter(run=run).delete()
            SimulatedPayslip.objects.filter(run=run).delete()
            # 5. Clean up any related notifications pointing to this run
            from employees.models import Notification

            Notification.objects.filter(related_run_id=run.id).delete()
            # 6. Delete the run
            run.delete()

        return Response(
            {"status": "success", "message": "Payroll run deleted successfully"},
            status=status.HTTP_200_OK,
        )

    @action(detail=True, methods=["post"])
    def execute(self, request, pk=None):
        user = request.user
        emp = getattr(user, "employee_profile", None)
        if not emp and user.email:
            from employees.models import Employee

            emp = Employee.objects.filter(email__iexact=user.email).first()

        can_run = False
        from authentication.permissions import coerce_permission_bool

        if user.is_superuser:
            can_run = True
        elif emp and emp.dynamic_role and emp.dynamic_role.permissions:
            perms = emp.dynamic_role.permissions
            if (
                coerce_permission_bool(perms.get("can_run_payroll"))
                or coerce_permission_bool(perms.get("can_process_payroll"))
                or coerce_permission_bool(perms.get("can_approve_payroll"))
                or coerce_permission_bool(perms.get("can_manage_payroll"))
            ):
                can_run = True
        elif emp and getattr(emp, "is_admin", False):
            can_run = True

        if not can_run:
            return Response(
                {
                    "error": "Permission denied. You do not have permission to run payroll."
                },
                status=403,
            )

        from django.db import transaction
        from payroll.models import PayrollRun, SalaryStructure
        from .service import PayrollService
        import logging

        logger = logging.getLogger("hrms.payroll")

        try:
            import time

            max_retries = 3
            for attempt in range(max_retries):
                try:
                    with transaction.atomic():
                        run = PayrollRun.objects.filter(pk=pk).first()
                        if not run:
                            return Response(
                                {"status": "error", "detail": "Payroll run not found."},
                                status=404,
                            )

                        if run.status == "Processing":
                            return Response(
                                {
                                    "status": "error",
                                    "detail": "Payroll run is currently being processed by another task. Please wait.",
                                },
                                status=400,
                            )

                        overrides = request.data.get("overrides")
                        include_variable_bonus = request.data.get(
                            "include_variable_bonus", False
                        )
                        include_leaves_encashment = request.data.get(
                            "include_leaves_encashment", False
                        )

                        remarks = str(
                            request.data.get("remarks")
                            or request.data.get("comment")
                            or ""
                        ).strip()
                        if not remarks or len(remarks) < 3:
                            return Response(
                                {
                                    "status": "error",
                                    "error": "Mandatory remarks missing: Payroll execution remarks are required (minimum 3 characters).",
                                    "detail": "Payroll remarks are mandatory before executing payroll. Please provide execution remarks.",
                                },
                                status=400,
                            )

                        from attendance.models import AttendancePeriodVerification

                        is_att_verified = AttendancePeriodVerification.objects.filter(
                            entity=run.entity, period=run.period, status="Verified"
                        ).exists()
                        if not is_att_verified:
                            return Response(
                                {
                                    "status": "error",
                                    "error": f"Cannot execute payroll: Attendance for {run.entity.name} in period {run.period} has not been verified. Attendance sign-off is required before payroll execution.",
                                    "detail": f"Cannot execute payroll: Attendance for {run.entity.name} in period {run.period} has not been verified. Attendance sign-off is required before payroll execution.",
                                },
                                status=400,
                            )

                        if run.status in ["Frozen", "Disbursed"]:
                            if overrides:
                                PayrollService.file_arrears(run.id, overrides)
                            return Response(
                                {
                                    "status": "success",
                                    "run_status": run.status,
                                    "msg": "Arrears processed",
                                }
                            )

                        # Mark as Processing inside the atomic lock to prevent duplicate race conditions
                        run.status = "Processing"
                        run.remarks = remarks
                        if hasattr(request, "user") and request.user.is_authenticated:
                            run.maker = request.user
                        run.save(
                            update_fields=(
                                ["status", "maker", "remarks"]
                                if run.maker
                                else ["status", "remarks"]
                            )
                        )
                    break
                except Exception as lock_err:
                    if (
                        "database is locked" in str(lock_err).lower()
                        and attempt < max_retries - 1
                    ):
                        time.sleep(0.5 * (attempt + 1))
                        continue
                    raise lock_err

            # Dynamic resolution of active salary structure for any unassigned employees
            from employees.models import Employee
            from django.db.models import Q

            active_employees = (
                Employee.objects.filter(
                    Q(entity=run.entity)
                    | Q(branch__entity=run.entity)
                    | Q(site__branch__entity=run.entity),
                    status="Active",
                )
                .select_related(
                    "salary_structure", "department", "designation", "site", "entity"
                )
                .prefetch_related("salary_structure__components")
            )

            default_structure = SalaryStructure.objects.filter(status="Active").first()
            for e in active_employees:
                if not e.salary_structure or e.salary_structure.components.count() == 0:
                    struct = resolve_employee_salary_structure(e, default_structure)
                    if struct:
                        e.salary_structure = struct
                        e.save(update_fields=["salary_structure"])

            run = PayrollService.execute_run(
                run.id,
                overrides=overrides,
                include_variable_bonus=include_variable_bonus,
                include_leaves_encashment=include_leaves_encashment,
            )

            try:
                from payroll.models import PayrollRunComment

                PayrollRunComment.objects.create(
                    run=run,
                    author=(
                        request.user
                        if hasattr(request, "user") and request.user.is_authenticated
                        else None
                    ),
                    comment=f"Execution Remarks: {remarks}",
                )
            except Exception:
                pass

            return Response(
                {
                    "status": "success",
                    "run_status": run.status,
                    "msg": "Engine started in background",
                }
            )
        except PayrollPrerequisiteError as pe:
            logger.warning(f"Payroll prerequisite check failed for run {pk}: {str(pe)}")
            try:
                PayrollRun.objects.filter(pk=pk, status="Processing").update(
                    status="Draft"
                )
            except Exception:
                pass
            return Response(
                {
                    "status": "error",
                    "detail": f"Payroll calculation failed: {str(pe)}",
                    "missing_employees": pe.missing_employees,
                },
                status=400,
            )
        except Exception as e:
            logger.exception(f"Payroll execution failed for run {pk}: {str(e)}")
            try:
                PayrollRun.objects.filter(pk=pk, status="Processing").update(
                    status="Draft"
                )
            except Exception:
                pass
            return Response(
                {"status": "error", "detail": f"Payroll calculation failed: {str(e)}"},
                status=400,
            )

    @action(detail=True, methods=["get"])
    def details(self, request, pk=None):
        user = request.user
        from authentication.permissions import is_ceo_user

        can_view_confidential = is_ceo_user(user)

        run = self.get_object()
        slips = (
            run.payslip_set.all()
            .select_related(
                "employee",
                "employee__department",
                "employee__designation",
                "employee__site",
                "employee__entity",
                "employee__salary_structure",
            )
            .prefetch_related("lines", "lines__rule")
        )

        employee_details = []
        for slip in slips:
            emp = slip.employee
            components = {
                line.rule.name.strip(): float(line.amount) for line in slip.lines.all()
            }

            pf_amount = sum(
                float(l.amount)
                for l in slip.lines.all()
                if l.rule and "PF" in str(l.rule.name).upper()
            )
            pt_amount = sum(
                float(l.amount)
                for l in slip.lines.all()
                if l.rule
                and (
                    "PT" in str(l.rule.name).upper()
                    or "PROFESSIONAL TAX" in str(l.rule.name).upper()
                )
            )
            reimbursement = sum(
                float(l.amount)
                for l in slip.lines.all()
                if l.rule and "REIMBURSEMENT" in str(l.rule.name).upper()
            )
            incentive = sum(
                float(l.amount)
                for l in slip.lines.all()
                if l.rule
                and (
                    "INCENTIVE" in str(l.rule.name).upper()
                    or "BONUS" in str(l.rule.name).upper()
                )
            )
            arrears = sum(
                float(l.amount)
                for l in slip.lines.all()
                if l.rule and "ARREAR" in str(l.rule.name).upper()
            )
            ot_pay = sum(
                float(l.amount)
                for l in slip.lines.all()
                if l.rule
                and (
                    "OVERTIME" in str(l.rule.name).upper()
                    or "OT" in str(l.rule.name).upper()
                )
            )

            safe_name = f"{emp.first_name} {emp.last_name}".strip()
            safe_dept = emp.department.name if emp.department else "N/A"
            safe_site = emp.site.name if emp.site else ""
            safe_entity = emp.entity.name if emp.entity else run.entity.name

            employee_details.append(
                {
                    "id": emp.id,
                    "name": safe_name,
                    "code": emp.code or f"EMP{emp.id}",
                    "email": emp.email,
                    "number": emp.phone or "",
                    "workFrom": safe_site,
                    "entity": safe_entity,
                    "_entity": safe_entity,
                    "department": safe_dept,
                    "bankName": emp.bank_name or "",
                    "acNo": emp.bank_account or "",
                    "ifscCode": emp.ifsc or "",
                    "currentSalary": (
                        float(emp.ctc or 0) if can_view_confidential else 0
                    ),
                    "totalDays": float(slip.total_days or 30),
                    "presentDays": float(slip.days_present or 0),
                    "leaves": float(slip.annual_leaves or 0),
                    "lopDays": float(slip.lop_days or 0),
                    "halfDays": float(slip.half_days or 0),
                    "latePenalties": float(slip.late_penalty_days or 0),
                    "ot": float(slip.ot_hours or 0),
                    "overtimeHours": float(slip.ot_hours or 0),
                    "overtimePay": ot_pay if can_view_confidential else 0,
                    "daysPaid": float(slip.days_paid or 0),
                    "totalAmount": float(slip.gross) if can_view_confidential else 0,
                    "arrears": arrears if can_view_confidential else 0,
                    "deduction": float(slip.deductions) if can_view_confidential else 0,
                    "pf": pf_amount if can_view_confidential else 0,
                    "pt": pt_amount if can_view_confidential else 0,
                    "reimbursement": reimbursement if can_view_confidential else 0,
                    "incentive": incentive if can_view_confidential else 0,
                    "payableSalary": float(slip.net) if can_view_confidential else 0,
                    "isConfidential": not can_view_confidential,
                    "components": components if can_view_confidential else {},
                }
            )

        total_gross = sum(float(s.gross) for s in slips)
        total_ded = sum(float(s.deductions) for s in slips)
        total_net = sum(float(s.net) for s in slips)

        return Response(
            {
                "id": run.id,
                "period": run.period,
                "entity": run.entity.name,
                "entity_id": run.entity.id,
                "status": run.status,
                "employees": len(slips),
                "gross": total_gross if can_view_confidential else 0,
                "deductions": total_ded if can_view_confidential else 0,
                "net": total_net if can_view_confidential else 0,
                "employee_details": employee_details,
                "employeeDetails": employee_details,
            }
        )

    @action(detail=False, methods=["post", "get"])
    def validate_prerequisites(self, request):
        """Pre-flight validation check before initiating payroll run"""
        from employees.models import Employee
        from organisation.models import Entity
        from django.db.models import Q

        entity_ids = (
            request.data.get("entity_ids")
            or request.query_params.get("entity_ids")
            or request.data.get("entities")
            or request.query_params.get("entities")
        )
        if not entity_ids:
            entity_id = request.data.get("entity") or request.query_params.get("entity")
            if entity_id:
                entity_ids = [entity_id]

        if entity_ids:
            if isinstance(entity_ids, str):
                entity_ids = [
                    int(x.strip()) for x in entity_ids.split(",") if x.strip().isdigit()
                ]
            entities = Entity.objects.filter(id__in=entity_ids)
        else:
            entities = Entity.objects.all()

        from payroll.models import SalaryStructure

        default_structure = SalaryStructure.objects.filter(status="Active").first()
        missing_employees = []
        for entity in entities:
            emps = (
                Employee.objects.filter(
                    Q(entity=entity)
                    | Q(branch__entity=entity)
                    | Q(site__branch__entity=entity),
                    status="Active",
                )
                .select_related(
                    "salary_structure", "department", "designation", "site", "entity"
                )
                .prefetch_related("salary_structure__components")
            )

            for emp_record in emps:
                missing_fields = []
                struct = resolve_employee_salary_structure(
                    emp_record, default_structure
                )
                if not struct or struct.components.count() == 0:
                    missing_fields.append("Salary Structure")
                if not emp_record.ctc or emp_record.ctc <= 0:
                    missing_fields.append("CTC")

                if missing_fields:
                    missing_employees.append(
                        {
                            "id": emp_record.id,
                            "code": emp_record.code or f"EMP{emp_record.id}",
                            "name": f"{emp_record.first_name} {emp_record.last_name}".strip()
                            or "Unnamed",
                            "department": (
                                emp_record.department.name
                                if emp_record.department
                                else "N/A"
                            ),
                            "designation": (
                                emp_record.designation.title
                                if emp_record.designation
                                else "N/A"
                            ),
                            "entity": entity.name,
                            "entity_id": entity.id,
                            "missing": missing_fields,
                            "missing_salary_structure": "Salary Structure"
                            in missing_fields,
                            "missing_ctc": "CTC" in missing_fields,
                        }
                    )

        period = request.data.get("period") or request.query_params.get("period")
        attendance_unverified_entities = []
        pending_regularizations = []

        if period:
            from attendance.models import (
                AttendancePeriodVerification,
                RegularizationRequest,
            )
            from datetime import datetime
            import calendar

            try:
                year, month = map(int, period.split("-"))
                num_days = calendar.monthrange(year, month)[1]
                start_date = datetime(year, month, 1).date()
                end_date = datetime(year, month, num_days).date()
            except Exception:
                start_date = None
                end_date = None

            for entity in entities:
                verif = AttendancePeriodVerification.objects.filter(
                    entity=entity, period=period, status="Verified"
                ).first()
                if not verif:
                    attendance_unverified_entities.append(
                        {
                            "entity_id": entity.id,
                            "entity_name": entity.name,
                            "period": period,
                            "message": f"Attendance for {entity.name} ({period}) has not been verified/signed off. Attendance verification is mandatory before payroll execution.",
                        }
                    )
                if start_date and end_date:
                    pending_cnt = RegularizationRequest.objects.filter(
                        employee__entity=entity,
                        attendance_date__range=[start_date, end_date],
                        status="Pending",
                    ).count()
                    if pending_cnt > 0:
                        pending_regularizations.append(
                            {
                                "entity_id": entity.id,
                                "entity_name": entity.name,
                                "pending_count": pending_cnt,
                                "message": f"{pending_cnt} attendance regularization request(s) are pending review in {entity.name}.",
                            }
                        )

        can_run = (len(missing_employees) == 0) and (
            len(attendance_unverified_entities) == 0
        )

        return Response(
            {
                "status": "success",
                "can_run": can_run,
                "missing_employees": missing_employees,
                "attendance_unverified_entities": attendance_unverified_entities,
                "pending_regularizations": pending_regularizations,
            }
        )

    @action(detail=True, methods=["post"])
    def approve(self, request, pk=None):
        user = request.user
        from authentication.permissions import user_can_approve

        if not user_can_approve(user, module="Run Payroll"):
            return Response(
                {
                    "error": "Permission denied. You do not have permission to approve payroll."
                },
                status=403,
            )

        comment_text = str(
            request.data.get("comment") or request.data.get("remarks") or ""
        ).strip()
        if not comment_text or len(comment_text) < 3:
            return Response(
                {"error": "Approval remarks are mandatory before approving payroll."},
                status=400,
            )

        from django.db import transaction

        with transaction.atomic():
            run = PayrollRun.objects.select_for_update().filter(pk=pk).first()
            if not run:
                return Response({"error": "Payroll run not found"}, status=404)
            if run.status != "Maker-Submitted":
                return Response(
                    {"error": "Can only approve Maker-Submitted runs"}, status=400
                )

            run.status = "Disbursed"
            run.checker = request.user
            run.approval_remarks = comment_text
            run.save(update_fields=["status", "checker", "approval_remarks"])

            # Mark approved reimbursements as Paid for employees who got a payslip in this run
            from .models import Reimbursement

            paid_employees = list(run.payslip_set.values_list("employee_id", flat=True))
            Reimbursement.objects.filter(
                employee_id__in=paid_employees, status="Approved"
            ).update(status="Paid")

            # Credit Employee Wallets & Post Ledger Entries for Security Deposits
            from decimal import Decimal
            import decimal
            from .models import PayslipLineItem, EmployeeWallet, WalletLedgerEntry

            wallet_lines = PayslipLineItem.objects.filter(
                payslip__run=run, rule__name="Security Deposit (Wallet)"
            ).select_related("payslip__employee")

            for item in wallet_lines:
                emp = item.payslip.employee
                amt = Decimal(str(item.amount or "0.00")).quantize(
                    Decimal("0.01"), rounding=decimal.ROUND_HALF_UP
                )
                if amt > Decimal("0.00"):
                    (
                        wallet,
                        _,
                    ) = EmployeeWallet.objects.select_for_update().get_or_create(
                        employee=emp
                    )
                    if not WalletLedgerEntry.objects.filter(
                        wallet=wallet, payroll_run=run
                    ).exists():
                        new_bal = (wallet.current_balance + amt).quantize(
                            Decimal("0.01"), rounding=decimal.ROUND_HALF_UP
                        )
                        wallet.current_balance = new_bal
                        wallet.save(update_fields=["current_balance", "updated_at"])
                        WalletLedgerEntry.objects.create(
                            wallet=wallet,
                            payroll_run=run,
                            period=run.period,
                            transaction_type="SALARY_DEDUCTION",
                            amount=amt,
                            balance_after=new_bal,
                            notes=f"Security deposit deduction from payroll {run.period}",
                        )

            # Inactivate and link Disciplinary Memos deducted in this payroll run
            from .models import EmployeeDisciplinaryMemo

            paid_slips = run.payslip_set.all().select_related("employee")
            slip_by_emp = {s.employee_id: s for s in paid_slips}
            pending_memos = EmployeeDisciplinaryMemo.objects.filter(
                employee_id__in=paid_employees, status="PENDING", is_active=True
            )
            for memo in pending_memos:
                matching_slip = slip_by_emp.get(memo.employee_id)
                if matching_slip:
                    memo.status = "DEDUCTED"
                    memo.is_active = False
                    memo.payroll_run = run
                    memo.payslip = matching_slip
                    memo.deducted_at = timezone.now()
                    memo.save(
                        update_fields=[
                            "status",
                            "is_active",
                            "payroll_run",
                            "payslip",
                            "deducted_at",
                            "updated_at",
                        ]
                    )

            # Debit and link Loan Installments deducted in this payroll run
            from .models import LoanInstallment, Loan
            from decimal import Decimal

            pending_installments = LoanInstallment.objects.filter(
                loan__employee_id__in=paid_employees,
                period=run.period,
                status="PENDING",
                loan__status="Active",
            ).select_related("loan")

            for inst in pending_installments:
                matching_slip = slip_by_emp.get(inst.loan.employee_id)
                if matching_slip:
                    loan_line = matching_slip.lines.filter(
                        rule__name__icontains=f"Loan EMI: {inst.loan.type}"
                    ).first()
                    actual_paid = loan_line.amount if loan_line else Decimal("0.00")
                    if actual_paid > Decimal("0.00"):
                        inst.status = (
                            "DEBITED" if actual_paid >= inst.emi_amount else "PARTIAL"
                        )
                        inst.paid_amount = actual_paid
                        inst.debited_in_run = run
                        inst.debited_in_payslip = matching_slip
                        inst.debited_at = timezone.now()
                        inst.save(
                            update_fields=[
                                "status",
                                "paid_amount",
                                "debited_in_run",
                                "debited_in_payslip",
                                "debited_at",
                            ]
                        )

                        loan = inst.loan
                        loan.outstanding = max(
                            Decimal("0.00"), loan.outstanding - inst.paid_amount
                        )
                        if loan.outstanding <= Decimal("0.00"):
                            loan.status = "Closed"
                        loan.save(update_fields=["outstanding", "status", "updated_at"])

            from .models import SalaryAdvanceInstallment

            pending_adv_insts = SalaryAdvanceInstallment.objects.filter(
                advance__employee_id__in=paid_employees,
                period=run.period,
                status="PENDING",
                advance__status="Disbursed",
            ).select_related("advance")

            for inst in pending_adv_insts:
                matching_slip = slip_by_emp.get(inst.advance.employee_id)
                if matching_slip:
                    adv_line = matching_slip.lines.filter(
                        rule__name__icontains="Salary Advance Recovery"
                    ).first()
                    actual_rec = adv_line.amount if adv_line else Decimal("0.00")
                    if actual_rec > Decimal("0.00"):
                        inst.status = (
                            "RECOVERED" if actual_rec >= inst.amount else "PARTIAL"
                        )
                        inst.recovered_amount = actual_rec
                        inst.debited_in_run = run
                        inst.debited_in_payslip = matching_slip
                        inst.debited_at = timezone.now()
                        inst.save(
                            update_fields=[
                                "status",
                                "recovered_amount",
                                "debited_in_run",
                                "debited_in_payslip",
                                "debited_at",
                            ]
                        )

                        adv = inst.advance
                        adv.outstanding = max(
                            Decimal("0.00"), adv.outstanding - inst.recovered_amount
                        )
                        if adv.outstanding <= Decimal("0.00"):
                            adv.status = "Recovered"
                        adv.save(update_fields=["outstanding", "status", "updated_at"])

            from .models import PayrollRunComment

            PayrollRunComment.objects.create(
                run=run,
                author=request.user,
                comment=f"Approval Remarks: {comment_text}",
            )

        from employees.models import Notification
        from authentication.permissions import coerce_permission_bool

        for emp in Employee.objects.filter(status="Active"):
            if (
                emp.dynamic_role
                and emp.dynamic_role.permissions
                and coerce_permission_bool(
                    emp.dynamic_role.permissions.get("can_release_salary")
                )
            ):
                Notification.objects.create(
                    recipient=emp,
                    title="Payroll Approved",
                    message=f"Payroll for {run.period} has been approved by the CEO and is pending finance disbursement.",
                    related_run_id=run.id,
                )

            if run.maker and hasattr(run.maker, "employee_profile"):
                Notification.objects.create(
                    recipient=run.maker.employee_profile,
                    title="Payroll Approved",
                    message=f"Your payroll run for {run.period} was approved and forwarded to Finance.",
                    related_run_id=run.id,
                )

        return Response({"status": "success", "run_status": run.status})

    @action(detail=True, methods=["post"])
    def reject(self, request, pk=None):
        user = request.user
        from authentication.permissions import user_can_approve

        if not user_can_approve(user, module="Run Payroll"):
            return Response(
                {
                    "error": "Permission denied. You do not have permission to reject payroll."
                },
                status=403,
            )

        comment_text = request.data.get("comment")
        if not comment_text:
            return Response({"error": "Comment is required"}, status=400)

        from django.db import transaction

        with transaction.atomic():
            run = PayrollRun.objects.select_for_update().filter(pk=pk).first()
            if not run:
                return Response({"error": "Payroll run not found"}, status=404)
            if run.status != "Maker-Submitted":
                return Response(
                    {"error": "Can only reject Maker-Submitted runs"}, status=400
                )

            from .models import PayrollRunComment

            PayrollRunComment.objects.create(
                run=run, author=request.user, comment=comment_text
            )

            run.status = "Rejected"
            run.save(update_fields=["status"])

        # Notify maker and users who can run payroll
        from employees.models import Notification, Employee

        recipients = set()
        if run.maker and hasattr(run.maker, "employee_profile"):
            recipients.add(run.maker.employee_profile)

        from authentication.permissions import check_user_permission

        for emp in Employee.objects.filter(status="Active").select_related("user"):
            if emp.user and (
                emp.user.is_superuser
                or check_user_permission(emp.user, "can_run_payroll")
            ):
                recipients.add(emp)

        for recipient in recipients:
            Notification.objects.create(
                recipient=recipient,
                title="Payroll Run Rejected",
                message=f"Payroll for {run.period} was rejected. Reason: {comment_text}",
                related_run_id=run.id,
            )

        return Response({"status": "success", "run_status": run.status})


class LoanViewSet(DataIsolationMixin, viewsets.ModelViewSet):
    rbac_module = "Loans & Advances"
    queryset = (
        Loan.objects.all()
        .select_related("employee", "approved_by")
        .prefetch_related("installments")
        .order_by("-id")
    )
    serializer_class = LoanSerializer

    def perform_create(self, serializer):
        loan = serializer.save()
        if loan.status == "Active":
            loan.generate_schedule()

    def perform_update(self, serializer):
        loan = serializer.save()
        if loan.status == "Active" and loan.installments.count() == 0:
            loan.generate_schedule()

    @action(detail=True, methods=["get"])
    def statement(self, request, pk=None):
        loan = self.get_object()
        user = request.user
        from authentication.permissions import is_ceo_user

        # Employee can only view their own loan; CEO/SuperAdmin can view any
        is_own = (
            getattr(user, "employee_profile", None)
            and user.employee_profile.id == loan.employee_id
        )
        if not is_ceo_user(user) and not is_own:
            return Response(
                {
                    "error": "Permission denied. You are only authorized to view your own loan statements."
                },
                status=403,
            )

        # Ensure schedule is generated if missing
        if loan.installments.count() == 0:
            loan.generate_schedule()

        installments = loan.installments.all().order_by("installment_number")
        inst_serializer = LoanInstallmentSerializer(installments, many=True)
        loan_serializer = LoanSerializer(loan)

        next_due = installments.filter(status="PENDING").first()

        return Response(
            {
                "loan": loan_serializer.data,
                "installments": inst_serializer.data,
                "summary": {
                    "principal": float(loan.amount),
                    "emi": float(loan.emi),
                    "tenure": loan.tenure,
                    "outstanding": float(loan.outstanding),
                    "totalPaid": float(loan.total_amount_paid),
                    "installmentsPaid": loan.installments_paid_count,
                    "installmentsRemaining": loan.installments_remaining_count,
                    "moratoriumCount": loan.moratorium_count,
                    "nextDue": (
                        LoanInstallmentSerializer(next_due).data if next_due else None
                    ),
                },
            }
        )

    def _execute_skip_installment(
        self, loan, target_inst, strategy, reason, skipped_by, actor=None
    ):
        from django.db import transaction
        from django.utils import timezone
        import calendar
        import datetime
        from decimal import Decimal

        with transaction.atomic():
            loan = Loan.objects.select_for_update().get(pk=loan.pk)
            target_inst = loan.installments.select_for_update().get(pk=target_inst.pk)

            # Mark target as SKIPPED
            target_inst.status = "SKIPPED"
            target_inst.skip_strategy = strategy
            target_inst.skip_reason = reason
            target_inst.skipped_by = skipped_by
            target_inst.skipped_at = timezone.now()
            target_inst.save()

            loan.moratorium_count += 1

            if strategy == "EXTEND_TENURE":
                loan.tenure += 1
                loan.save(update_fields=["tenure", "moratorium_count", "updated_at"])

                last_inst = loan.installments.order_by("-installment_number").first()
                if last_inst:
                    last_parts = last_inst.period.split("-")
                    l_year, l_month = int(last_parts[0]), int(last_parts[1])
                    next_month = (l_month % 12) + 1
                    next_year = l_year + (1 if l_month == 12 else 0)
                    next_period = f"{next_year:04d}-{next_month:02d}"
                    last_day = calendar.monthrange(next_year, next_month)[1]
                    due_date = datetime.date(next_year, next_month, min(last_day, 28))

                    new_inst_number = last_inst.installment_number + 1
                else:
                    next_period = timezone.now().strftime("%Y-%m")
                    due_date = timezone.now().date()
                    new_inst_number = 1

                LoanInstallment.objects.create(
                    loan=loan,
                    installment_number=new_inst_number,
                    period=next_period,
                    due_date=due_date,
                    emi_amount=target_inst.emi_amount,
                    principal_amount=target_inst.emi_amount,
                    paid_amount=Decimal("0.00"),
                    balance_after=Decimal("0.00"),
                    status="PENDING",
                )

            elif strategy == "ADJUST_NEXT_MONTH":
                loan.save(update_fields=["moratorium_count", "updated_at"])
                next_pending = (
                    loan.installments.filter(
                        installment_number__gt=target_inst.installment_number,
                        status="PENDING",
                    )
                    .order_by("installment_number")
                    .first()
                )

                if next_pending:
                    next_pending.emi_amount += target_inst.emi_amount
                    next_pending.principal_amount += target_inst.emi_amount
                    next_pending.save(update_fields=["emi_amount", "principal_amount"])
                else:
                    loan.tenure += 1
                    loan.save(update_fields=["tenure"])
                    last_parts = target_inst.period.split("-")
                    l_year, l_month = int(last_parts[0]), int(last_parts[1])
                    next_month = (l_month % 12) + 1
                    next_year = l_year + (1 if l_month == 12 else 0)
                    next_period = f"{next_year:04d}-{next_month:02d}"
                    last_day = calendar.monthrange(next_year, next_month)[1]
                    due_date = datetime.date(next_year, next_month, min(last_day, 28))
                    LoanInstallment.objects.create(
                        loan=loan,
                        installment_number=target_inst.installment_number + 1,
                        period=next_period,
                        due_date=due_date,
                        emi_amount=target_inst.emi_amount,
                        principal_amount=target_inst.emi_amount,
                        paid_amount=Decimal("0.00"),
                        balance_after=Decimal("0.00"),
                        status="PENDING",
                    )

            # Recalculate balance_after sequentially across all installments
            cur_bal = loan.amount
            for inst in loan.installments.order_by("installment_number"):
                if inst.status == "DEBITED":
                    cur_bal = max(Decimal("0.00"), cur_bal - inst.paid_amount)
                elif inst.status == "PENDING":
                    cur_bal = max(Decimal("0.00"), cur_bal - inst.emi_amount)
                inst.balance_after = cur_bal
                inst.save(update_fields=["balance_after"])

            from .models import PayrollEvent

            PayrollEvent.objects.create(
                type="LoanEmiSkipped",
                actor=actor,
                reference=f"LOAN-{loan.id}-INST-{target_inst.installment_number}",
                payload={
                    "loan_id": loan.id,
                    "employee": loan.employee.code,
                    "installment_number": target_inst.installment_number,
                    "period": target_inst.period,
                    "strategy": strategy,
                    "reason": reason,
                    "new_tenure": loan.tenure,
                },
            )
        return target_inst

    @action(detail=True, methods=["post"], url_path="skip-emi")
    def skip_emi(self, request, pk=None):
        from authentication.permissions import is_ceo_user

        if not is_ceo_user(request.user):
            return Response(
                {
                    "error": "Permission denied. Only Executive Management / CEO can approve skipping an EMI."
                },
                status=403,
            )

        loan = self.get_object()
        if loan.status != "Active":
            return Response(
                {"error": "Can only skip EMIs for Active loans."},
                status=400,
            )

        installment_id = request.data.get("installment_id")
        strategy = request.data.get(
            "strategy", "EXTEND_TENURE"
        )  # Default: Extend Tenure
        reason = (request.data.get("reason") or "").strip()

        if not reason:
            return Response(
                {
                    "error": "A mandatory reason for skipping the EMI (e.g. employee relief request) is required."
                },
                status=400,
            )

        if strategy not in ["EXTEND_TENURE", "ADJUST_NEXT_MONTH"]:
            return Response(
                {
                    "error": "Invalid strategy. Must be EXTEND_TENURE or ADJUST_NEXT_MONTH."
                },
                status=400,
            )

        if installment_id:
            target_inst = loan.installments.filter(id=installment_id).first()
        else:
            target_inst = (
                loan.installments.filter(status="PENDING")
                .order_by("installment_number")
                .first()
            )

        if not target_inst:
            return Response(
                {"error": "No eligible pending installment found to skip."},
                status=400,
            )

        if target_inst.status == "DEBITED":
            return Response(
                {
                    "error": f"Installment #{target_inst.installment_number} has already been debited in payroll and cannot be skipped."
                },
                status=400,
            )

        if target_inst.status == "SKIPPED":
            return Response(
                {
                    "error": f"Installment #{target_inst.installment_number} is already marked as skipped."
                },
                status=400,
            )

        skipped_by = getattr(request.user, "employee_profile", None)
        target_inst = self._execute_skip_installment(
            loan, target_inst, strategy, reason, skipped_by, request.user
        )
        loan.refresh_from_db()

        return Response(
            {
                "status": "success",
                "message": f"Installment #{target_inst.installment_number} for period {target_inst.period} skipped successfully via {strategy}.",
                "loan": LoanSerializer(loan).data,
                "skipped_installment": LoanInstallmentSerializer(target_inst).data,
            }
        )

    @action(detail=True, methods=["post"], url_path="request-relief")
    def request_relief(self, request, pk=None):
        loan = self.get_object()
        if loan.status != "Active":
            return Response(
                {"error": "Can only request EMI relief for Active loans."}, status=400
            )

        from authentication.permissions import is_ceo_user

        emp_profile = getattr(request.user, "employee_profile", None)
        if not is_ceo_user(request.user):
            if not emp_profile or loan.employee_id != emp_profile.id:
                return Response(
                    {
                        "error": "You can only request EMI relief for your own active loans."
                    },
                    status=403,
                )

        reason = (request.data.get("reason") or "").strip()
        preferred_strategy = request.data.get("preferred_strategy", "EITHER")
        installment_id = request.data.get("installment_id")

        if not reason:
            return Response(
                {"error": "A valid reason for requesting EMI relief is required."},
                status=400,
            )

        if loan.relief_requests.filter(status="PENDING").exists():
            return Response(
                {
                    "error": "A relief request is already pending Executive review for this loan."
                },
                status=400,
            )

        target_inst = None
        if installment_id:
            target_inst = loan.installments.filter(
                id=installment_id, status="PENDING"
            ).first()
        if not target_inst:
            target_inst = (
                loan.installments.filter(status="PENDING")
                .order_by("installment_number")
                .first()
            )

        if not target_inst:
            return Response(
                {"error": "No pending installments found on this loan to defer."},
                status=400,
            )

        relief_req = EmiReliefRequest.objects.create(
            loan=loan,
            installment=target_inst,
            employee=loan.employee,
            reason=reason,
            preferred_strategy=preferred_strategy,
            status="PENDING",
        )

        return Response(
            {
                "status": "success",
                "message": f"EMI relief request for {target_inst.period} submitted to Executive Management.",
                "relief_request": EmiReliefRequestSerializer(relief_req).data,
                "loan": LoanSerializer(loan).data,
            }
        )

    @action(detail=False, methods=["get"], url_path="relief-requests")
    def relief_requests(self, request):
        from authentication.permissions import is_ceo_user

        user = request.user
        qs = EmiReliefRequest.objects.select_related(
            "loan", "installment", "employee"
        ).all()

        if not is_ceo_user(user):
            emp_profile = getattr(user, "employee_profile", None)
            if emp_profile:
                qs = qs.filter(employee=emp_profile)
            else:
                qs = qs.none()

        return Response(EmiReliefRequestSerializer(qs, many=True).data)

    @action(detail=True, methods=["post"], url_path="decide-relief")
    def decide_relief(self, request, pk=None):
        from authentication.permissions import is_ceo_user

        if not is_ceo_user(request.user):
            return Response(
                {
                    "error": "Permission denied. Only Executive Management / CEO can approve or reject EMI relief."
                },
                status=403,
            )

        loan = self.get_object()
        relief_id = request.data.get("relief_id")
        decision = (request.data.get("decision") or "").upper()
        strategy = request.data.get("strategy", "EXTEND_TENURE")
        remarks = (request.data.get("remarks") or "").strip()

        relief_req = (
            loan.relief_requests.filter(id=relief_id, status="PENDING").first()
            if relief_id
            else loan.relief_requests.filter(status="PENDING").first()
        )
        if not relief_req:
            return Response({"error": "Pending relief request not found."}, status=404)

        from django.utils import timezone

        decided_by = getattr(request.user, "employee_profile", None)

        if decision == "REJECT":
            relief_req.status = "REJECTED"
            relief_req.decision_remarks = (
                remarks or "Relief request rejected by Executive Management."
            )
            relief_req.decided_by = decided_by
            relief_req.decided_at = timezone.now()
            relief_req.save()
            return Response(
                {
                    "status": "success",
                    "message": "Relief request rejected.",
                    "loan": LoanSerializer(loan).data,
                    "relief_request": EmiReliefRequestSerializer(relief_req).data,
                }
            )

        if strategy not in ["EXTEND_TENURE", "ADJUST_NEXT_MONTH"]:
            strategy = "EXTEND_TENURE"

        target_inst = relief_req.installment
        if not target_inst or target_inst.status != "PENDING":
            target_inst = (
                loan.installments.filter(status="PENDING")
                .order_by("installment_number")
                .first()
            )

        if not target_inst:
            return Response(
                {"error": "No eligible pending installment to skip."}, status=400
            )

        target_inst = self._execute_skip_installment(
            loan, target_inst, strategy, relief_req.reason, decided_by, request.user
        )
        loan.refresh_from_db()

        relief_req.status = "APPROVED"
        relief_req.applied_strategy = strategy
        relief_req.decision_remarks = (
            remarks or f"Approved via {strategy} by Executive Management."
        )
        relief_req.decided_by = decided_by
        relief_req.decided_at = timezone.now()
        relief_req.save()

        return Response(
            {
                "status": "success",
                "message": f"Relief granted. Installment #{target_inst.installment_number} ({target_inst.period}) deferred via {strategy}.",
                "loan": LoanSerializer(loan).data,
                "relief_request": EmiReliefRequestSerializer(relief_req).data,
            }
        )

    @action(detail=False, methods=["get"], url_path="cockpit-summary")
    def cockpit_summary(self, request):
        from authentication.permissions import is_ceo_user, isolate_queryset
        from django.db.models import Sum

        user = request.user
        loans_qs = isolate_queryset(Loan.objects.all(), user)
        is_ceo = is_ceo_user(user)

        total_loans = loans_qs.count()
        active_loans = loans_qs.filter(status="Active")
        total_disbursed = float(loans_qs.aggregate(s=Sum("amount"))["s"] or 0)
        total_outstanding = float(
            active_loans.aggregate(s=Sum("outstanding"))["s"] or 0
        )

        inst_qs = LoanInstallment.objects.filter(loan__in=loans_qs)
        total_debited = float(
            inst_qs.filter(status="DEBITED").aggregate(s=Sum("paid_amount"))["s"] or 0
        )
        total_pending = float(
            inst_qs.filter(status="PENDING").aggregate(s=Sum("emi_amount"))["s"] or 0
        )
        moratoriums_count = inst_qs.filter(status="SKIPPED").count()
        paid_count = inst_qs.filter(status="DEBITED").count()
        pending_count = inst_qs.filter(status="PENDING").count()
        pending_relief_count = EmiReliefRequest.objects.filter(status="PENDING").count()

        return Response(
            {
                "isExecutive": is_ceo,
                "totalLoans": total_loans,
                "activeLoans": active_loans.count(),
                "closedLoans": loans_qs.filter(status="Closed").count(),
                "totalDisbursed": total_disbursed,
                "totalOutstanding": total_outstanding,
                "totalDebited": total_debited,
                "totalPending": total_pending,
                "paidInstallmentsCount": paid_count,
                "pendingInstallmentsCount": pending_count,
                "moratoriumsCount": moratoriums_count,
                "pendingReliefRequestsCount": pending_relief_count,
            }
        )

    @action(detail=True, methods=["get"], url_path="export-statement")
    def export_statement(self, request, pk=None):
        loan = self.get_object()
        import csv
        from django.http import HttpResponse

        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = (
            f'attachment; filename="loan_statement_{loan.employee.code}_{loan.id}.csv"'
        )

        writer = csv.writer(response)
        writer.writerow(["Loan Passbook Statement"])
        writer.writerow(
            [
                "Employee",
                f"{loan.employee.first_name} {loan.employee.last_name} ({loan.employee.code})",
            ]
        )
        writer.writerow(["Loan Type", loan.type])
        writer.writerow(["Principal Amount", float(loan.amount)])
        writer.writerow(["Monthly EMI", float(loan.emi)])
        writer.writerow(["Tenure (Months)", loan.tenure])
        writer.writerow(["Outstanding Balance", float(loan.outstanding)])
        writer.writerow(["Status", loan.status])
        writer.writerow([])
        writer.writerow(
            [
                "Installment #",
                "Period",
                "Due Date",
                "EMI Amount",
                "Paid Amount",
                "Balance After",
                "Status",
                "Debited Period",
                "Skip Strategy",
                "Skip Reason",
            ]
        )

        for inst in loan.installments.order_by("installment_number"):
            writer.writerow(
                [
                    inst.installment_number,
                    inst.period,
                    inst.due_date.strftime("%Y-%m-%d") if inst.due_date else "",
                    float(inst.emi_amount),
                    float(inst.paid_amount),
                    float(inst.balance_after),
                    inst.status,
                    inst.debited_in_run.period if inst.debited_in_run else "",
                    inst.skip_strategy if inst.skip_strategy != "NONE" else "",
                    inst.skip_reason or "",
                ]
            )

        return response


class SalaryAdvanceViewSet(DataIsolationMixin, viewsets.ModelViewSet):
    rbac_module = "Loans & Advances"
    queryset = (
        SalaryAdvance.objects.all()
        .select_related("employee", "approved_by")
        .prefetch_related("installments")
        .order_by("-id")
    )
    serializer_class = SalaryAdvanceSerializer

    def perform_create(self, serializer):
        from decimal import Decimal
        from django.utils import timezone

        amount = serializer.validated_data.get("amount", Decimal("0.00"))
        tenure = max(1, serializer.validated_data.get("tenure", 1))
        monthly = (amount / Decimal(str(tenure))).quantize(Decimal("0.01"))

        start_period = serializer.validated_data.get("start_period")
        if not start_period:
            start_period = timezone.now().strftime("%Y-%m")

        advance = serializer.save(
            monthly_installment=monthly,
            outstanding=amount,
            start_period=start_period,
            status="Pending",
        )
        advance.generate_schedule(start_period)

    @action(detail=True, methods=["post"], url_path="approve")
    def approve(self, request, pk=None):
        from django.utils import timezone

        advance = self.get_object()
        if advance.status != "Pending":
            return Response(
                {
                    "error": f"Only pending advances can be approved (current: {advance.status})."
                },
                status=400,
            )

        advance.status = "Approved"
        advance.approved_at = timezone.now()
        if hasattr(request.user, "employee_profile"):
            advance.approved_by = request.user.employee_profile
        advance.save()
        return Response(self.get_serializer(advance).data)

    @action(detail=True, methods=["post"], url_path="disburse")
    def disburse(self, request, pk=None):
        from django.utils import timezone

        advance = self.get_object()
        if advance.status not in ["Pending", "Approved"]:
            return Response(
                {"error": f"Cannot disburse advance in status: {advance.status}."},
                status=400,
            )

        disbursement_date = (
            request.data.get("disbursement_date") or timezone.now().date()
        )
        disbursement_mode = request.data.get("disbursement_mode", "Bank Transfer")
        disbursement_ref = request.data.get("disbursement_ref", "")
        start_period = request.data.get("start_period") or advance.start_period

        advance.status = "Disbursed"
        advance.disbursement_date = disbursement_date
        advance.disbursement_mode = disbursement_mode
        advance.disbursement_ref = disbursement_ref
        advance.start_period = start_period
        advance.save()

        advance.generate_schedule(start_period)
        return Response(self.get_serializer(advance).data)

    @action(detail=True, methods=["post"], url_path="reject")
    def reject(self, request, pk=None):
        advance = self.get_object()
        if advance.status in ["Disbursed", "Recovered"]:
            return Response(
                {"error": "Cannot reject an already disbursed or recovered advance."},
                status=400,
            )
        advance.status = "Rejected"
        advance.save(update_fields=["status"])
        return Response(self.get_serializer(advance).data)

    @action(detail=False, methods=["get"], url_path="summary")
    def summary(self, request):
        from django.db.models import Sum

        qs = self.get_queryset()
        total_disbursed = float(
            qs.filter(status__in=["Disbursed", "Recovered"]).aggregate(s=Sum("amount"))[
                "s"
            ]
            or 0
        )
        total_outstanding = float(
            qs.filter(status="Disbursed").aggregate(s=Sum("outstanding"))["s"] or 0
        )
        total_recovered = float(
            qs.aggregate(s=Sum("installments__recovered_amount"))["s"] or 0
        )
        active_count = qs.filter(status="Disbursed").count()
        pending_count = qs.filter(status="Pending").count()

        return Response(
            {
                "totalDisbursed": total_disbursed,
                "totalOutstanding": total_outstanding,
                "totalRecovered": total_recovered,
                "activeCount": active_count,
                "pendingCount": pending_count,
            }
        )


from djangorestframework_camel_case.parser import (
    CamelCaseMultiPartParser,
    CamelCaseFormParser,
    CamelCaseJSONParser,
)


class ReimbursementViewSet(DataIsolationMixin, viewsets.ModelViewSet):
    rbac_module = "Reimbursements"
    queryset = Reimbursement.objects.all()
    serializer_class = ReimbursementSerializer
    parser_classes = (
        CamelCaseMultiPartParser,
        CamelCaseFormParser,
        CamelCaseJSONParser,
    )


class SalarySlipAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            period = request.query_params.get("period")
            from .models import Payslip

            user = request.user
            from authentication.permissions import isolate_queryset

            user = request.user
            from authentication.permissions import is_ceo_user

            can_view_confidential = is_ceo_user(user)

            # Determine all periods where payroll has been run or payslips exist
            from payroll.models import PayrollRun

            run_periods = set(
                filter(
                    None,
                    isolate_queryset(PayrollRun.objects.all(), user).values_list(
                        "period", flat=True
                    ),
                )
            )
            slip_periods = set(
                filter(
                    None,
                    isolate_queryset(Payslip.objects.all(), user).values_list(
                        "period", flat=True
                    ),
                )
            )
            all_available_periods = sorted(
                list(run_periods | slip_periods), reverse=True
            )

            # If period was missing, check if latest run/slip exists in isolated scope
            if not request.query_params.get("period"):
                if all_available_periods:
                    period = all_available_periods[0]
                else:
                    from django.utils import timezone

                    period = timezone.now().strftime("%Y-%m")

        except Exception as e:
            import traceback

            print("Payroll Query Error:", traceback.format_exc())
            raise e

        try:
            import calendar
            from datetime import date

            p_year, p_month = map(int, period.split("-"))
            _, total_days_in_month = calendar.monthrange(p_year, p_month)
            month_start = date(p_year, p_month, 1)
            month_end = date(p_year, p_month, total_days_in_month)
            calc_end = month_end
            db_slips = (
                isolate_queryset(Payslip.objects.all(), user)
                .filter(period=period)
                .select_related("employee", "employee__manager", "employee__department")
                .prefetch_related("lines", "lines__rule")
            )

            # Determine if we should dynamically calculate
            from payroll.models import PayrollRun

            run = PayrollRun.objects.filter(period=period).first()
            is_draft = run and run.status == "Draft"

            # Precompute data for dynamic calculation if needed
            precomputed_data = {}
            if is_draft:
                from payroll.service import PayrollService

                precomputed_data = PayrollService._precompute_payroll_data(run)
                from payroll.engine import build_dag_and_sort

            slips = []

            # If no slips exist yet (but a run exists) we can preview for all isolated employees
            if not db_slips and is_draft:
                from django.db.models import Q

                preview_emps = isolate_queryset(
                    Employee.objects.filter(status="Active"), user
                ).filter(
                    Q(entity=run.entity)
                    | Q(branch__entity=run.entity)
                    | Q(site__branch__entity=run.entity)
                )
                db_slips = [
                    Payslip(employee=e, run=run, period=period) for e in preview_emps
                ]

            from attendance.models import DailyAttendance

            for slip in db_slips:
                emp = slip.employee
                components = {}
                paid_leave_days = 0

                if is_draft:
                    # DYNAMIC PREVIEW: Calculate 100% real-time using current CTC and formulas
                    try:
                        emp_rules = (
                            list(emp.salary_structure.components.all())
                            if getattr(emp, "salary_structure", None)
                            else []
                        )
                        emp._cached_dag = (
                            build_dag_and_sort(emp_rules) if emp_rules else []
                        )
                        gross, ded, net, line_items = (
                            PayrollService.process_employee_in_memory(
                                emp, run, precomputed_data, is_simulation=True
                            )
                        )
                        slip.gross = gross
                        slip.deductions = ded
                        slip.net = net
                        for item in line_items:
                            components[item["rule"].name.strip()] = item["amount"]
                    except Exception as e:
                        # Fallback to empty if calculation fails
                        slip.gross = 0
                        slip.deductions = 0
                        slip.net = 0
                        slip.engine_error = str(e)
                else:
                    # DATABASE SNAPSHOT
                    try:
                        for line in slip.lines.all():
                            name = line.rule.name.strip()
                            if name in components:
                                components[f"{name} (2)"] = line.amount
                            else:
                                components[name] = line.amount
                    except ValueError:
                        pass

                emp_doj = emp.doj if emp.doj else month_start
                calc_start = max(month_start, emp_doj)

                if slip.id and not is_draft:
                    days_present = float(slip.days_present or 0)
                    days_paid = float(slip.days_paid or 0)
                    calc_days = int(slip.total_days or calc_days)
                    lop_days = float(slip.lop_days or 0)
                    half_day_count = float(slip.half_days or 0)
                    late_penalty_days = float(slip.late_penalty_days or 0)
                    late_count = int(late_penalty_days * 3)
                    total_ot_hours = float(slip.ot_hours or 0)
                    paid_leave_days = float(slip.annual_leaves or 0)
                    days_absent = max(0.0, float(calc_days) - days_paid)
                    days_off = sum(
                        1
                        for i in range(calc_days)
                        if date.fromordinal(month_start.toordinal() + i).weekday() == 6
                    )
                elif emp_doj > calc_end:
                    days_paid, days_present, days_off, days_absent, late_count = (
                        0,
                        0,
                        0,
                        0,
                        0,
                    )
                else:
                    calc_days = (calc_end - calc_start).days + 1
                    days_off = sum(
                        1
                        for i in range(calc_days)
                        if date.fromordinal(calc_start.toordinal() + i).weekday() == 6
                    )

                    # Fix: calculate absences by counting present/late days, rather than relying on explicit 'Absent' records.
                    # Dynamic Punch-Driven Model
                    present_count = DailyAttendance.objects.filter(
                        employee=emp,
                        attendance_date__gte=calc_start,
                        attendance_date__lte=calc_end,
                        attendance_status__in=["Present", "Late"],
                    ).count()

                    half_day_count = DailyAttendance.objects.filter(
                        employee=emp,
                        attendance_date__gte=calc_start,
                        attendance_date__lte=calc_end,
                        attendance_status="Half Day",
                    ).count()

                    absent_count = DailyAttendance.objects.filter(
                        employee=emp,
                        attendance_date__gte=calc_start,
                        attendance_date__lte=calc_end,
                        attendance_status="Absent",
                    ).count()

                    late_count = DailyAttendance.objects.filter(
                        employee=emp,
                        attendance_date__gte=calc_start,
                        attendance_date__lte=calc_end,
                        attendance_status="Late",
                    ).count()
                    late_penalty_days = (late_count // 3) * 0.5

                    # Recalculate overtime_hours based on shift threshold rules for this period
                    for att in DailyAttendance.objects.filter(
                        employee=emp,
                        attendance_date__gte=calc_start,
                        attendance_date__lte=calc_end,
                        total_work_hours__gt=0,
                    ):
                        correct_ot = att.compute_overtime(float(att.total_work_hours))
                        if float(att.overtime_hours or 0) != float(correct_ot):
                            DailyAttendance.objects.filter(id=att.id).update(
                                overtime_hours=correct_ot
                            )

                    from django.db.models import Sum

                    ot_agg = DailyAttendance.objects.filter(
                        employee=emp,
                        attendance_date__gte=calc_start,
                        attendance_date__lte=calc_end,
                    ).aggregate(total_ot=Sum("overtime_hours"))
                    total_ot_hours = float(ot_agg["total_ot"] or 0.0)

                    paid_leave_days = sum(
                        (min(l.end_date, calc_end) - max(l.start_date, calc_start)).days
                        + 1
                        for l in emp.leave_requests.filter(
                            status="Approved",
                            start_date__lte=calc_end,
                            end_date__gte=calc_start,
                        )
                        if "lop" not in (l.leave_type.name or "").lower()
                    )

                    lop_days = sum(
                        (min(l.end_date, calc_end) - max(l.start_date, calc_start)).days
                        + 1
                        for l in emp.leave_requests.filter(
                            status="Approved",
                            start_date__lte=calc_end,
                            end_date__gte=calc_start,
                        )
                        if "lop" in (l.leave_type.name or "").lower()
                    )

                    worked_days = float(present_count) + (float(half_day_count) * 0.5)

                    if worked_days == 0 and paid_leave_days == 0:
                        days_paid = 0
                        days_present = 0
                        days_absent = calc_days
                    else:
                        days_present = min(worked_days, calc_days)
                        days_paid = max(
                            0.0,
                            min(
                                worked_days
                                + float(days_off)
                                + float(paid_leave_days)
                                - float(absent_count)
                                - float(lop_days)
                                - float(late_penalty_days),
                                float(calc_days),
                            ),
                        )
                        days_absent = max(0.0, calc_days - days_paid)

                # Use the exact DB snapshot values without applying a secondary proration
                slip_gross = float(slip.gross)
                slip_ded = float(slip.deductions)
                slip_net = float(slip.net)

                # Synchronize snapshot Overtime Allowance if OT was recalculated (drafts only)
                if is_draft:
                    ot_lines = (
                        slip.lines.filter(rule__name__icontains="overtime")
                        if slip.id
                        else None
                    )
                    if (
                        ot_lines is not None and ot_lines.exists()
                    ) or "Overtime Allowance" in components:
                        old_ot_amt = (
                            sum(float(l.amount) for l in ot_lines)
                            if (ot_lines is not None and ot_lines.exists())
                            else float(components.get("Overtime Allowance", 0))
                        )
                        if total_ot_hours == 0:
                            if ot_lines is not None:
                                ot_lines.delete()
                            components.pop("Overtime Allowance", None)
                            components.pop("Overtime Pay", None)
                            components.pop("Overtime", None)
                            if old_ot_amt > 0:
                                slip_gross = max(0.0, slip_gross - old_ot_amt)
                                slip_net = max(0.0, slip_net - old_ot_amt)
                                if slip.id:
                                    Payslip.objects.filter(id=slip.id).update(
                                        gross=slip_gross, net=slip_net
                                    )
                        else:
                            basic_amt = 0.0
                            for c_name, c_val in components.items():
                                if "basic" in c_name.lower():
                                    basic_amt = float(c_val)
                                    break
                            if basic_amt == 0.0 and getattr(emp, "ctc", None):
                                basic_amt = (float(emp.ctc) / 12.0) * 0.5

                            # Dynamically resolve OT Multiplier and Base Hours from assigned Shift Definition
                            shift_cfg = PayrollService.resolve_employee_shift_config(
                                emp, {"start_date": calc_start, "end_date": calc_end}
                            )
                            ot_mult = float(shift_cfg["ot_multiplier"])
                            day_hours = float(shift_cfg["base_hours"])

                            emp_ctc = float(getattr(emp, "ctc", 0) or 0)
                            monthly_ctc = (
                                (emp_ctc / 12.0) if emp_ctc > 0 else (basic_amt or 0)
                            )
                            hourly_rate = (
                                monthly_ctc / float(calc_days or 30)
                            ) / day_hours
                            new_ot_amt = round(
                                hourly_rate * ot_mult * total_ot_hours, 2
                            )
                            if abs(new_ot_amt - old_ot_amt) > 0.01:
                                if ot_lines is not None:
                                    ot_lines.update(amount=new_ot_amt)
                                components["Overtime Allowance"] = new_ot_amt
                                diff = new_ot_amt - old_ot_amt
                                slip_gross = max(0.0, slip_gross + diff)
                                slip_net = max(0.0, slip_net + diff)
                                if slip.id:
                                    Payslip.objects.filter(id=slip.id).update(
                                        gross=slip_gross, net=slip_net
                                    )

                for k in list(components.keys()):
                    components[k] = float(components[k])

                # Accurately compute total deductions from components
                ded_keys = [
                    "pf",
                    "pt",
                    "tds",
                    "provident",
                    "professional",
                    "income tax",
                    "loan",
                    "advance",
                    "penalty",
                    "memo",
                    "deduction",
                    "esi",
                ]
                calculated_ded = sum(
                    v
                    for k, v in components.items()
                    if any(d in k.lower() for d in ded_keys)
                )
                if calculated_ded > 0:
                    slip_ded = calculated_ded
                    slip_net = max(0.0, round(slip_gross - slip_ded, 2))
                    if (
                        slip.id
                        and not is_draft
                        and abs(float(slip.deductions or 0) - slip_ded) > 0.01
                    ):
                        Payslip.objects.filter(id=slip.id).update(
                            deductions=slip_ded, net=slip_net
                        )

                # Retroactive Fix: If an employee was saved with full salary but actually had 0 paid days due to the old bug, zero it out dynamically here (only for unexecuted drafts).
                if is_draft and days_paid == 0:
                    slip_gross = 0.0
                    slip_ded = 0.0
                    slip_net = 0.0
                    for k in components:
                        components[k] = 0.0

                is_own_slip = (
                    getattr(user, "employee_profile", None)
                    and user.employee_profile.id == emp.id
                )
                hide_money = not can_view_confidential and not is_own_slip

                actual_components = {}
                actual_gross = 0.0
                if (
                    getattr(emp, "salary_structure", None)
                    and emp.salary_structure.components.exists()
                ):
                    try:
                        struct_rules = list(emp.salary_structure.components.all())
                        from payroll.engine import (
                            build_dag_and_sort,
                            evaluate_component,
                        )

                        sorted_rules = build_dag_and_sort(struct_rules)
                        base_ctx = {
                            "ctc": Decimal(str(emp.ctc or 0)),
                            "monthly_ctc": Decimal(str(emp.ctc or 0)) / Decimal(12),
                            "present_days": Decimal(str(calc_days)),
                            "total_days": Decimal(str(calc_days)),
                            "paid_days": Decimal(str(calc_days)),
                            "overtime_hours": Decimal("0.00"),
                            "ot_hours": Decimal("0.00"),
                            "absent_days": Decimal("0.00"),
                            "lop_days": Decimal("0.00"),
                            "half_day_count": Decimal("0.00"),
                            "late_penalty_days": Decimal("0.00"),
                            "paid_leave_days": Decimal("0.00"),
                            "basic": Decimal("0.00"),
                            "hra": Decimal("0.00"),
                            "non_balancing_gross": Decimal("0.00"),
                        }
                        for r in sorted_rules:
                            base_ctx["non_balancing_gross"] = sum(
                                base_ctx.get(other.name, Decimal("0"))
                                for other in sorted_rules
                                if other.type == "Earning" and other.calc != "Balancing"
                            )
                            actual_val = evaluate_component(r, base_ctx)
                            base_ctx[r.name] = actual_val
                            if r.type == "Earning":
                                actual_components[r.name.strip()] = float(actual_val)
                                actual_gross += float(actual_val)
                    except Exception:
                        pass

                is_ded_key = lambda name: any(
                    d in name.lower()
                    for d in [
                        "pf",
                        "pt",
                        "tds",
                        "provident",
                        "professional",
                        "tax",
                        "deduction",
                        "esi",
                        "loan",
                        "advance",
                        "memo",
                        "penalty",
                    ]
                )
                for k, v in components.items():
                    if k not in actual_components:
                        if days_paid > 0 and days_paid != calc_days:
                            act_val = round(
                                (float(v) / float(days_paid)) * float(calc_days), 2
                            )
                        else:
                            act_val = float(v)
                        actual_components[k] = act_val
                        if not is_ded_key(k):
                            actual_gross += act_val

                if actual_gross == 0:
                    actual_gross = float(emp.ctc or 0) / 12.0 if emp.ctc else slip_gross

                entity_obj = None
                if getattr(emp, "entity", None):
                    entity_obj = emp.entity
                elif getattr(slip, "run", None) and getattr(slip.run, "entity", None):
                    entity_obj = slip.run.entity
                elif getattr(emp, "department", None) and getattr(
                    emp.department, "entity", None
                ):
                    entity_obj = emp.department.entity
                elif getattr(emp, "branch", None) and getattr(
                    emp.branch, "entity", None
                ):
                    entity_obj = emp.branch.entity
                elif (
                    getattr(emp, "site", None)
                    and getattr(emp.site, "branch", None)
                    and getattr(emp.site.branch, "entity", None)
                ):
                    entity_obj = emp.site.branch.entity
                elif getattr(emp, "organization", None):
                    entity_obj = emp.organization

                entity_name = entity_obj.name if entity_obj else ""
                if not entity_name:
                    from authentication.permissions import isolate_queryset

                    first_ent = isolate_queryset(Entity.objects.all(), user).first()
                    if first_ent:
                        entity_name = first_ent.name

                slips.append(
                    {
                        "id": slip.id,
                        "empId": emp.id,
                        "firstName": emp.first_name,
                        "lastName": emp.last_name,
                        "code": emp.code,
                        "email": emp.email,
                        "entityName": entity_name,
                        "designation": (
                            emp.designation.title
                            if getattr(emp, "designation", None)
                            else "N/A"
                        ),
                        "location": (
                            emp.site.name
                            if getattr(emp, "site", None)
                            else (
                                emp.entity.name
                                if getattr(emp, "entity", None)
                                else "Bangalore"
                            )
                        ),
                        "isConfidential": hide_money,
                        "ctc": 0 if hide_money else emp.ctc,
                        "gross": 0 if hide_money else slip_gross,
                        "actual_gross": 0 if hide_money else actual_gross,
                        "components": {} if hide_money else components,
                        "actual_components": {} if hide_money else actual_components,
                        "basic": 0 if hide_money else components.get("basic", 0),
                        "hra": 0 if hide_money else components.get("hra", 0),
                        "special": 0 if hide_money else components.get("special", 0),
                        "pf": (
                            0
                            if hide_money
                            else components.get(
                                "pf", components.get("Provident Fund", 0)
                            )
                        ),
                        "pt": (
                            0
                            if hide_money
                            else components.get(
                                "pt", components.get("Professional Tax", 0)
                            )
                        ),
                        "tds": (
                            0
                            if hide_money
                            else sum(
                                v
                                for k, v in components.items()
                                if "tds" in k.lower() or "income tax" in k.lower()
                            )
                        ),
                        "workerType": getattr(emp, "worker_type", "Salaried"),
                        "tdsApplicable": getattr(emp, "tds_applicable", False),
                        "tdsSection": getattr(emp, "tds_section", "194J_10"),
                        "tdsRate": float(getattr(emp, "tds_rate", 10.0)),
                        "tdsLowerDeductionCert": getattr(
                            emp, "tds_lower_deduction_cert", ""
                        )
                        or "",
                        "isProfessionalFee": getattr(emp, "worker_type", "Salaried")
                        in ["Professional", "Contractor"],
                        "ded": 0 if hide_money else slip_ded,
                        "net": 0 if hide_money else slip_net,
                        "arrears": (
                            0
                            if hide_money
                            else components.get("Retroactive Arrears", 0)
                        ),
                        "bankName": emp.bank_name,
                        "bankAccount": emp.bank_account,
                        "pan": emp.pan,
                        "uan": emp.uan,
                        "doj": emp.doj,
                        "managerName": (
                            f"{emp.manager.first_name} {emp.manager.last_name}"
                            if emp.manager
                            else "—"
                        ),
                        "department": emp.department.name if emp.department else "N/A",
                        "totalDays": calc_days if "calc_days" in locals() else 30,
                        "daysPaid": days_paid,
                        "daysPresent": days_present,
                        "daysOff": days_off,
                        "holidays": float(days_off),
                        "paidLeaves": float(paid_leave_days),
                        "daysAbsent": days_absent,
                        "lopDays": float(lop_days),
                        "extraDays": (
                            float(round(float(total_ot_hours) / 8.0, 2))
                            if "total_ot_hours" in locals()
                            else 0.0
                        ),
                        "lateMarks": int(late_count),
                        "latePenalties": float(late_penalty_days),
                        "halfDays": float(half_day_count),
                        "ot": (
                            float(total_ot_hours)
                            if "total_ot_hours" in locals()
                            else 0.0
                        ),
                        "overtimeHours": (
                            float(total_ot_hours)
                            if "total_ot_hours" in locals()
                            else 0.0
                        ),
                        "overtimePay": (
                            0
                            if hide_money
                            else float(
                                components.get("Overtime Allowance", 0)
                                or components.get("Overtime Pay", 0)
                                or components.get("Overtime", 0)
                            )
                        ),
                        "error": getattr(slip, "engine_error", None),
                        "loanDetails": (
                            [
                                {
                                    "loanId": l.id,
                                    "type": l.type,
                                    "amount": 0 if hide_money else float(l.amount),
                                    "emi": 0 if hide_money else float(l.emi),
                                    "tenure": l.tenure,
                                    "outstanding": (
                                        0 if hide_money else float(l.outstanding)
                                    ),
                                    "installmentsPaid": l.installments_paid_count,
                                    "installmentsRemaining": l.installments_remaining_count,
                                }
                                for l in emp.loans.filter(status="Active")
                            ]
                            if hasattr(emp, "loans")
                            else []
                        ),
                        "loanRemarks": (
                            [
                                f"Loan EMI for {inst.loan.type} deferred by Management approval ({inst.skip_reason or 'Relief Request'})"
                                for inst in LoanInstallment.objects.filter(
                                    loan__employee=emp, period=period, status="SKIPPED"
                                ).select_related("loan")
                            ]
                        ),
                        "leaveBalances": (
                            [
                                {
                                    "type": lb.leave_type.name,
                                    "allocated": float(lb.allocated_days),
                                    "used": float(lb.used_days),
                                    "remaining": float(lb.remaining_days),
                                }
                                for lb in emp.leave_balances.filter(year=p_year)
                            ]
                            if hasattr(emp, "leave_balances")
                            else []
                        ),
                    }
                )
            diagnostics = {
                "total_payslips_in_db": Payslip.objects.count(),
                "slips_for_period": (
                    len(db_slips) if isinstance(db_slips, list) else db_slips.count()
                ),
                "total_employees": Employee.objects.count(),
                "active_employees": Employee.objects.filter(status="Active").count(),
                "employee_details": list(
                    Employee.objects.values("id", "code", "entity_id", "status")
                    if not can_view_confidential
                    else Employee.objects.values(
                        "id", "code", "entity_id", "status", "ctc"
                    )
                ),
                "payroll_runs": list(
                    PayrollRun.objects.values("id", "period", "entity_id", "status")
                ),
                "exceptions": list(
                    PayrollException.objects.values("error_trace").order_by("-id")[:20]
                ),
            }
            if period and period not in all_available_periods:
                all_available_periods.insert(0, period)
            return Response(
                {
                    "period": period,
                    "slips": slips,
                    "availablePeriods": all_available_periods,
                    "diagnostics": diagnostics,
                }
            )
        except Exception as e:
            import traceback

            print("Payroll Process Error:", traceback.format_exc())
            raise e


from django.http import HttpResponse


class PayslipPDFView(APIView):
    def get(self, request, pk=None):
        from .models import Payslip
        from authentication.permissions import can_view_salary

        try:
            slip = (
                Payslip.objects.select_related("employee", "employee__department")
                .prefetch_related("lines", "lines__rule")
                .get(pk=pk)
            )
            if not can_view_salary(request.user, slip.employee):
                return Response(
                    {
                        "error": "Unauthorized: Only the CEO can view other employees payslips"
                    },
                    status=403,
                )
        except Payslip.DoesNotExist:
            return Response({"error": "Payslip not found"}, status=404)

        response = HttpResponse(content_type="application/pdf")
        response["Content-Disposition"] = (
            f'attachment; filename="payslip_{slip.period}_{slip.employee.code}.pdf"'
        )

        try:
            from reportlab.pdfgen import canvas
            from reportlab.lib.pagesizes import letter

            p = canvas.Canvas(response, pagesize=letter)
            width, height = letter

            w_type = getattr(slip.employee, "worker_type", "Salaried")
            is_prof = w_type in ["Professional", "Contractor"]
            p.setFont("Helvetica-Bold", 15)
            p.drawString(
                50, height - 50, f"PAYSLIP / PROFESSIONAL FEE VOUCHER ({slip.period})"
            )

            p.setFont("Helvetica", 11)
            p.drawString(
                50,
                height - 75,
                f"Employee / Professional Name: {slip.employee.first_name} {slip.employee.last_name}",
            )
            p.drawString(50, height - 93, f"Code: {slip.employee.code}")
            p.drawString(
                50,
                height - 111,
                f"Department: {slip.employee.department.name if slip.employee.department else 'N/A'}",
            )
            if is_prof:
                sec_desc = (
                    "Section 194J (Professional Services)"
                    if "194J" in getattr(slip.employee, "tds_section", "")
                    else "Section 194C (Contractor)"
                )
                p.drawString(
                    50,
                    height - 129,
                    f"Payment Nature: Professional Fees ({sec_desc}) / Retainer Payout",
                )
                p.drawString(
                    320,
                    height - 93,
                    f"PAN: {slip.employee.pan or 'Not Provided (Sec 206AA Applied)'}",
                )
            else:
                p.drawString(320, height - 93, f"PAN: {slip.employee.pan or 'N/A'}")

            # Show Overtime Hours if recorded for this period
            try:
                import calendar
                from datetime import date
                from django.db.models import Sum
                from attendance.models import DailyAttendance

                p_yr, p_mo = map(int, slip.period.split("-"))
                _, t_days = calendar.monthrange(p_yr, p_mo)
                m_start = date(p_yr, p_mo, 1)
                m_end = date(p_yr, p_mo, t_days)
                ot_sum = (
                    DailyAttendance.objects.filter(
                        employee=slip.employee,
                        attendance_date__gte=m_start,
                        attendance_date__lte=m_end,
                    ).aggregate(total_ot=Sum("overtime_hours"))["total_ot"]
                    or 0.0
                )
                if ot_sum > 0:
                    p.drawString(320, height - 100, f"Overtime Hours: {ot_sum} hrs")

                late_count = DailyAttendance.objects.filter(
                    employee=slip.employee,
                    attendance_date__gte=m_start,
                    attendance_date__lte=m_end,
                    attendance_status="Late",
                ).count()
                if late_count > 0:
                    p.drawString(320, height - 120, f"Late Marks: {late_count} marks")
            except Exception:
                pass

            p.drawString(50, height - 160, "Earnings & Deductions")

            y = height - 190
            for line in slip.lines.all():
                sign = "+" if line.rule.type == "Earning" else "-"
                p.drawString(50, y, f"{line.rule.name}: {sign} {line.amount}")
                y -= 20

            y -= 20
            p.setFont("Helvetica-Bold", 12)
            p.drawString(50, y, f"Total Gross: {slip.gross}")
            y -= 20
            p.drawString(50, y, f"Total Deductions: {slip.deductions}")
            y -= 20
            p.drawString(50, y, f"Net Pay: {slip.net}")

            p.showPage()
            p.save()
            return response
        except Exception as e:
            return Response({"error": str(e)}, status=500)


class PayslipEmailView(APIView):
    def post(self, request, pk=None):
        from .models import Payslip
        from authentication.permissions import isolate_queryset

        try:
            qs = isolate_queryset(Payslip.objects.all(), request.user)
            slip = (
                qs.select_related("employee", "employee__department")
                .prefetch_related("lines", "lines__rule")
                .get(pk=pk)
            )
        except Payslip.DoesNotExist:
            return Response({"error": "Payslip not found or unauthorized"}, status=404)

        try:
            import io
            import base64
            from django.core.mail import EmailMessage
            from django.conf import settings

            pdf_datauri = request.data.get("pdf")
            if pdf_datauri and "," in pdf_datauri:
                base64_data = pdf_datauri.split(",")[1]
                pdf_bytes = base64.b64decode(base64_data)
            else:
                from reportlab.pdfgen import canvas
                from reportlab.lib.pagesizes import letter

                buffer = io.BytesIO()
                p = canvas.Canvas(buffer, pagesize=letter)
                width, height = letter

                p.setFont("Helvetica-Bold", 16)
                p.drawString(50, height - 50, f"Payslip for {slip.period}")

                p.setFont("Helvetica", 12)
                p.drawString(
                    50,
                    height - 80,
                    f"Employee Name: {slip.employee.first_name} {slip.employee.last_name}",
                )
                p.drawString(50, height - 100, f"Employee Code: {slip.employee.code}")
                p.drawString(
                    50,
                    height - 120,
                    f"Department: {slip.employee.department.name if slip.employee.department else 'N/A'}",
                )
                p.drawString(50, height - 160, "Earnings & Deductions")

                y = height - 190
                for line in slip.lines.all():
                    sign = "+" if line.rule.type == "Earning" else "-"
                    p.drawString(50, y, f"{line.rule.name}: {sign} {line.amount}")
                    y -= 20

                y -= 20
                p.setFont("Helvetica-Bold", 12)
                p.drawString(50, y, f"Total Gross: {slip.gross}")
                y -= 20
                p.drawString(50, y, f"Total Deductions: {slip.deductions}")
                y -= 20
                p.drawString(50, y, f"Net Pay: {slip.net}")

                p.showPage()
                p.save()
                pdf_bytes = buffer.getvalue()
                buffer.close()

            org_brand = None
            if hasattr(slip.employee, "organization") and slip.employee.organization:
                org_brand = (
                    getattr(slip.employee.organization, "branding_text", None)
                    or slip.employee.organization.name
                )
            brand_name = org_brand or getattr(settings, "APP_NAME", "HRMS Management")

            email = EmailMessage(
                f"Your Payslip for {slip.period}",
                f"Hello {slip.employee.first_name},\n\nPlease find attached your payslip for the period {slip.period}.\n\nRegards,\n{brand_name}",
                settings.EMAIL_HOST_USER,
                [slip.employee.email],
            )
            email.attach(
                f"payslip_{slip.period}_{slip.employee.code}.pdf",
                pdf_bytes,
                "application/pdf",
            )

            import threading

            threading.Thread(target=email.send).start()

            return Response({"message": "Payslip emailed successfully!"})
        except Exception as e:
            return Response({"error": str(e)}, status=500)


class PayrollPreviewAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request):
        try:
            period = request.query_params.get("period")
            entity_param = request.query_params.get("entity")
            include_leaves_encashment_str = request.query_params.get(
                "include_leaves_encashment", "false"
            )
            include_leaves_encashment = include_leaves_encashment_str.lower() == "true"

            if not period:
                return Response({"error": "Period is required"}, status=400)
                # Direct check for can_view_confidential without empty serializer context
            user = request.user
            from authentication.permissions import is_ceo_user

            can_view_confidential = is_ceo_user(user)

            from organisation.models import Entity
            from payroll.models import PayrollRun
            from employees.models import Employee
            from payroll.service import PayrollService
            from payroll.engine import build_dag_and_sort
            from decimal import Decimal

            if entity_param and entity_param != "__all__":
                entity_ids = [
                    int(x.strip())
                    for x in entity_param.split(",")
                    if x.strip().isdigit()
                ]
                entities = Entity.objects.filter(id__in=entity_ids)
            else:
                entities = Entity.objects.all()

            results = []
            reset_attendance = (
                request.query_params.get("reset", "false").lower() == "true"
            )

            for entity in entities:
                # Check if an existing run with payslips exists for this period and entity (e.g. Rejected, Draft, etc.)
                # If so, load the saved payslips so user-edited attendance, payable days, and amounts are preserved!
                existing_run = PayrollRun.objects.filter(
                    period=period, entity=entity
                ).first()
                if (
                    not reset_attendance
                    and existing_run
                    and existing_run.payslip_set.exists()
                ):
                    slips = (
                        existing_run.payslip_set.all()
                        .select_related(
                            "employee",
                            "employee__department",
                            "employee__designation",
                            "employee__site",
                            "employee__entity",
                            "employee__salary_structure",
                        )
                        .prefetch_related("lines", "lines__rule")
                    )

                    emp_count = 0
                    total_gross = Decimal("0.00")
                    total_deductions = Decimal("0.00")
                    total_net = Decimal("0.00")
                    employee_details = []

                    def sfloat(val):
                        try:
                            return float(val or 0)
                        except:
                            return 0.0

                    hide_money = not can_view_confidential

                    for slip in slips:
                        emp = slip.employee
                        pf_amount = sum(
                            float(l.amount)
                            for l in slip.lines.all()
                            if l.rule and "PF" in str(l.rule.name).upper()
                        )
                        pt_amount = sum(
                            float(l.amount)
                            for l in slip.lines.all()
                            if l.rule
                            and (
                                "PT" in str(l.rule.name).upper()
                                or "PROFESSIONAL TAX" in str(l.rule.name).upper()
                            )
                        )
                        reimbursement = sum(
                            float(l.amount)
                            for l in slip.lines.all()
                            if l.rule and "REIMBURSEMENT" in str(l.rule.name).upper()
                        )
                        incentive = sum(
                            float(l.amount)
                            for l in slip.lines.all()
                            if l.rule
                            and (
                                "INCENTIVE" in str(l.rule.name).upper()
                                or "BONUS" in str(l.rule.name).upper()
                            )
                        )
                        arrears = sum(
                            float(l.amount)
                            for l in slip.lines.all()
                            if l.rule and "ARREAR" in str(l.rule.name).upper()
                        )
                        ot_pay = sum(
                            float(l.amount)
                            for l in slip.lines.all()
                            if l.rule
                            and (
                                "OVERTIME" in str(l.rule.name).upper()
                                or "OT" in str(l.rule.name).upper()
                            )
                        )

                        safe_name = f"{getattr(emp, 'first_name', '')} {getattr(emp, 'last_name', '')}".strip()
                        safe_dept = (
                            emp.department.name
                            if getattr(emp, "department", None)
                            else ""
                        )
                        safe_site = emp.site.name if getattr(emp, "site", None) else ""
                        if getattr(emp, "entity", None):
                            safe_entity = emp.entity.name
                        elif getattr(emp, "branch", None) and getattr(
                            emp.branch, "entity", None
                        ):
                            safe_entity = emp.branch.entity.name
                        elif (
                            getattr(emp, "site", None)
                            and getattr(emp.site, "branch", None)
                            and getattr(emp.site.branch, "entity", None)
                        ):
                            safe_entity = emp.site.branch.entity.name
                        else:
                            safe_entity = entity.name
                        safe_bank = getattr(emp, "bank_name", "")
                        safe_ac = getattr(emp, "bank_account", "")
                        safe_ifsc = getattr(emp, "ifsc", "")

                        total_gross += Decimal(str(slip.gross or 0))
                        total_deductions += Decimal(str(slip.deductions or 0))
                        total_net += Decimal(str(slip.net or 0))
                        emp_count += 1

                        employee_details.append(
                            {
                                "id": emp.id,
                                "name": safe_name,
                                "code": emp.code or f"EMP{emp.id}",
                                "email": getattr(emp, "email", ""),
                                "number": getattr(emp, "phone", "") or "",
                                "workFrom": safe_site,
                                "entity": safe_entity,
                                "_entity": safe_entity,
                                "department": safe_dept,
                                "bankName": safe_bank or "",
                                "acNo": safe_ac or "",
                                "ifscCode": safe_ifsc or "",
                                "currentSalary": (
                                    0 if hide_money else sfloat(getattr(emp, "ctc", 0))
                                ),
                                "totalDays": sfloat(slip.total_days or 30),
                                "presentDays": sfloat(slip.days_present or 0),
                                "leaves": sfloat(slip.annual_leaves or 0),
                                "absentDays": max(
                                    0.0,
                                    sfloat(slip.total_days or 30)
                                    - sfloat(slip.days_paid or 0),
                                ),
                                "lopDays": sfloat(slip.lop_days or 0),
                                "ot": sfloat(slip.ot_hours or 0),
                                "overtimeHours": sfloat(slip.ot_hours or 0),
                                "overtimePay": 0 if hide_money else sfloat(ot_pay),
                                "otMultiplier": float(
                                    getattr(slip, "attendance_snapshot", {}).get(
                                        "ot_multiplier", 2.0
                                    )
                                    if getattr(slip, "attendance_snapshot", None)
                                    else 2.0
                                ),
                                "halfDays": sfloat(slip.half_days or 0),
                                "latePenalties": sfloat(slip.late_penalty_days or 0),
                                "daysPaid": sfloat(slip.days_paid or 0),
                                "totalAmount": 0 if hide_money else sfloat(slip.gross),
                                "arrears": 0 if hide_money else sfloat(arrears),
                                "deduction": (
                                    0 if hide_money else sfloat(slip.deductions)
                                ),
                                "pf": 0 if hide_money else sfloat(pf_amount),
                                "pt": 0 if hide_money else sfloat(pt_amount),
                                "reimbursement": (
                                    0 if hide_money else sfloat(reimbursement)
                                ),
                                "incentive": 0 if hide_money else sfloat(incentive),
                                "payableSalary": 0 if hide_money else sfloat(slip.net),
                                "isConfidential": hide_money,
                                "salaryStructure": (
                                    emp.salary_structure_id
                                    if getattr(emp, "salary_structure_id", None)
                                    else None
                                ),
                                "salary_structure": (
                                    emp.salary_structure_id
                                    if getattr(emp, "salary_structure_id", None)
                                    else None
                                ),
                                "missingFields": [],
                                "hasSalaryStructure": True,
                                "hasCtc": True,
                                "isValidForRun": True,
                            }
                        )

                    results.append(
                        {
                            "entity": entity.name,
                            "entity_id": entity.id,
                            "employees": emp_count,
                            "gross": float(total_gross) if can_view_confidential else 0,
                            "deduction": (
                                float(total_deductions) if can_view_confidential else 0
                            ),
                            "net": float(total_net) if can_view_confidential else 0,
                            "isConfidential": not can_view_confidential,
                            "errors": [],
                            "employee_details": employee_details,
                            "employeeDetails": employee_details,
                            "missing_employees": [],
                            "can_run": True,
                        }
                    )
                    continue

                # Create a mock run for precomputation
                run = PayrollRun(period=period, entity=entity, status="Draft")
                precomputed_data = PayrollService._precompute_payroll_data(run)

                from authentication.permissions import isolate_queryset
                from django.db.models import Q

                employees = (
                    isolate_queryset(
                        Employee.objects.filter(status="Active"), request.user
                    )
                    .filter(
                        Q(entity=entity)
                        | Q(branch__entity=entity)
                        | Q(site__branch__entity=entity)
                    )
                    .select_related("salary_structure")
                    .prefetch_related("salary_structure__components")
                )

                emp_count = 0
                total_gross = Decimal("0.00")
                total_deductions = Decimal("0.00")
                total_net = Decimal("0.00")

                dag_cache = {}
                errors = []
                employee_details = []
                missing_in_entity = []
                from payroll.models import SalaryStructure

                default_structure = SalaryStructure.objects.filter(
                    status="Active"
                ).first()
                for emp in employees:
                    try:
                        struct = resolve_employee_salary_structure(
                            emp, default_structure
                        )
                        missing_fields = []
                        if not struct or struct.components.count() == 0:
                            missing_fields.append("Salary Structure")
                        if not emp.ctc or emp.ctc <= 0:
                            missing_fields.append("CTC")

                        safe_name = f"{getattr(emp, 'first_name', '')} {getattr(emp, 'last_name', '')}".strip()
                        safe_dept = (
                            emp.department.name
                            if getattr(emp, "department", None)
                            else ""
                        )

                        if missing_fields:
                            missing_in_entity.append(
                                {
                                    "id": emp.id,
                                    "code": emp.code or f"EMP{emp.id}",
                                    "name": safe_name
                                    or f"{emp.first_name} {emp.last_name}".strip(),
                                    "department": safe_dept or "N/A",
                                    "designation": (
                                        emp.designation.title
                                        if getattr(emp, "designation", None)
                                        else "N/A"
                                    ),
                                    "entity": entity.name,
                                    "entity_id": entity.id,
                                    "missing": missing_fields,
                                    "missing_salary_structure": "Salary Structure"
                                    in missing_fields,
                                    "missing_ctc": "CTC" in missing_fields,
                                }
                            )

                        assigned_struct = emp.salary_structure or struct
                        if assigned_struct:
                            emp.salary_structure = assigned_struct
                            if assigned_struct.id not in dag_cache:
                                emp_rules = list(assigned_struct.components.all())
                                dag_cache[assigned_struct.id] = (
                                    build_dag_and_sort(emp_rules) if emp_rules else []
                                )
                            emp._cached_dag = dag_cache[assigned_struct.id]
                        else:
                            emp._cached_dag = []

                        gross, ded, net, line_items = (
                            PayrollService.process_employee_in_memory(
                                emp,
                                run,
                                precomputed_data,
                                is_simulation=True,
                                include_leaves_encashment=include_leaves_encashment,
                            )
                        )
                        total_gross += gross
                        total_deductions += ded
                        total_net += net
                        emp_count += 1

                        context = PayrollService._get_context_for_employee(
                            emp, precomputed_data
                        )

                        pf_amount = 0
                        pt_amount = 0
                        reimbursement = 0
                        incentive = 0
                        arrears = 0
                        ot_pay = 0

                        try:
                            pf_amount = sum(
                                item["amount"]
                                for item in line_items
                                if getattr(item["rule"], "name", None)
                                and "PF" in str(item["rule"].name).upper()
                            )
                            pt_amount = sum(
                                item["amount"]
                                for item in line_items
                                if getattr(item["rule"], "name", None)
                                and (
                                    "PT" in str(item["rule"].name).upper()
                                    or "PROFESSIONAL TAX"
                                    in str(item["rule"].name).upper()
                                )
                            )
                            reimbursement = sum(
                                item["amount"]
                                for item in line_items
                                if getattr(item["rule"], "name", None)
                                and "REIMBURSEMENT" in str(item["rule"].name).upper()
                            )
                            incentive = sum(
                                item["amount"]
                                for item in line_items
                                if getattr(item["rule"], "name", None)
                                and (
                                    "INCENTIVE" in str(item["rule"].name).upper()
                                    or "BONUS" in str(item["rule"].name).upper()
                                )
                            )
                            arrears = sum(
                                item["amount"]
                                for item in line_items
                                if getattr(item["rule"], "name", None)
                                and "ARREAR" in str(item["rule"].name).upper()
                            )
                            ot_pay = sum(
                                item["amount"]
                                for item in line_items
                                if getattr(item["rule"], "name", None)
                                and (
                                    "OVERTIME" in str(item["rule"].name).upper()
                                    or "OT" in str(item["rule"].name).upper()
                                )
                            )
                        except Exception as e:
                            print(f"Error summing items: {e}")

                        hide_money = not can_view_confidential

                        # SAFE EXTRACT
                        safe_email = getattr(emp, "email", "")
                        safe_phone = getattr(emp, "phone", "")
                        safe_site = emp.site.name if getattr(emp, "site", None) else ""
                        if getattr(emp, "entity", None):
                            safe_entity = emp.entity.name
                        elif getattr(emp, "branch", None) and getattr(
                            emp.branch, "entity", None
                        ):
                            safe_entity = emp.branch.entity.name
                        elif (
                            getattr(emp, "site", None)
                            and getattr(emp.site, "branch", None)
                            and getattr(emp.site.branch, "entity", None)
                        ):
                            safe_entity = emp.site.branch.entity.name
                        else:
                            safe_entity = ""
                        safe_bank = getattr(emp, "bank_name", "")
                        safe_ac = getattr(emp, "bank_account", "")
                        safe_ifsc = getattr(emp, "ifsc", "")

                        def sfloat(val):
                            try:
                                return float(val or 0)
                            except:
                                return 0.0

                        employee_details.append(
                            {
                                "id": emp.id,
                                "name": safe_name,
                                "code": emp.code or f"EMP{emp.id}",
                                "email": safe_email,
                                "number": safe_phone or "",
                                "workFrom": safe_site,
                                "entity": safe_entity,
                                "department": safe_dept,
                                "bankName": safe_bank or "",
                                "acNo": safe_ac or "",
                                "ifscCode": safe_ifsc or "",
                                "currentSalary": (
                                    0 if hide_money else sfloat(getattr(emp, "ctc", 0))
                                ),
                                "totalDays": sfloat(context.get("total_days", 0)),
                                "presentDays": sfloat(
                                    context.get(
                                        "actual_present_days",
                                        context.get("present_days", 0),
                                    )
                                ),
                                "leaves": sfloat(
                                    context.get(
                                        "annual_leaves",
                                        context.get("paid_leave_days", 0),
                                    )
                                ),
                                "absentDays": sfloat(context.get("absent_days", 0)),
                                "lopDays": sfloat(context.get("lop_days", 0)),
                                "ot": sfloat(
                                    context.get(
                                        "ot_hours", context.get("overtime_hours", 0)
                                    )
                                ),
                                "overtimeHours": sfloat(
                                    context.get(
                                        "ot_hours", context.get("overtime_hours", 0)
                                    )
                                ),
                                "overtimePay": 0 if hide_money else sfloat(ot_pay),
                                "otMultiplier": float(
                                    context.get("ot_multiplier", 2.0)
                                ),
                                "halfDays": sfloat(context.get("half_day_count", 0)),
                                "latePenalties": sfloat(
                                    context.get("late_penalty_days", 0)
                                ),
                                "daysPaid": sfloat(context.get("paid_days", 0)),
                                "totalAmount": 0 if hide_money else sfloat(gross),
                                "arrears": 0 if hide_money else sfloat(arrears),
                                "deduction": 0 if hide_money else sfloat(ded),
                                "pf": 0 if hide_money else sfloat(pf_amount),
                                "pt": 0 if hide_money else sfloat(pt_amount),
                                "reimbursement": (
                                    0 if hide_money else sfloat(reimbursement)
                                ),
                                "incentive": 0 if hide_money else sfloat(incentive),
                                "payableSalary": 0 if hide_money else sfloat(net),
                                "isConfidential": hide_money,
                                "salaryStructure": (
                                    assigned_struct.id if assigned_struct else None
                                ),
                                "salary_structure": (
                                    assigned_struct.id if assigned_struct else None
                                ),
                                "missingFields": missing_fields,
                                "hasSalaryStructure": "Salary Structure"
                                not in missing_fields,
                                "hasCtc": "CTC" not in missing_fields,
                                "isValidForRun": len(missing_fields) == 0,
                            }
                        )
                    except Exception as e:
                        import traceback

                        tb_str = traceback.format_exc()
                        print(f"DEBUG ERRORS for employee {emp.id}:", tb_str)
                        errors.append(f"Emp {emp.id}: {str(e)} | {tb_str}")
                        # Inject error into table for visibility
                        employee_details.append(
                            {
                                "id": emp.id,
                                "name": f"ERROR: {str(e)}",
                                "email": "",
                                "number": "",
                                "workFrom": "",
                                "entity": "",
                                "department": "",
                                "bankName": "",
                                "acNo": "",
                                "ifscCode": "",
                                "currentSalary": 0,
                                "totalDays": 0,
                                "presentDays": 0,
                                "totalAmount": 0,
                                "deduction": 0,
                                "pf": 0,
                                "pt": 0,
                                "reimbursement": 0,
                                "incentive": 0,
                                "payableSalary": 0,
                                "isConfidential": False,
                                "missingFields": ["Configuration error"],
                                "hasSalaryStructure": False,
                                "hasCtc": False,
                                "isValidForRun": False,
                            }
                        )
                        emp_count += 1

                if errors:
                    print(f"DEBUG ERRORS for entity {entity.name}:", errors)

                if emp_count == 0:
                    pass

                results.append(
                    {
                        "entity": entity.name,
                        "employees": emp_count,
                        "gross": float(total_gross) if can_view_confidential else 0,
                        "deduction": (
                            float(total_deductions) if can_view_confidential else 0
                        ),
                        "net": float(total_net) if can_view_confidential else 0,
                        "isConfidential": not can_view_confidential,
                        "errors": errors[:5],  # send first 5 errors for debugging
                        "employee_details": employee_details,
                        "employeeDetails": employee_details,  # Failsafe for OneClickPanel
                        "missing_employees": missing_in_entity,
                        "can_run": len(missing_in_entity) == 0,
                    }
                )

            all_missing = [m for r in results for m in r.get("missing_employees", [])]
            return Response(
                {
                    "status": "success",
                    "data": results,
                    "can_run": len(all_missing) == 0,
                    "missing_employees": all_missing,
                }
            )
        except Exception as e:
            import traceback

            tb = traceback.format_exc()
            # If the entire view crashes, return a fake result so the UI table shows the crash!
            fake_result = [
                {
                    "entity": "CRASH",
                    "employees": 1,
                    "gross": 0,
                    "deduction": 0,
                    "net": 0,
                    "isConfidential": False,
                    "errors": [str(e)],
                    "employee_details": [
                        {
                            "id": 9999,
                            "name": f"CRASH: {str(e)}",
                            "email": str(tb)[:50],
                            "number": "",
                            "workFrom": "",
                            "entity": "",
                            "department": "",
                            "bankName": "",
                            "acNo": "",
                            "ifscCode": "",
                            "currentSalary": 0,
                            "totalDays": 0,
                            "presentDays": 0,
                            "totalAmount": 0,
                            "deduction": 0,
                            "pf": 0,
                            "pt": 0,
                            "reimbursement": 0,
                            "incentive": 0,
                            "payableSalary": 0,
                            "isConfidential": False,
                        }
                    ],
                    "employeeDetails": [],
                }
            ]
            return Response({"status": "success", "data": fake_result})


from .models import Form16Document
from .serializers import Form16DocumentSerializer


class Form16DocumentViewSet(DataIsolationMixin, viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated]
    parser_classes = (
        CamelCaseMultiPartParser,
        CamelCaseFormParser,
        CamelCaseJSONParser,
    )
    queryset = Form16Document.objects.all().order_by("-uploaded_at")
    serializer_class = Form16DocumentSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        user = self.request.user
        emp = getattr(user, "employee_profile", None)

        from authentication.permissions import is_ceo_user

        if is_ceo_user(user):
            return qs

        # Regular employees can only see their own
        if emp:
            return qs.filter(employee=emp)

        return qs.none()

    def perform_create(self, serializer):
        from authentication.permissions import is_ceo_user

        if not is_ceo_user(self.request.user):
            raise exceptions.PermissionDenied(
                "Only the CEO can create or upload Form 16 documents."
            )
        serializer.save(uploaded_by=self.request.user)

    @action(detail=False, methods=["post"])
    def bulk_upload(self, request):
        from authentication.permissions import is_ceo_user

        if not is_ceo_user(request.user):
            return Response(
                {"error": "Unauthorized. Only the CEO can upload Form 16 documents."},
                status=403,
            )
        files = request.FILES.getlist("files")
        financial_year = request.data.get("financial_year", "2025-26")
        mapping_mode = request.data.get("mapping_mode", "filename")

        if not files:
            return Response({"error": "No files provided"}, status=400)

        results = {"success": 0, "failed": 0, "errors": []}

        for file in files:
            # Simple filename parsing logic for demo: EMP0012_FORM16_2025-26.pdf
            filename = file.name
            emp_code = (
                filename.split("_")[0] if "_" in filename else filename.split(".")[0]
            )

            try:
                emp = Employee.objects.get(code=emp_code)

                # Check for existing
                existing = (
                    Form16Document.objects.filter(
                        employee=emp, financial_year=financial_year
                    )
                    .order_by("-version")
                    .first()
                )
                version = existing.version + 1 if existing else 1

                Form16Document.objects.create(
                    employee=emp,
                    financial_year=financial_year,
                    version=version,
                    file=file,
                    uploaded_by=request.user,
                    status="Pending",
                )
                results["success"] += 1
            except Employee.DoesNotExist:
                results["failed"] += 1
                results["errors"].append(
                    f"Employee not found for file {filename} (Code: {emp_code})"
                )
            except Exception as e:
                results["failed"] += 1
                results["errors"].append(f"Error processing {filename}: {str(e)}")

        return Response(results)


from .models import CTCImportHistory
from .serializers import CTCImportHistorySerializer
import csv
import io
import time
from rest_framework.parsers import MultiPartParser
from django.http import HttpResponse


class CTCImportHistoryViewSet(DataIsolationMixin, viewsets.ModelViewSet):
    rbac_module = "Import CTC"
    permission_classes = [IsAuthenticated]
    queryset = CTCImportHistory.objects.all().order_by("-import_date")
    serializer_class = CTCImportHistorySerializer

    def get_queryset(self):
        from authentication.permissions import is_ceo_user

        if not is_ceo_user(self.request.user):
            return CTCImportHistory.objects.none()
        return super().get_queryset()


class ImportCTCTemplateView(APIView):
    rbac_module = "Import CTC"
    permission_classes = [IsAuthenticated]

    def get(self, request):
        from authentication.permissions import is_ceo_user

        if not is_ceo_user(request.user):
            return Response(
                {"error": "Unauthorized. Only the CEO can access CTC templates."},
                status=403,
            )
        response = HttpResponse(content_type="text/csv")
        response["Content-Disposition"] = (
            'attachment; filename="CTC import template.csv"'
        )
        writer = csv.writer(response)

        # Include fields for context to make filling out the template easier
        writer.writerow(
            [
                "Employee Code",
                "First Name",
                "Last Name",
                "Email",
                "Department",
                "Designation",
                "CTC",
                "Tax Regime",
                "Tax Saving Deductions",
                "Salary Structure",
                "PF Applicable",
                "Bonus Applicable",
                "Bonus Type",
                "Bonus Value",
                "Bonus Months",
            ]
        )

        # Output reference dummy rows instead of real employee data
        writer.writerow(
            [
                "EMP-001",
                "John",
                "Doe",
                "john@example.com",
                "Engineering",
                "Developer",
                "1200000",
                "New",
                "0",
                "Client Structure",
                "Yes",
                "Yes",
                "Fixed Amount",
                "50000",
                "1",
            ]
        )
        writer.writerow(
            [
                "EMP-002",
                "Jane",
                "Smith",
                "jane@example.com",
                "HR",
                "Manager",
                "1500000",
                "Old",
                "150000",
                "Client Structure",
                "No",
                "No",
                "",
                "",
                "",
            ]
        )

        return response


class ImportCTCAPIView(APIView):
    rbac_module = "Import CTC"
    permission_classes = [IsAuthenticated]
    parser_classes = [
        CamelCaseMultiPartParser,
        CamelCaseFormParser,
        CamelCaseJSONParser,
    ]

    def post(self, request, *args, **kwargs):
        from authentication.permissions import is_ceo_user

        if not is_ceo_user(request.user):
            return Response(
                {"error": "Unauthorized. Only the CEO can import employee salaries."},
                status=403,
            )
        file = request.FILES.get("file")
        if not file:
            return Response({"detail": "No file uploaded."}, status=400)

        if not file.name.endswith(".csv"):
            return Response(
                {"detail": "Invalid format. Only .csv is supported."}, status=400
            )

        start_time = time.time()

        try:
            decoded_file = file.read().decode("utf-8")
            io_string = io.StringIO(decoded_file)
            reader = csv.DictReader(io_string)
        except Exception as e:
            return Response({"detail": "Invalid format or encoding."}, status=400)

        if (
            not reader.fieldnames
            or "Employee Code" not in reader.fieldnames
            or "CTC" not in reader.fieldnames
        ):
            return Response(
                {
                    "detail": "Invalid format. CSV must contain 'Employee Code' and 'CTC' columns."
                },
                status=400,
            )

        from authentication.permissions import isolate_queryset

        allowed_employees = isolate_queryset(Employee.objects.all(), request.user)
        allowed_employees_dict = {e.code: e for e in allowed_employees}

        successful = 0
        failed = 0

        for row in reader:
            code = row.get("Employee Code", "").strip()

            if not code:
                failed += 1
                continue

            emp = allowed_employees_dict.get(code)
            if not emp:
                failed += 1
                continue

            updated_fields = []

            ctc_val = row.get("CTC", "").strip()
            if ctc_val:
                try:
                    ctc = int(float(ctc_val))
                    emp.ctc = ctc
                    updated_fields.append("ctc")
                except ValueError:
                    pass

            tax_regime = row.get("Tax Regime", "").strip()
            if tax_regime in dict(Employee.TAX_REGIME_CHOICES):
                emp.tax_regime = tax_regime
                updated_fields.append("tax_regime")

            tax_saving = row.get("Tax Saving Deductions", "").strip()
            if tax_saving:
                try:
                    emp.tax_saving_deductions = float(tax_saving)
                    updated_fields.append("tax_saving_deductions")
                except ValueError:
                    pass

            struct_name = row.get("Salary Structure", "").strip()
            if struct_name:
                from payroll.models import SalaryStructure

                struct_qs = isolate_queryset(
                    SalaryStructure.objects.all(), request.user
                )
                struct = struct_qs.filter(name__iexact=struct_name).first()
                if struct:
                    emp.salary_structure = struct
                    updated_fields.append("salary_structure")

            pf_app = row.get("PF Applicable", "").strip().lower()
            if pf_app in ["yes", "true", "1"]:
                emp.pf_applicable = True
                updated_fields.append("pf_applicable")
            elif pf_app in ["no", "false", "0"]:
                emp.pf_applicable = False
                updated_fields.append("pf_applicable")

            bonus_app = row.get("Bonus Applicable", "").strip().lower()
            if bonus_app in ["yes", "true", "1"]:
                emp.bonus_applicable = True
                updated_fields.append("bonus_applicable")
            elif bonus_app in ["no", "false", "0"]:
                emp.bonus_applicable = False
                updated_fields.append("bonus_applicable")

            b_type = row.get("Bonus Type", "").strip()
            if b_type in dict(Employee.BONUS_TYPE_CHOICES):
                emp.bonus_type = b_type
                updated_fields.append("bonus_type")

            b_val = row.get("Bonus Value", "").strip()
            if b_val:
                try:
                    emp.bonus_value = float(b_val)
                    updated_fields.append("bonus_value")
                except ValueError:
                    pass

            b_months = row.get("Bonus Months", "").strip()
            if b_months:
                try:
                    emp.bonus_months = int(float(b_months))
                    updated_fields.append("bonus_months")
                except ValueError:
                    pass

            if updated_fields:
                emp.save(update_fields=updated_fields)

            try:
                from employees.models import CompensationHistory

                latest_history = emp.compensation_history.order_by(
                    "-effective_from"
                ).first()
                if latest_history:
                    CompensationHistory.objects.create(
                        employee=emp,
                        ctc=emp.ctc,
                        salary_structure=latest_history.salary_structure,
                        effective_from=timezone.now().date(),
                        reason="Bulk CTC Import",
                        changed_by=request.user,
                    )
            except Exception as e:
                pass

            successful += 1

        duration = int(time.time() - start_time)
        status_val = (
            "Completed" if failed == 0 else ("Failed" if successful == 0 else "Partial")
        )

        CTCImportHistory.objects.create(
            imported_by=request.user,
            records_processed=successful + failed,
            successful=successful,
            failed=failed,
            file_type="CSV",
            duration_seconds=duration,
            status=status_val,
        )

        return Response(
            {"successful": successful, "failed": failed, "status": status_val}
        )


class WalletPolicyViewSet(DataIsolationMixin, viewsets.ModelViewSet):
    rbac_module = "Payroll Overview"
    queryset = WalletPolicy.objects.all()
    serializer_class = WalletPolicySerializer

    def get_queryset(self):
        qs = super().get_queryset()
        site_id = self.request.query_params.get("site")
        if site_id:
            return qs.filter(site_id=site_id)
        org_id = self.request.query_params.get("organization")
        if org_id:
            return qs.filter(organization_id=org_id)
        return qs

    def create(self, request, *args, **kwargs):
        site_id = request.data.get("site")
        org_id = request.data.get("organization")
        existing = None
        if site_id:
            existing = WalletPolicy.objects.filter(site_id=site_id).first()
        elif org_id:
            existing = WalletPolicy.objects.filter(organization_id=org_id).first()

        if existing:
            serializer = self.get_serializer(existing, data=request.data, partial=True)
            serializer.is_valid(raise_exception=True)
            serializer.save()
            return Response(serializer.data, status=200)
        return super().create(request, *args, **kwargs)


class EmployeeWalletViewSet(DataIsolationMixin, viewsets.ModelViewSet):
    rbac_module = "Payroll Overview"
    queryset = EmployeeWallet.objects.all().select_related(
        "employee",
        "employee__user",
        "employee__department",
        "employee__designation",
        "employee__site",
    )
    serializer_class = EmployeeWalletSerializer

    def get_queryset(self):
        qs = super().get_queryset()
        site_id = self.request.query_params.get("site")
        org_id = self.request.query_params.get("organization")
        emp_id = self.request.query_params.get("employee")

        # Auto-initialize wallets for active employees in the filtered scope if missing
        if site_id:
            from employees.models import Employee

            emps = Employee.objects.filter(site_id=site_id, status="Active")
            existing_wallet_emp_ids = set(
                EmployeeWallet.objects.filter(employee__in=emps).values_list(
                    "employee_id", flat=True
                )
            )
            missing_emps = [e for e in emps if e.id not in existing_wallet_emp_ids]
            if missing_emps:
                EmployeeWallet.objects.bulk_create(
                    [
                        EmployeeWallet(employee=e, current_balance=0.00, is_active=True)
                        for e in missing_emps
                    ],
                    ignore_conflicts=True,
                )
            return qs.filter(employee__site_id=site_id)
        elif org_id:
            from employees.models import Employee

            emps = Employee.objects.filter(entity_id=org_id, status="Active")
            existing_wallet_emp_ids = set(
                EmployeeWallet.objects.filter(employee__in=emps).values_list(
                    "employee_id", flat=True
                )
            )
            missing_emps = [e for e in emps if e.id not in existing_wallet_emp_ids]
            if missing_emps:
                EmployeeWallet.objects.bulk_create(
                    [
                        EmployeeWallet(employee=e, current_balance=0.00, is_active=True)
                        for e in missing_emps
                    ],
                    ignore_conflicts=True,
                )
            return qs.filter(employee__entity_id=org_id)
        elif emp_id:
            return qs.filter(employee_id=emp_id)
        return qs

    @action(detail=True, methods=["post"], url_path="adjust-balance")
    def adjust_balance(self, request, pk=None):
        amount_str = request.data.get("amount")
        txn_type = request.data.get("transaction_type", "MANUAL_ADJUSTMENT")
        notes = request.data.get("notes", "Manual adjustment")
        if not amount_str:
            return Response({"error": "amount is required"}, status=400)
        from decimal import Decimal
        import decimal
        from django.db import transaction

        with transaction.atomic():
            wallet = EmployeeWallet.objects.select_for_update().filter(pk=pk).first()
            if not wallet:
                return Response({"error": "Wallet not found"}, status=404)
            adj_amount = Decimal(str(amount_str)).quantize(
                Decimal("0.01"), rounding=decimal.ROUND_HALF_UP
            )
            new_balance = (wallet.current_balance + adj_amount).quantize(
                Decimal("0.01"), rounding=decimal.ROUND_HALF_UP
            )
            wallet.current_balance = max(Decimal("0.00"), new_balance)
            wallet.save(update_fields=["current_balance", "updated_at"])

            WalletLedgerEntry.objects.create(
                wallet=wallet,
                period=timezone.now().strftime("%Y-%m"),
                transaction_type=txn_type,
                amount=adj_amount,
                balance_after=wallet.current_balance,
                notes=notes,
            )
        return Response(EmployeeWalletSerializer(wallet).data)


# ==========================================
# DISCIPLINARY INFRACTION CATEGORIES VIEWSET
# ==========================================


class DisciplinaryInfractionCategoryViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated]
    queryset = DisciplinaryInfractionCategory.objects.all()
    serializer_class = DisciplinaryInfractionCategorySerializer

    def get_queryset(self):
        qs = DisciplinaryInfractionCategory.objects.filter(is_active=True)
        org_id = self.request.query_params.get(
            "organization"
        ) or self.request.query_params.get("entity")
        if org_id and org_id != "all" and str(org_id).isdigit():
            from django.db.models import Q

            qs = qs.filter(
                Q(organization_id=int(org_id)) | Q(organization__isnull=True)
            )
        return qs.order_by("name")


# ==========================================
# EMPLOYEE DISCIPLINARY MEMO VIEWSET
# ==========================================


class EmployeeDisciplinaryMemoViewSet(viewsets.ModelViewSet):
    permission_classes = [IsAuthenticated]
    queryset = EmployeeDisciplinaryMemo.objects.all()
    serializer_class = EmployeeDisciplinaryMemoSerializer

    def get_queryset(self):
        qs = EmployeeDisciplinaryMemo.objects.all().select_related(
            "employee",
            "employee__dynamic_role",
            "employee__designation",
            "employee__department",
            "employee__site",
            "issued_by",
            "category",
            "payroll_run",
            "payslip",
        )

        site_id = self.request.query_params.get("site")
        emp_id = self.request.query_params.get("employee")
        status_filter = self.request.query_params.get("status")
        active_filter = self.request.query_params.get("is_active")

        if site_id and site_id != "all" and str(site_id).isdigit():
            qs = qs.filter(employee__site_id=int(site_id))
        if emp_id and str(emp_id).isdigit():
            qs = qs.filter(employee_id=int(emp_id))
        if status_filter and status_filter != "ALL":
            qs = qs.filter(status=status_filter)
        if active_filter is not None:
            is_act = active_filter.lower() in ("true", "1")
            qs = qs.filter(is_active=is_act)

        # Scoped access isolation for dynamic roles
        user = self.request.user
        if hasattr(user, "employee_profile") and user.employee_profile:
            emp_prof = user.employee_profile
            role = emp_prof.dynamic_role
            if (
                role
                and role.access_scope == "Site"
                and emp_prof.site_id
                and not site_id
            ):
                qs = qs.filter(employee__site_id=emp_prof.site_id)

        return qs.order_by("-incident_date", "-created_at")

    def perform_create(self, serializer):
        from decimal import Decimal
        import decimal

        issuer = None
        if (
            hasattr(self.request.user, "employee_profile")
            and self.request.user.employee_profile
        ):
            issuer = self.request.user.employee_profile

        raw_amount = self.request.data.get("amount", 0)
        quantized_amt = Decimal(str(raw_amount)).quantize(
            Decimal("0.01"), rounding=decimal.ROUND_HALF_UP
        )

        serializer.save(
            issued_by=issuer, amount=quantized_amt, status="PENDING", is_active=True
        )

    @action(detail=True, methods=["post"], url_path="waive")
    def waive(self, request, pk=None):
        memo = self.get_object()
        if memo.status == "DEDUCTED":
            return Response(
                {
                    "error": "Cannot waive a memo that has already been deducted in payroll."
                },
                status=400,
            )
        memo.status = "WAIVED"
        memo.is_active = False
        memo.save(update_fields=["status", "is_active", "updated_at"])
        return Response(EmployeeDisciplinaryMemoSerializer(memo).data)

    @action(detail=True, methods=["post"], url_path="cancel")
    def cancel(self, request, pk=None):
        memo = self.get_object()
        if memo.status == "DEDUCTED":
            return Response(
                {
                    "error": "Cannot cancel a memo that has already been deducted in payroll."
                },
                status=400,
            )
        memo.status = "CANCELLED"
        memo.is_active = False
        memo.save(update_fields=["status", "is_active", "updated_at"])
        return Response(EmployeeDisciplinaryMemoSerializer(memo).data)

    @action(detail=False, methods=["get"], url_path="summary")
    def summary(self, request):
        site_id = request.query_params.get("site")
        qs = EmployeeDisciplinaryMemo.objects.all()
        if site_id and site_id != "all" and str(site_id).isdigit():
            qs = qs.filter(employee__site_id=int(site_id))

        from django.db.models import Sum
        from decimal import Decimal

        now = timezone.now()
        current_year = now.year
        current_month = now.month

        pending_qs = qs.filter(status="PENDING", is_active=True)
        pending_count = pending_qs.count()
        pending_amount = pending_qs.aggregate(total=Sum("amount"))["total"] or Decimal(
            "0.00"
        )

        deducted_month_qs = qs.filter(
            status="DEDUCTED",
            deducted_at__year=current_year,
            deducted_at__month=current_month,
        )
        deducted_count = deducted_month_qs.count()
        deducted_amount = deducted_month_qs.aggregate(total=Sum("amount"))[
            "total"
        ] or Decimal("0.00")

        total_count = qs.count()

        return Response(
            {
                "pending_count": pending_count,
                "pending_amount": float(pending_amount),
                "deducted_this_month_count": deducted_count,
                "deducted_this_month_amount": float(deducted_amount),
                "total_count": total_count,
            }
        )
