import decimal
from decimal import Decimal
from django.utils import timezone
from .models import ComponentRule, SalaryStructure
from .engine import (
    build_dag_and_sort,
    evaluate_component,
    calculate_tds,
    calculate_professional_tds,
)


class CTCBreakupService:
    @staticmethod
    def calculate_breakup(
        structure_id=None,
        structure=None,
        ctc=0,
        tax_regime="New",
        tds_applicable=True,
        tds_rate=None,
        tds_section=None,
        worker_type="Salaried",
        pan=None,
        employee_id=None,
    ):
        """
        Authoritative single-source-of-truth CTC Breakup calculator.
        Executes the exact same DAG logic as PayrollService for 100% mathematical consistency.
        """
        if employee_id:
            from employees.models import Employee

            emp = Employee.objects.filter(id=employee_id).first()
            if emp:
                if not structure and not structure_id and emp.salary_structure:
                    structure = emp.salary_structure
                if not ctc or Decimal(str(ctc)) <= Decimal("0.00"):
                    ctc = emp.ctc
                if tds_applicable is None:
                    tds_applicable = emp.tds_applicable
                if tds_rate is None and emp.tds_rate is not None:
                    tds_rate = emp.tds_rate
                if tds_section is None and emp.tds_section:
                    tds_section = emp.tds_section
                if pan is None and emp.pan:
                    pan = emp.pan
                if not worker_type and emp.worker_type:
                    worker_type = emp.worker_type
                if not tax_regime and emp.tax_regime:
                    tax_regime = emp.tax_regime

        if not structure and structure_id:
            structure = SalaryStructure.objects.filter(id=structure_id).first()

        if not structure:
            structure = SalaryStructure.objects.filter(status="Active").first()

        annual_ctc = Decimal(str(ctc or 0)).quantize(Decimal("0.01"))
        monthly_ctc = (annual_ctc / Decimal("12.0")).quantize(
            Decimal("0.01"), rounding=decimal.ROUND_HALF_UP
        )

        if not structure:
            # Fallback simple standard structure if no salary structure exists in DB
            basic_monthly = (monthly_ctc * Decimal("0.50")).quantize(Decimal("0.01"))
            hra_monthly = (basic_monthly * Decimal("0.50")).quantize(Decimal("0.01"))
            special_monthly = max(
                Decimal("0.00"), monthly_ctc - basic_monthly - hra_monthly
            )
            gross_monthly = basic_monthly + hra_monthly + special_monthly

            pf_monthly = min(basic_monthly, Decimal("15000.00")) * Decimal("0.12")
            pt_monthly = (
                Decimal("200.00")
                if gross_monthly > Decimal("15000.00")
                else Decimal("0.00")
            )

            tds_monthly = Decimal("0.00")
            if tds_applicable:
                tds_monthly = calculate_tds(
                    ytd_gross=Decimal("0.00"),
                    ytd_tax_paid=Decimal("0.00"),
                    current_month_gross=gross_monthly,
                    remaining_months=12,
                    regime=tax_regime,
                )

            deductions_monthly = pf_monthly + pt_monthly + tds_monthly
            net_monthly = gross_monthly - deductions_monthly

            return {
                "structure_id": None,
                "structure_name": "Standard Fallback Structure",
                "annual_ctc": float(annual_ctc),
                "monthly_ctc": float(monthly_ctc),
                "earnings": [
                    {
                        "name": "Basic Pay",
                        "type": "Earning",
                        "monthly": float(basic_monthly),
                        "annual": float(basic_monthly * 12),
                        "is_statutory": False,
                    },
                    {
                        "name": "House Rent Allowance",
                        "type": "Earning",
                        "monthly": float(hra_monthly),
                        "annual": float(hra_monthly * 12),
                        "is_statutory": False,
                    },
                    {
                        "name": "Special Allowance",
                        "type": "Earning",
                        "monthly": float(special_monthly),
                        "annual": float(special_monthly * 12),
                        "is_statutory": False,
                    },
                ],
                "total_gross_earnings": {
                    "monthly": float(gross_monthly),
                    "annual": float(gross_monthly * 12),
                },
                "employee_deductions": [
                    {
                        "name": "Provident Fund (Employee)",
                        "type": "Deduction",
                        "monthly": float(pf_monthly),
                        "annual": float(pf_monthly * 12),
                        "is_statutory": True,
                    },
                    {
                        "name": "Professional Tax",
                        "type": "Deduction",
                        "monthly": float(pt_monthly),
                        "annual": float(pt_monthly * 12),
                        "is_statutory": True,
                    },
                    {
                        "name": "TDS / Income Tax",
                        "type": "Deduction",
                        "monthly": float(tds_monthly),
                        "annual": float(tds_monthly * 12),
                        "is_statutory": True,
                    },
                ],
                "total_employee_deductions": {
                    "monthly": float(deductions_monthly),
                    "annual": float(deductions_monthly * 12),
                },
                "net_take_home": {
                    "monthly": float(net_monthly),
                    "annual": float(net_monthly * 12),
                },
                "employer_contributions": [
                    {
                        "name": "Provident Fund (Employer)",
                        "type": "Employer Contribution",
                        "monthly": float(pf_monthly),
                        "annual": float(pf_monthly * 12),
                        "is_statutory": True,
                    },
                ],
                "total_employer_cost": {
                    "monthly": float(pf_monthly),
                    "annual": float(pf_monthly * 12),
                },
                "calculated_ctc": {
                    "monthly": float(gross_monthly + pf_monthly),
                    "annual": float((gross_monthly + pf_monthly) * 12),
                },
                "is_balanced": True,
            }

        # Build context
        from django.utils import timezone

        now_m = timezone.now().month
        context = {
            "monthly_ctc": monthly_ctc,
            "annual_ctc": annual_ctc,
            "ctc": annual_ctc,
            "current_month": now_m,
            "month": now_m,
            "year": timezone.now().year,
            "present_days": 30,
            "total_days": 30,
            "paid_days": 30,
            "basic": Decimal("0.00"),
            "hra": Decimal("0.00"),
            "non_balancing_gross": Decimal("0.00"),
            "overtime_hours": Decimal("0.00"),
            "ot_hours": Decimal("0.00"),
            "ot_multiplier": Decimal("1.00"),
            "shift_base_hours": Decimal("8.00"),
            "absent_days": Decimal("0.00"),
            "lop_days": Decimal("0.00"),
            "pf_wage_limit": Decimal("15000.00"),
            "esic_wage_limit": Decimal("21000.00"),
            "gender": "Male",
            "state": "KA",
            "reimbursement": Decimal("0.00"),
        }

        rules = list(structure.components.all())
        sorted_rules = build_dag_and_sort(rules)

        earnings_list = []
        deductions_list = []
        employer_list = []

        total_gross = Decimal("0.00")
        total_deductions = Decimal("0.00")
        total_employer = Decimal("0.00")

        # Two passes: first calculate non-balancing components, then balancing components
        for rule in sorted_rules:
            if rule.calc == "Balancing":
                continue

            r_name_lower = (rule.name or "").lower()
            # Defer TDS/Income tax to post-balancing pass so total gross is finalized
            if "income tax" in r_name_lower or "tds" in r_name_lower:
                continue

            amt = Decimal("0.00")
            if rule.calc == "Fixed":
                amt = Decimal(str(rule.value or 0))
            elif rule.calc == "% of Basic":
                amt = (context["basic"] * Decimal(str(rule.value or 0))) / Decimal(
                    "100.0"
                )
            elif rule.calc == "% of CTC":
                amt = (annual_ctc * Decimal(str(rule.value or 0))) / Decimal("1200.0")
            elif rule.calc == "% of Gross":
                amt = (
                    context.get("gross", monthly_ctc) * Decimal(str(rule.value or 0))
                ) / Decimal("100.0")
            elif rule.calc == "Formula":
                try:
                    amt = evaluate_component(rule, context)
                except Exception:
                    amt = Decimal("0.00")

            amt = amt.quantize(Decimal("0.01"), rounding=decimal.ROUND_HALF_UP)

            # Update context
            r_name_lower = rule.name.lower()
            if "basic" in r_name_lower:
                context["basic"] = amt
                context["BASIC"] = amt
                context["BASIC_PAY"] = amt
            elif "hra" in r_name_lower:
                context["hra"] = amt
                context["HRA"] = amt

            if rule.variable_code:
                context[rule.variable_code] = amt
            context[r_name_lower] = amt

            if rule.type == "Earning":
                context["non_balancing_gross"] += amt
                total_gross += amt
                earnings_list.append(
                    {
                        "name": rule.name,
                        "type": rule.type,
                        "monthly": float(amt),
                        "annual": float(amt * 12),
                        "is_statutory": rule.is_statutory,
                    }
                )
            elif rule.type == "Deduction":
                total_deductions += amt
                deductions_list.append(
                    {
                        "name": rule.name,
                        "type": rule.type,
                        "monthly": float(amt),
                        "annual": float(amt * 12),
                        "is_statutory": rule.is_statutory,
                    }
                )
            elif rule.type == "Employer Contribution":
                total_employer += amt
                employer_list.append(
                    {
                        "name": rule.name,
                        "type": rule.type,
                        "monthly": float(amt),
                        "annual": float(amt * 12),
                        "is_statutory": rule.is_statutory,
                    }
                )

        # Second pass: calculate Balancing components
        for rule in sorted_rules:
            if rule.calc != "Balancing":
                continue

            target_gross = max(Decimal("0.00"), monthly_ctc - total_employer)
            balancing_amt = max(
                Decimal("0.00"), target_gross - context["non_balancing_gross"]
            )
            balancing_amt = balancing_amt.quantize(
                Decimal("0.01"), rounding=decimal.ROUND_HALF_UP
            )

            total_gross += balancing_amt
            context[rule.name.lower()] = balancing_amt
            if rule.variable_code:
                context[rule.variable_code] = balancing_amt

            earnings_list.append(
                {
                    "name": rule.name,
                    "type": rule.type,
                    "monthly": float(balancing_amt),
                    "annual": float(balancing_amt * 12),
                    "is_statutory": rule.is_statutory,
                }
            )

        # Calculate TDS if applicable (or if structure explicitly defines an Income Tax / TDS rule)
        has_tds_component = any(
            "tds" in (r.name or "").lower() or "income tax" in (r.name or "").lower()
            for r in sorted_rules
            if r.type == "Deduction"
        )
        tds_component_name = "Income Tax (TDS)"
        for r in sorted_rules:
            if r.type == "Deduction" and (
                "tds" in (r.name or "").lower() or "income tax" in (r.name or "").lower()
            ):
                tds_component_name = r.name
                break

        tds_amt = Decimal("0.00")
        tds_calc_desc = "TDS Exempt / Non-Applicable"
        if tds_applicable:
            if worker_type in ["Professional", "Contractor"]:
                sec = tds_section or "194J_10"
                c_rate = Decimal(str(tds_rate or "10.00"))
                tds_amt, _, _ = calculate_professional_tds(
                    gross_fee=total_gross,
                    tds_section=sec,
                    custom_rate=c_rate,
                    pan=pan,
                )
                tds_calc_desc = f"TDS u/s {sec} ({c_rate}%)"
            else:
                pan_clean = str(pan or "").strip().upper()
                is_pan_missing = (
                    not pan_clean
                    or pan_clean in ["N/A", "NONE", "NAN", "XXXXX0000X"]
                    or len(pan_clean) < 5
                )
                if is_pan_missing and pan is not None and str(pan).strip():
                    tds_amt = (total_gross * Decimal("0.20")).quantize(
                        Decimal("1.00"), rounding=decimal.ROUND_HALF_UP
                    )
                    tds_calc_desc = "Mandatory 20% TDS u/s 206AA (PAN Missing)"
                elif tds_rate is not None and Decimal(str(tds_rate)) > Decimal("0.00"):
                    custom_pct = Decimal(str(tds_rate)) / Decimal("100.0")
                    tds_amt = (total_gross * custom_pct).quantize(
                        Decimal("1.00"), rounding=decimal.ROUND_HALF_UP
                    )
                    tds_calc_desc = f"{tds_rate}% Profile Rate (Section {tds_section or '192'})"
                else:
                    tds_amt = calculate_tds(
                        ytd_gross=Decimal("0.00"),
                        ytd_tax_paid=Decimal("0.00"),
                        current_month_gross=total_gross,
                        remaining_months=12,
                        regime=tax_regime,
                    )
                    tds_calc_desc = f"Section 192 Tax Slabs ({tax_regime} Regime)"

        if has_tds_component or (tds_applicable and tds_amt > Decimal("0.00")):
            total_deductions += tds_amt
            deductions_list.append(
                {
                    "name": tds_component_name,
                    "type": "Deduction",
                    "monthly": float(tds_amt),
                    "annual": float(tds_amt * 12),
                    "is_statutory": True,
                    "calculation": tds_calc_desc,
                }
            )

        net_take_home = max(Decimal("0.00"), total_gross - total_deductions)
        calculated_ctc_monthly = total_gross + total_employer
        calculated_ctc_annual = calculated_ctc_monthly * 12

        return {
            "structure_id": structure.id,
            "structure_name": structure.name,
            "tax_regime": tax_regime,
            "worker_type": worker_type,
            "annual_ctc": float(annual_ctc),
            "monthly_ctc": float(monthly_ctc),
            "earnings": earnings_list,
            "total_gross_earnings": {
                "monthly": float(total_gross),
                "annual": float(total_gross * 12),
            },
            "employee_deductions": deductions_list,
            "total_employee_deductions": {
                "monthly": float(total_deductions),
                "annual": float(total_deductions * 12),
            },
            "net_take_home": {
                "monthly": float(net_take_home),
                "annual": float(net_take_home * 12),
            },
            "employer_contributions": employer_list,
            "total_employer_cost": {
                "monthly": float(total_employer),
                "annual": float(total_employer * 12),
            },
            "calculated_ctc": {
                "monthly": float(calculated_ctc_monthly),
                "annual": float(calculated_ctc_annual),
            },
            "is_balanced": abs(calculated_ctc_annual - annual_ctc) <= Decimal("100.00"),
        }
