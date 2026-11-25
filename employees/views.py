import csv
import io
from rest_framework import viewsets, exceptions, status
from rest_framework.decorators import action
from djangorestframework_camel_case.parser import (
    CamelCaseMultiPartParser,
    CamelCaseFormParser,
    CamelCaseJSONParser,
)
from rest_framework.response import Response
from django.contrib.auth.models import User
from django.core.mail import send_mail
from django.conf import settings
from .models import Employee
from .serializers import EmployeeSerializer
from authentication.permissions import DataIsolationMixin
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.views import APIView
import json


class EmployeeViewSet(DataIsolationMixin, viewsets.ModelViewSet):
    rbac_module = "Employees"
    queryset = Employee.objects.all()
    serializer_class = EmployeeSerializer
    permission_classes = [IsAuthenticated]

    def get_object(self):
        queryset = self.filter_queryset(self.get_queryset())
        lookup_url_kwarg = self.lookup_url_kwarg or self.lookup_field
        lookup_val = self.kwargs.get(lookup_url_kwarg)

        obj = None
        if lookup_val is not None:
            val_str = str(lookup_val).strip()
            if val_str.isdigit():
                obj = queryset.filter(pk=val_str).first()
            if not obj:
                obj = queryset.filter(code__iexact=val_str).first()

        if not obj:
            raise exceptions.NotFound(f"Employee '{lookup_val}' not found.")

        self.check_object_permissions(self.request, obj)
        return obj

    def get_queryset(self):
        qs = super().get_queryset()
        return qs.select_related(
            "department",
            "designation",
            "dynamic_role",
            "site",
            "entity",
            "organization",
            "salary_structure",
            "manager",
        ).prefetch_related("enrolled_sites")

    def _extract_raw_rows(self, request):
        """Extracts list of row dictionaries from either uploaded CSV file or JSON body."""
        file_obj = request.FILES.get("file")
        if file_obj:
            try:
                content = file_obj.read().decode("utf-8-sig")
            except UnicodeDecodeError:
                file_obj.seek(0)
                content = file_obj.read().decode("latin-1")
            io_string = io.StringIO(content)
            reader = csv.DictReader(io_string)
            return [
                dict(r)
                for r in reader
                if any(str(v).strip() for v in r.values() if v is not None)
            ]

        rows_data = request.data.get("rows")
        if rows_data and isinstance(rows_data, list):
            return rows_data
        if isinstance(request.data, list):
            return request.data
        return []

    def _parse_and_validate_rows(self, raw_rows, user):
        """
        Parses and performs strict validation on employee master data rows.
        Mandatory fields: First Name, Last Name, Employee Code (Option A: unique),
        Contact (Email or Phone), Gender, Date of Joining, and Entity.
        """
        from datetime import datetime
        from django.db.models import Q
        from authentication.permissions import isolate_queryset
        from organisation.models import Entity, Department, Designation, Branch, Site
        from employees.models import Employee

        def _clean_str(v):
            if v is None:
                return ""
            return str(v).replace("\t", "").strip()

        def _get_val(row, *aliases):
            for alias in aliases:
                if alias in row and row[alias] is not None:
                    v = _clean_str(row[alias])
                    if v:
                        return v
            # Case-insensitive & stripped lookup
            row_norm = {
                k.strip().lower().rstrip("*").strip(): v
                for k, v in row.items()
                if isinstance(k, str)
            }
            for alias in aliases:
                norm_key = alias.strip().lower().rstrip("*").strip()
                if norm_key in row_norm and row_norm[norm_key] is not None:
                    v = _clean_str(row_norm[norm_key])
                    if v:
                        return v
            return ""

        def _parse_date(date_str):
            if not date_str:
                return None, None
            s = _clean_str(date_str)
            if not s or s.lower() in ("none", "null", "nan", "-", "undefined"):
                return None, None
            for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%m/%d/%Y", "%d.%m.%Y"):
                try:
                    return datetime.strptime(s, fmt).date().strftime("%Y-%m-%d"), None
                except ValueError:
                    pass
            return None, f"Invalid date '{s}'. Expected DD-MM-YYYY or YYYY-MM-DD."

        def _parse_bool(val, default=False):
            if val is None:
                return default
            if isinstance(val, bool):
                return val
            s = str(val).strip().lower()
            if s in ("true", "1", "yes", "y", "t"):
                return True
            if s in ("false", "0", "no", "n", "f"):
                return False
            return default

        def _parse_float(val, default=0.0):
            if val is None or val == "":
                return default
            try:
                return float(str(val).replace("%", "").strip())
            except (ValueError, TypeError):
                return default

        # Querysets bounded to caller tenant/site scope
        ent_qs = isolate_queryset(Entity.objects.all(), user)
        dept_qs = isolate_queryset(Department.objects.all(), user)
        desg_qs = isolate_queryset(Designation.objects.all(), user)
        branch_qs = isolate_queryset(Branch.objects.all(), user)
        site_qs = isolate_queryset(Site.objects.all(), user)
        manager_qs = isolate_queryset(Employee.objects.all(), user)

        caller_emp = getattr(user, "employee_profile", None)
        default_org = caller_emp.organization if caller_emp else None
        default_ent = caller_emp.entity if caller_emp else None
        default_site = caller_emp.site if caller_emp else None
        default_branch = caller_emp.branch if caller_emp else None

        seen_codes = set()
        seen_emails = set()
        seen_phones = set()

        parsed_rows = []
        errors_summary = []
        total_error_count = 0

        for idx, row in enumerate(raw_rows, start=1):
            row_errors = []

            # 1. Names
            first_name = _get_val(
                row, "first_name", "firstName", "First Name", "First Name*"
            )
            last_name = _get_val(
                row, "last_name", "lastName", "Last Name", "Last Name*"
            )
            if not first_name:
                row_errors.append(
                    {"field": "firstName", "message": "First Name is mandatory."}
                )
            if not last_name:
                row_errors.append(
                    {"field": "lastName", "message": "Last Name is mandatory."}
                )

            # 2. Employee Code (Option A: Reject duplicate employee code)
            code = _get_val(
                row,
                "code",
                "employee_code",
                "employeeCode",
                "Employee Code",
                "Employee Code*",
            )
            if not code:
                row_errors.append(
                    {"field": "code", "message": "Employee Code is mandatory."}
                )
            else:
                code_lower = code.lower()
                if code_lower in seen_codes:
                    row_errors.append(
                        {
                            "field": "code",
                            "message": f"Duplicate Employee Code '{code}' within uploaded batch.",
                        }
                    )
                else:
                    seen_codes.add(code_lower)
                    if Employee.objects.filter(code__iexact=code).exists():
                        row_errors.append(
                            {
                                "field": "code",
                                "message": f"Employee Code '{code}' already exists in system.",
                            }
                        )

            # 3. Contact (Email or Phone is mandatory)
            email = _get_val(row, "email", "Email", "Email*")
            phone = _get_val(row, "phone", "mobile", "Phone", "Phone*")
            clean_phone = (
                "".join(c for c in phone if c.isdigit() or c == "+") if phone else ""
            )

            if not email and not clean_phone:
                row_errors.append(
                    {
                        "field": "email",
                        "message": "At least one contact method (Email or Phone) is mandatory.",
                    }
                )
                row_errors.append(
                    {
                        "field": "phone",
                        "message": "At least one contact method (Email or Phone) is mandatory.",
                    }
                )

            if email:
                if "@" not in email or "." not in email.split("@")[-1]:
                    row_errors.append(
                        {
                            "field": "email",
                            "message": f"Invalid email format '{email}'.",
                        }
                    )
                else:
                    email_lower = email.lower()
                    if email_lower in seen_emails:
                        row_errors.append(
                            {
                                "field": "email",
                                "message": f"Duplicate email '{email}' within uploaded batch.",
                            }
                        )
                    else:
                        seen_emails.add(email_lower)
                        if (
                            User.objects.filter(email__iexact=email).exists()
                            or Employee.objects.filter(email__iexact=email).exists()
                        ):
                            row_errors.append(
                                {
                                    "field": "email",
                                    "message": f"Email '{email}' already registered in system.",
                                }
                            )

            if clean_phone:
                if len(clean_phone.replace("+", "")) < 7:
                    row_errors.append(
                        {
                            "field": "phone",
                            "message": f"Invalid phone number '{phone}' (must be at least 7 digits).",
                        }
                    )
                else:
                    if clean_phone in seen_phones:
                        row_errors.append(
                            {
                                "field": "phone",
                                "message": f"Duplicate phone '{phone}' within uploaded batch.",
                            }
                        )
                    else:
                        seen_phones.add(clean_phone)
                        if (
                            not email
                            and User.objects.filter(username=clean_phone).exists()
                        ):
                            row_errors.append(
                                {
                                    "field": "phone",
                                    "message": f"User account with phone '{clean_phone}' already exists.",
                                }
                            )

            # 4. Gender
            gender_raw = _get_val(row, "gender", "Gender", "Gender*")
            norm_gender = ""
            if not gender_raw:
                row_errors.append(
                    {
                        "field": "gender",
                        "message": "Gender is mandatory (Male, Female, Other).",
                    }
                )
            else:
                g = gender_raw.lower()
                if g in ("male", "m", "man"):
                    norm_gender = "Male"
                elif g in ("female", "f", "woman"):
                    norm_gender = "Female"
                elif g in ("other", "o", "non-binary", "nonbinary"):
                    norm_gender = "Other"
                else:
                    row_errors.append(
                        {
                            "field": "gender",
                            "message": f"Invalid gender '{gender_raw}'. Expected Male, Female, or Other.",
                        }
                    )

            # 5. Date of Joining (Mandatory)
            doj_raw = _get_val(
                row,
                "doj",
                "date_of_joining",
                "dateOfJoining",
                "Date of Joining",
                "Date of Joining*",
                "Date of Joining* (DD-MM-YYYY)",
            )
            doj_parsed, doj_err = _parse_date(doj_raw)
            if not doj_raw:
                row_errors.append(
                    {"field": "doj", "message": "Date of Joining is mandatory."}
                )
            elif doj_err:
                row_errors.append(
                    {"field": "doj", "message": f"Date of Joining: {doj_err}"}
                )

            # 6. Date of Birth (Optional)
            dob_raw = _get_val(
                row,
                "dob",
                "date_of_birth",
                "dateOfBirth",
                "Date of Birth",
                "Date of Birth (DD-MM-YYYY)",
            )
            dob_parsed, dob_err = _parse_date(dob_raw)
            if dob_raw and dob_err:
                row_errors.append(
                    {"field": "dob", "message": f"Date of Birth: {dob_err}"}
                )

            # 7. Entity (Mandatory)
            entity_val = _get_val(
                row,
                "entity",
                "entity_id",
                "entityId",
                "entity_name",
                "entityName",
                "Entity",
                "Entity*",
            )
            ent = None
            if entity_val and entity_val.lower() != "none":
                if entity_val.isdigit():
                    ent = ent_qs.filter(id=int(entity_val)).first()
                if not ent:
                    ent = (
                        ent_qs.filter(code__iexact=entity_val).first()
                        or ent_qs.filter(name__iexact=entity_val).first()
                    )
                if not ent:
                    row_errors.append(
                        {
                            "field": "entity",
                            "message": f"Entity '{entity_val}' not found or not accessible.",
                        }
                    )
            elif default_ent:
                ent = default_ent
            else:
                row_errors.append(
                    {"field": "entity", "message": "Entity is mandatory."}
                )

            # Organization from entity or default
            org = ent.organization if ent else default_org

            # 8. Department & Designation
            dept_val = _get_val(
                row,
                "department",
                "department_id",
                "departmentId",
                "department_name",
                "Department",
            )
            dept = None
            if dept_val and dept_val.lower() != "none":
                if dept_val.isdigit():
                    dept = dept_qs.filter(id=int(dept_val)).first()
                if not dept:
                    dept = (
                        dept_qs.filter(name__iexact=dept_val).first()
                        or dept_qs.filter(code__iexact=dept_val).first()
                    )
                if not dept:
                    row_errors.append(
                        {
                            "field": "department",
                            "message": f"Department '{dept_val}' does not exist.",
                        }
                    )

            desg_val = _get_val(
                row,
                "designation",
                "designation_id",
                "designationId",
                "designation_name",
                "Designation",
            )
            desg = None
            if desg_val and desg_val.lower() != "none":
                if desg_val.isdigit():
                    desg = desg_qs.filter(id=int(desg_val)).first()
                if not desg:
                    desg = desg_qs.filter(title__iexact=desg_val).first()
                if not desg:
                    row_errors.append(
                        {
                            "field": "designation",
                            "message": f"Designation '{desg_val}' does not exist.",
                        }
                    )

            # 9. Branch & Site
            branch_val = _get_val(
                row, "branch", "branch_id", "branchId", "branch_name", "Branch"
            )
            branch = None
            if branch_val and branch_val.lower() != "none":
                if branch_val.isdigit():
                    branch = branch_qs.filter(id=int(branch_val)).first()
                if not branch:
                    branch = (
                        branch_qs.filter(name__iexact=branch_val).first()
                        or branch_qs.filter(code__iexact=branch_val).first()
                    )
                if not branch:
                    row_errors.append(
                        {
                            "field": "branch",
                            "message": f"Branch '{branch_val}' does not exist.",
                        }
                    )
            else:
                branch = default_branch

            site_val = _get_val(row, "site", "site_id", "siteId", "site_name", "Site")
            site = None
            if site_val and site_val.lower() != "none":
                if site_val.isdigit():
                    site = site_qs.filter(id=int(site_val)).first()
                if not site:
                    site = (
                        site_qs.filter(name__iexact=site_val).first()
                        or site_qs.filter(site_code__iexact=site_val).first()
                    )
                if not site:
                    row_errors.append(
                        {
                            "field": "site",
                            "message": f"Site '{site_val}' does not exist.",
                        }
                    )
            else:
                site = default_site

            # 10. Reporting Manager
            mgr_val = _get_val(
                row,
                "manager",
                "reporting_manager",
                "reportingManager",
                "Reporting Manager",
                "Reporting Manager (Code or Email)",
            )
            manager = None
            if mgr_val and mgr_val.lower() not in ("none", "null", "nan", "-", ""):
                if mgr_val.isdigit():
                    manager = manager_qs.filter(id=int(mgr_val)).first()
                if not manager:
                    manager = (
                        manager_qs.filter(code__iexact=mgr_val).first()
                        or manager_qs.filter(email__iexact=mgr_val).first()
                    )
                if not manager:
                    row_errors.append(
                        {
                            "field": "manager",
                            "message": f"Reporting Manager '{mgr_val}' not found.",
                        }
                    )

            # 11. Worker Type & TDS
            wt_raw = _get_val(
                row,
                "worker_type",
                "workerType",
                "Worker Type",
                "Worker Type (Salaried/Professional/Contractor)",
            )
            norm_wt = "Salaried"
            if wt_raw:
                w = wt_raw.strip().lower()
                if "prof" in w or "consult" in w or "retain" in w or "194j" in w:
                    norm_wt = "Professional"
                elif "contract" in w or "194c" in w or "vendor" in w:
                    norm_wt = "Contractor"
                elif "salar" in w or "192" in w or "normal" in w:
                    norm_wt = "Salaried"

            tds_app_raw = _get_val(
                row,
                "tds_applicable",
                "tdsApplicable",
                "TDS Applicable",
                "TDS Applicable (True/False)",
            )
            if norm_wt in ("Professional", "Contractor"):
                tds_applicable = (
                    True if not tds_app_raw else _parse_bool(tds_app_raw, default=True)
                )
            else:
                tds_applicable = _parse_bool(tds_app_raw, default=False)

            default_sec = (
                "194J_10"
                if norm_wt == "Professional"
                else ("194C_1" if norm_wt == "Contractor" else "192")
            )
            tds_section = (
                _get_val(row, "tds_section", "tdsSection", "TDS Section") or default_sec
            )
            default_rate = (
                10.0
                if norm_wt == "Professional"
                else (1.0 if norm_wt == "Contractor" else 0.0)
            )
            tds_rate = _parse_float(
                _get_val(row, "tds_rate", "tdsRate", "TDS Rate", "TDS Rate (%)"),
                default=default_rate,
            )

            # 12. PF & Statutory
            pf_applicable = _parse_bool(
                _get_val(
                    row,
                    "pf_applicable",
                    "pfApplicable",
                    "PF Applicable",
                    "PF Applicable (True/False)",
                ),
                default=False,
            )
            pan = _get_val(row, "pan", "PAN")
            aadhaar = _get_val(row, "aadhaar", "Aadhaar")
            uan = _get_val(row, "uan", "UAN")
            esi = _get_val(row, "esi", "esi_no", "esiNo", "ESI No.", "ESI")
            bank_name = _get_val(row, "bank_name", "bankName", "Bank Name")
            bank_account = _get_val(
                row, "bank_account", "bankAccount", "Bank Account No.", "Bank Account"
            )
            ifsc = _get_val(row, "ifsc", "IFSC Code", "IFSC")
            address = _get_val(row, "address", "Address")
            status_val = _get_val(row, "status", "Status") or "Active"

            is_valid = len(row_errors) == 0
            if not is_valid:
                total_error_count += 1
                for err in row_errors:
                    errors_summary.append(
                        f"Row {idx} ({code or 'No Code'}): {err['message']}"
                    )

            parsed_rows.append(
                {
                    "row_index": idx,
                    "is_valid": is_valid,
                    "errors": row_errors,
                    "raw_data": row,
                    "parsed_data": {
                        "first_name": first_name,
                        "last_name": last_name,
                        "code": code,
                        "email": email or "",
                        "phone": phone or "",
                        "gender": norm_gender or gender_raw,
                        "dob": dob_parsed,
                        "doj": doj_parsed,
                        "status": status_val,
                        "entity_id": ent.id if ent else None,
                        "entity_name": ent.name if ent else (entity_val or ""),
                        "organization_id": org.id if org else None,
                        "department_id": dept.id if dept else None,
                        "department_name": dept.name if dept else (dept_val or ""),
                        "designation_id": desg.id if desg else None,
                        "designation_name": desg.title if desg else (desg_val or ""),
                        "branch_id": branch.id if branch else None,
                        "branch_name": branch.name if branch else (branch_val or ""),
                        "site_id": site.id if site else None,
                        "site_name": site.name if site else (site_val or ""),
                        "manager_id": manager.id if manager else None,
                        "manager_code": manager.code if manager else (mgr_val or ""),
                        "worker_type": norm_wt,
                        "tds_applicable": tds_applicable,
                        "tds_section": tds_section,
                        "tds_rate": tds_rate,
                        "pf_applicable": pf_applicable,
                        "pan": pan,
                        "aadhaar": aadhaar,
                        "uan": uan,
                        "esi": esi,
                        "bank_name": bank_name,
                        "bank_account": bank_account,
                        "ifsc": ifsc,
                        "address": address,
                    },
                }
            )

        return {
            "is_valid": total_error_count == 0,
            "total_rows": len(parsed_rows),
            "valid_count": len(parsed_rows) - total_error_count,
            "error_count": total_error_count,
            "errors_summary": errors_summary,
            "rows": parsed_rows,
        }

    @action(
        detail=False,
        methods=["POST"],
        parser_classes=[
            CamelCaseMultiPartParser,
            CamelCaseFormParser,
            CamelCaseJSONParser,
        ],
        url_path="validate_import",
    )
    def validate_import(self, request):
        """
        Validates uploaded employee master data without committing.
        Returns detailed per-row and summary errors, enabling in-place preview corrections.
        """
        raw_rows = self._extract_raw_rows(request)
        if not raw_rows:
            return Response(
                {
                    "detail": "No employee records found in payload.",
                    "is_valid": False,
                    "total_rows": 0,
                    "valid_count": 0,
                    "error_count": 1,
                    "errors_summary": [
                        "No data rows detected. Please upload a populated CSV or JSON rows."
                    ],
                    "rows": [],
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        summary = self._parse_and_validate_rows(raw_rows, request.user)
        return Response(summary, status=status.HTTP_200_OK)

    @action(
        detail=False,
        methods=["POST"],
        parser_classes=[
            CamelCaseMultiPartParser,
            CamelCaseFormParser,
            CamelCaseJSONParser,
        ],
        url_path="bulk_import",
    )
    def bulk_import(self, request):
        """
        Strict bulk import for employee master data.
        PREVENTS UPLOAD completely if any row has missing mandatory info or validation errors.
        Only commits when 100% of rows are valid, in an atomic transaction.
        Sets initial password to '123' per organizational rule.
        """
        from django.db import transaction
        from organisation.models import Entity, Department, Designation, Branch, Site
        from employees.models import EmployeeAuditLog

        raw_rows = self._extract_raw_rows(request)
        if not raw_rows:
            return Response(
                {"detail": "No file or employee records provided."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        summary = self._parse_and_validate_rows(raw_rows, request.user)

        # STRICT ENFORCEMENT: Block entire upload if ANY row has errors
        if summary["error_count"] > 0:
            return Response(
                {
                    "detail": f"Upload prevented: {summary['error_count']} record(s) contain missing mandatory information or validation errors. Please resolve all errors before importing.",
                    "is_valid": False,
                    "total_rows": summary["total_rows"],
                    "valid_count": summary["valid_count"],
                    "error_count": summary["error_count"],
                    "errors_summary": summary["errors_summary"],
                    "rows": summary["rows"],
                },
                status=status.HTTP_400_BAD_REQUEST,
            )

        created_employees = []
        try:
            with transaction.atomic():
                for row_info in summary["rows"]:
                    data = row_info["parsed_data"]

                    first_name = data["first_name"]
                    last_name = data["last_name"]
                    email = data["email"] or None
                    phone = data["phone"] or None
                    code = data["code"]
                    clean_phone = "".join(
                        c for c in (phone or "") if c.isdigit() or c == "+"
                    )

                    # Determine unique username: prefer email, then clean phone, then code
                    username = email if email else (clean_phone or code)

                    # Create User with password '123' (User standing rule)
                    user = User.objects.create_user(
                        username=username,
                        email=email or "",
                        password="123",
                        first_name=first_name,
                        last_name=last_name,
                        is_active=(data["status"] == "Active"),
                    )

                    # Resolve Foreign Keys
                    ent = (
                        Entity.objects.filter(id=data["entity_id"]).first()
                        if data.get("entity_id")
                        else None
                    )
                    org = ent.organization if ent else None
                    dept = (
                        Department.objects.filter(id=data["department_id"]).first()
                        if data.get("department_id")
                        else None
                    )
                    desg = (
                        Designation.objects.filter(id=data["designation_id"]).first()
                        if data.get("designation_id")
                        else None
                    )
                    branch = (
                        Branch.objects.filter(id=data["branch_id"]).first()
                        if data.get("branch_id")
                        else None
                    )
                    site = (
                        Site.objects.filter(id=data["site_id"]).first()
                        if data.get("site_id")
                        else None
                    )
                    manager = (
                        Employee.objects.filter(id=data["manager_id"]).first()
                        if data.get("manager_id")
                        else None
                    )

                    emp = Employee.objects.create(
                        user=user,
                        code=code,
                        first_name=first_name,
                        last_name=last_name,
                        email=email,
                        phone=phone,
                        gender=data["gender"] or "Male",
                        dob=data["dob"],
                        doj=data["doj"],
                        status=data["status"] or "Active",
                        organization=org,
                        entity=ent,
                        department=dept,
                        designation=desg,
                        branch=branch,
                        site=site,
                        manager=manager,
                        worker_type=data["worker_type"],
                        tds_applicable=data["tds_applicable"],
                        tds_section=data["tds_section"],
                        tds_rate=data["tds_rate"],
                        pf_applicable=data["pf_applicable"],
                        pan=data["pan"],
                        aadhaar=data["aadhaar"],
                        uan=data["uan"],
                        esi=data["esi"],
                        bank_name=data["bank_name"],
                        bank_account=data["bank_account"],
                        ifsc=data["ifsc"],
                        address=data["address"],
                    )

                    # Auto-enroll in site for attendance kiosk/GPS if assigned
                    if site:
                        emp.enrolled_sites.add(site)

                    # Initialize default leave balances for current calendar year
                    try:
                        from leaves.models import LeaveType, LeaveBalance
                        from datetime import date
                        from decimal import Decimal

                        current_year = date.today().year
                        for lt in LeaveType.objects.filter(active=True):
                            ent = lt.annual_entitlement or Decimal("0.00")
                            LeaveBalance.objects.get_or_create(
                                employee=emp,
                                leave_type=lt,
                                year=current_year,
                                defaults={
                                    "allocated_days": ent,
                                    "used_days": Decimal("0.00"),
                                    "remaining_days": ent,
                                },
                            )
                    except Exception:
                        pass

                    # Org Engine Node Sync
                    try:
                        from org_engine.models import (
                            OrganizationNode,
                            OrganizationNodeType,
                        )

                        if emp.dynamic_role:
                            emp_type, _ = OrganizationNodeType.objects.get_or_create(
                                name="Employee"
                            )
                            parent_node = OrganizationNode.objects.filter(
                                name=emp.dynamic_role.name, node_type__name="Role"
                            ).first()
                            if parent_node:
                                OrganizationNode.objects.create(
                                    name=f"{first_name} {last_name}",
                                    node_type=emp_type,
                                    parent=parent_node,
                                    tenant_id=org.id if org else 1,
                                )
                    except Exception as ex:
                        pass

                    # Audit Log
                    try:
                        EmployeeAuditLog.objects.create(
                            employee=emp,
                            performed_by=f"{request.user.username} ({request.user.get_full_name() or request.user.username})",
                            action="BULK_IMPORT",
                            changes={
                                "code": emp.code,
                                "email": emp.email,
                                "worker_type": emp.worker_type,
                                "entity": ent.name if ent else None,
                            },
                        )
                    except Exception as ex:
                        pass

                    created_employees.append(emp)

            return Response(
                {
                    "success": True,
                    "count": len(created_employees),
                    "message": f"Successfully imported {len(created_employees)} employee(s).",
                },
                status=status.HTTP_201_CREATED,
            )
        except Exception as e:
            return Response(
                {"detail": f"Failed to import employees: {str(e)}"},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

    @action(detail=False, methods=["GET"], url_path="template")
    def template(self, request):
        """
        Returns a downloadable CSV template with clear mandatory (*) indicators and sample rows.
        """
        from django.http import HttpResponse

        response = HttpResponse(content_type="text/csv; charset=utf-8")
        response["Content-Disposition"] = (
            'attachment; filename="Employee_Master_Data_Template.csv"'
        )

        writer = csv.writer(response)
        headers = [
            "First Name*",
            "Last Name*",
            "Employee Code*",
            "Email*",
            "Phone",
            "Gender*",
            "Date of Joining* (DD-MM-YYYY)",
            "Entity*",
            "Date of Birth (DD-MM-YYYY)",
            "Department",
            "Designation",
            "Branch",
            "Site",
            "Reporting Manager (Code or Email)",
            "Worker Type (Salaried/Professional/Contractor)",
            "PAN",
            "TDS Applicable (True/False)",
            "TDS Section",
            "TDS Rate (%)",
            "PF Applicable (True/False)",
            "Aadhaar",
            "UAN",
            "ESI No.",
            "Bank Name",
            "Bank Account No.",
            "IFSC Code",
            "Address",
            "Status",
        ]
        writer.writerow(headers)

        caller_emp = getattr(request.user, "employee_profile", None)
        ent_name = (
            caller_emp.entity.name
            if (caller_emp and caller_emp.entity)
            else "Main Entity"
        )

        sample_row_1 = [
            "Aarav",
            "Sharma",
            "EMP2001",
            "aarav.sharma@example.com",
            "9876543210",
            "Male",
            "01-04-2024",
            ent_name,
            "15-08-1992",
            "Engineering",
            "Software Engineer",
            "Headquarters",
            "Main Office",
            "None",
            "Salaried",
            "ABCDE1234F",
            "False",
            "192",
            "0.00",
            "True",
            "123456789012",
            "100000000000",
            "ESI123456",
            "HDFC Bank",
            "50100234567890",
            "HDFC0001234",
            "123 Tech Park, Bangalore",
            "Active",
        ]
        sample_row_2 = [
            "Priya",
            "Verma",
            "CON3001",
            "priya.verma@example.com",
            "9811223344",
            "Female",
            "15-05-2024",
            ent_name,
            "22-11-1988",
            "Legal",
            "Legal Consultant",
            "Headquarters",
            "Main Office",
            "EMP2001",
            "Professional",
            "XYZPK5678L",
            "True",
            "194J_10",
            "10.00",
            "False",
            "987654321098",
            "",
            "",
            "ICICI Bank",
            "001101234567",
            "ICIC0000011",
            "456 Tower B, Mumbai",
            "Active",
        ]
        writer.writerow(sample_row_1)
        writer.writerow(sample_row_2)
        return response

    @action(
        detail=True,
        methods=["POST"],
        parser_classes=[CamelCaseMultiPartParser, CamelCaseFormParser],
    )
    def update_photo(self, request, pk=None):
        """
        Updates an employee's profile photo with strict site-level data isolation.
        Automatically syncs and extracts facial embeddings into FaceProfile for tablet kiosk attendance.
        """
        employee = (
            self.get_object()
        )  # DataIsolationMixin ensures employee belongs to the isolated scope
        req_user = request.user

        # Strict Multi-Tenant Site Isolation Validation
        if not req_user.is_superuser:
            from authentication.permissions import _get_admin_sites

            admin_sites = _get_admin_sites(req_user)
            if admin_sites.exists():
                is_authorized = (
                    employee.site and employee.site in admin_sites
                ) or employee.enrolled_sites.filter(id__in=admin_sites).exists()
                if not is_authorized:
                    raise exceptions.PermissionDenied(
                        "Data Isolation Violation: You can only update photos for employees in your assigned site."
                    )
            if employee.role in ["super_admin", "org_admin"]:
                raise exceptions.PermissionDenied(
                    "Access Denied: You cannot modify photos of corporate administrators."
                )

        photo_file = request.FILES.get("photo")
        if not photo_file:
            return Response(
                {"error": "No photo file provided."}, status=status.HTTP_400_BAD_REQUEST
            )

        # Save photo
        employee.photo = photo_file
        employee.save(update_fields=["photo"])

        # Auto-extract biometric encoding for tablet kiosk matching
        biometric_enrolled = False
        try:
            from attendance.utils import get_face_encoding
            from attendance.models import FaceProfile
            from attendance.crypto_utils import CryptoService

            photo_file.seek(0)
            img_bytes = photo_file.read()
            encoding_res = get_face_encoding(img_bytes)

            if encoding_res.get("success"):
                encoding = encoding_res.get("encoding")
                face_profile, _ = FaceProfile.objects.get_or_create(employee=employee)
                payload = {"encodings": [encoding]}
                enc_data, enc_dek = CryptoService.encrypt_json(payload)
                face_profile.encrypted_face_encodings = enc_data
                face_profile.encrypted_dek = enc_dek
                face_profile.is_active = True
                face_profile.save()
                biometric_enrolled = True

                try:
                    from attendance.faiss_service import biometric_search

                    biometric_search.add_employee_vectors(employee.id, [encoding])
                except Exception as fe:
                    print(f"FAISS vector sync notice: {fe}")
        except Exception as be:
            print(f"Biometric sync notice: {be}")

        serializer = self.get_serializer(employee)
        data = dict(serializer.data)
        data["biometric_enrolled"] = biometric_enrolled
        return Response(data, status=status.HTTP_200_OK)

    def perform_create(self, serializer):
        req_user = self.request.user
        validated_data = serializer.validated_data
        raw_data = self.request.data

        from authentication.permissions import is_ceo_user

        if not is_ceo_user(req_user):
            validated_data.pop("ctc", None)
            validated_data.pop("tax_saving_deductions", None)
            validated_data.pop("salary_structure", None)

        # 1. Site Isolation Enforcement
        if req_user and req_user.is_authenticated and not req_user.is_superuser:
            admin_profile = getattr(req_user, "employee_profile", None)
            if admin_profile:
                if admin_profile.role == "site_admin":
                    # Force site matching
                    if not admin_profile.site:
                        raise exceptions.PermissionDenied(
                            "You are a site admin without a designated site."
                        )
                    validated_data["site"] = admin_profile.site

        import secrets
        import string

        status_val = validated_data.get("status", "Active")

        email = validated_data.get("email")
        first_name = validated_data.get("first_name", "")
        last_name = validated_data.get("last_name", "")

        if not validated_data.get("code"):
            import random

            validated_data["code"] = f"EMP-{random.randint(10000, 99999)}"
            while Employee.objects.filter(code=validated_data["code"]).exists():
                validated_data["code"] = f"EMP-{random.randint(10000, 99999)}"

        # If saving as draft, skip User creation and Email
        if status_val == "Draft":
            employee = serializer.save(user=None)
            return

        # Generate a random 10-character password
        alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
        password = raw_data.get("password") or "".join(
            secrets.choice(alphabet) for _ in range(10)
        )

        phone = validated_data.get("phone")

        # Determine username and account identifier (Phone-first for blue-collar or Email)
        if email:
            username = email.strip()
            if (
                User.objects.filter(username=username).exists()
                or User.objects.filter(email=username).exists()
            ):
                raise exceptions.ValidationError(
                    {"email": "A user with this email already exists."}
                )
        elif phone:
            clean_phone = "".join(c for c in phone if c.isdigit() or c == "+")
            username = clean_phone or validated_data.get("code")
            if User.objects.filter(username=username).exists():
                raise exceptions.ValidationError(
                    {"phone": "A user account with this phone number already exists."}
                )
        else:
            raise exceptions.ValidationError(
                {
                    "non_field_errors": [
                        "Either an Email or a Phone number is required to create a user account."
                    ]
                }
            )

        # 3. Create Django User
        is_active = status_val == "Active"
        user = User.objects.create_user(
            username=username,
            email=email or "",
            password=password,
            first_name=first_name,
            last_name=last_name,
            is_active=is_active,
        )

        # 4. Save Employee with linked user
        employee = serializer.save(user=user)

        # 4.0 Add Create Audit Log
        try:
            from .models import EmployeeAuditLog

            performed_by = (
                req_user.username
                if req_user and req_user.is_authenticated
                else "System"
            )
            EmployeeAuditLog.objects.create(
                employee=employee,
                action="Create",
                performed_by=performed_by,
                changes={"all": "Initial creation of record."},
            )
        except Exception as e:
            print(f"Failed to create audit log: {e}")

        # 4.1 Generate Offer Letter
        from .models import OfferLetter
        import uuid

        offer_num = f"OFF-{employee.code or str(uuid.uuid4())[:8].upper()}"
        OfferLetter.objects.create(
            employee=employee, offer_number=offer_num, status="Pending Approval"
        )

        # 5. Dispatch Welcome Credentials (SMS for phone-only, Email, or Both)
        send_email_flag = raw_data.get("send_email", False)
        send_sms_flag = raw_data.get("send_sms", False)
        send_credentials_flag = raw_data.get("send_credentials", False)
        delivery_method = raw_data.get("delivery_method", "auto")

        should_dispatch = any(
            str(x).lower() in ["true", "1"]
            for x in [send_email_flag, send_sms_flag, send_credentials_flag]
        )
        if should_dispatch:
            from core.notifications import NotificationService

            if str(send_sms_flag).lower() in ["true", "1"] and str(
                send_email_flag
            ).lower() not in ["true", "1"]:
                delivery_method = "sms"
            elif str(send_email_flag).lower() in ["true", "1"] and str(
                send_sms_flag
            ).lower() not in ["true", "1"]:
                delivery_method = "email"
            NotificationService.send_credentials(
                employee, password, delivery_method=delivery_method
            )

        # 6. Sync with Organization Engine
        try:
            from org_engine.models import OrganizationNode, OrganizationNodeType

            emp_type, _ = OrganizationNodeType.objects.get_or_create(name="Employee")
            emp_name = f"{first_name} {last_name}"

            # Determine parent node based on assigned role
            parent_node = None
            if employee.dynamic_role:
                parent_node = OrganizationNode.objects.filter(
                    name=employee.dynamic_role.name, node_type__name="Role"
                ).first()
                if parent_node:
                    emp_node = OrganizationNode.objects.create(
                        name=emp_name,
                        node_type=emp_type,
                        parent=parent_node,
                        tenant_id=1,
                    )
        except Exception as e:
            print(f"Failed to create Org Engine node for employee: {e}")

        # 7. CTC Notification Workflow
        from authentication.permissions import coerce_permission_bool

        creator_profile = getattr(req_user, "employee_profile", None)
        creator_has_ctc = req_user.is_superuser or (
            creator_profile
            and creator_profile.dynamic_role
            and creator_profile.dynamic_role.permissions
            and coerce_permission_bool(
                creator_profile.dynamic_role.permissions.get("can_add_ctc")
            )
        )

        if (not employee.ctc or employee.ctc == 0) and not creator_has_ctc:
            from .models import Notification

            # Find all users with can_add_ctc or superusers
            superusers = User.objects.filter(is_superuser=True)
            for su in superusers:
                if hasattr(su, "employee_profile"):
                    Notification.objects.create(
                        recipient=su.employee_profile,
                        title=f"New Employee Onboarded: {emp_name}",
                        message=f"Please add their CTC, PF, and Bonus credentials.",
                        related_employee_id=employee.id,
                    )

            # Find roles with can_add_ctc
            from organisation.models import Role

            ctc_roles = [
                r
                for r in Role.objects.all()
                if r.permissions
                and coerce_permission_bool(r.permissions.get("can_add_ctc"))
            ]
            ctc_employees = Employee.objects.filter(dynamic_role__in=ctc_roles)
            for ctc_emp in ctc_employees:
                Notification.objects.create(
                    recipient=ctc_emp,
                    title=f"New Employee Onboarded: {emp_name}",
                    message=f"Please add their CTC, PF, and Bonus credentials.",
                    related_employee_id=employee.id,
                )

    def update(self, request, *args, **kwargs):
        try:
            with open("update_debug.log", "w") as f:
                f.write(f"REQUEST DATA: {json.dumps(request.data)}\n")
        except:
            pass
        return super().update(request, *args, **kwargs)

    def perform_update(self, serializer):
        try:
            with open("update_debug.log", "a") as f:
                f.write(f"VALIDATED DATA: {serializer.validated_data}\n")
        except:
            pass

        validated_data = serializer.validated_data

        from authentication.permissions import is_ceo_user

        if not is_ceo_user(self.request.user):
            validated_data.pop("ctc", None)
            validated_data.pop("tax_saving_deductions", None)
            validated_data.pop("salary_structure", None)

        # Prevent wiping out the employee code during update
        if "code" in validated_data and not validated_data["code"]:
            validated_data.pop("code")

        old_status = serializer.instance.status
        new_status = validated_data.get("status", old_status)

        old_first = serializer.instance.first_name
        old_last = serializer.instance.last_name
        old_name = f"{old_first} {old_last}"
        old_role = serializer.instance.dynamic_role

        # Calculate diff before saving
        changes = {}
        for attr, new_val in validated_data.items():
            old_val = getattr(serializer.instance, attr, None)
            if old_val != new_val:
                if attr == "designation":
                    old_name = (
                        old_val.title
                        if hasattr(old_val, "title")
                        else str(old_val or "None")
                    )
                    new_name = (
                        new_val.title
                        if hasattr(new_val, "title")
                        else str(new_val or "None")
                    )
                    changes["designation"] = {"old": old_name, "new": new_name}
                elif attr == "dynamic_role":
                    old_name = (
                        old_val.name
                        if hasattr(old_val, "name")
                        else str(old_val or "None")
                    )
                    new_name = (
                        new_val.name
                        if hasattr(new_val, "name")
                        else str(new_val or "None")
                    )
                    changes["role"] = {"old": old_name, "new": new_name}
                elif attr == "department":
                    old_name = (
                        old_val.name
                        if hasattr(old_val, "name")
                        else str(old_val or "None")
                    )
                    new_name = (
                        new_val.name
                        if hasattr(new_val, "name")
                        else str(new_val or "None")
                    )
                    changes["department"] = {"old": old_name, "new": new_name}
                elif attr in ["site", "branch", "entity"]:
                    old_name = (
                        old_val.name
                        if hasattr(old_val, "name")
                        else str(old_val or "None")
                    )
                    new_name = (
                        new_val.name
                        if hasattr(new_val, "name")
                        else str(new_val or "None")
                    )
                    changes[attr] = {"old": old_name, "new": new_name}
                else:
                    changes[attr] = {"old": str(old_val), "new": str(new_val)}

        emp = serializer.save()
        if not emp.user and emp.email:
            matched_user = (
                User.objects.filter(email__iexact=emp.email).first()
                or User.objects.filter(username__iexact=emp.email).first()
            )
            if matched_user:
                emp.user = matched_user
                emp.save(update_fields=["user"])
        elif not emp.user and emp.code:
            matched_user = User.objects.filter(username__iexact=emp.code).first()
            if matched_user:
                emp.user = matched_user
                emp.save(update_fields=["user"])

        # Strict security boundary: only a user with is_superuser can ever have role 'super_admin'
        if emp.role == "super_admin" and not (emp.user and emp.user.is_superuser):
            emp.role = "employee"
            emp.save(update_fields=["role"])

        if emp.user:
            is_active = emp.status == "Active"
            if emp.user.is_active != is_active:
                emp.user.is_active = is_active
                emp.user.save(update_fields=["is_active"])

        if changes:
            try:
                from .models import EmployeeAuditLog

                req_user = self.request.user
                performed_by = (
                    req_user.username
                    if req_user and req_user.is_authenticated
                    else "System"
                )
                EmployeeAuditLog.objects.create(
                    employee=emp,
                    action="Update",
                    performed_by=performed_by,
                    changes=changes,
                )
            except Exception as e:
                print(f"Failed to create audit log for update: {e}")
        new_name = f"{emp.first_name} {emp.last_name}"

        # Draft to Active Transition
        if old_status == "Draft" and new_status == "Active" and not emp.user:
            email = emp.email
            from django.contrib.auth.models import User

            if email and not User.objects.filter(username=email).exists():
                import secrets
                import string
                import threading
                from django.core.mail import send_mail
                from django.conf import settings

                alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
                password = "".join(secrets.choice(alphabet) for _ in range(10))

                user = User.objects.create_user(
                    username=email,
                    email=email,
                    password=password,
                    first_name=emp.first_name,
                    last_name=emp.last_name,
                )
                emp.user = user
                emp.save(update_fields=["user"])

                login_url = getattr(
                    settings, "HRMS_PORTAL_URL", "http://127.0.0.1:8000"
                )
                brand = getattr(emp.organization, "branding_text", None) or (
                    emp.organization.name
                    if emp.organization
                    else getattr(settings, "APP_NAME", "HRMS Management")
                )
                subject = f"Welcome to {brand} - Your Login Credentials"
                message = f"Hello {emp.first_name},\n\nWelcome to {brand}! Your account has been successfully created.\n\nWebsite: {login_url}\nLogin ID: {email}\nPassword: {password}\n\nPlease log in and change your password immediately.\n\nRegards,\n{brand} Administration"
                try:
                    sender = (
                        getattr(settings, "DEFAULT_FROM_EMAIL", None)
                        or getattr(settings, "EMAIL_HOST_USER", None)
                        or "noreply@hrms.local"
                    )
                    threading.Thread(
                        target=send_mail,
                        args=(subject, message, sender, [email]),
                        kwargs={"fail_silently": True},
                    ).start()
                except:
                    pass

                # Generate Offer Letter
                from .models import OfferLetter
                import uuid

                offer_num = f"OFF-{emp.code or str(uuid.uuid4())[:8].upper()}"
                OfferLetter.objects.create(
                    employee=emp, offer_number=offer_num, status="Pending Approval"
                )

        try:
            from org_engine.models import OrganizationNode
            from org_engine.engine import HierarchyEngine

            emp_node = OrganizationNode.objects.filter(
                name=old_name, node_type__name="Employee"
            ).first()
            if emp_node:
                if old_name != new_name:
                    emp_node.name = new_name
                    emp_node.save(update_fields=["name"])

                # If role changed
                if old_role != emp.dynamic_role:
                    if emp.dynamic_role:
                        new_parent_node = OrganizationNode.objects.filter(
                            name=emp.dynamic_role.name, node_type__name="Role"
                        ).first()
                        if new_parent_node and emp_node.parent_id != new_parent_node.id:
                            HierarchyEngine.move_node(emp_node, new_parent_node)
                    else:
                        # Role was removed, so remove them from the tree
                        emp_node.delete()
            else:
                # Node didn't exist, create it ONLY if they have a role
                if emp.dynamic_role:
                    from org_engine.models import OrganizationNodeType

                    emp_type, _ = OrganizationNodeType.objects.get_or_create(
                        name="Employee"
                    )

                    new_parent_node = OrganizationNode.objects.filter(
                        name=emp.dynamic_role.name, node_type__name="Role"
                    ).first()

                    if new_parent_node:
                        OrganizationNode.objects.create(
                            name=new_name,
                            node_type=emp_type,
                            parent=new_parent_node,
                            tenant_id=1,
                        )
        except Exception as e:
            print(f"Failed to sync org engine graph update: {e}")

    def perform_destroy(self, instance):
        try:
            from org_engine.models import OrganizationNode

            emp_name = f"{instance.first_name} {instance.last_name}"
            emp_node = OrganizationNode.objects.filter(
                name=emp_name, node_type__name="Employee"
            ).first()
            if emp_node:
                emp_node.delete()
        except Exception as e:
            print(f"Failed to sync org engine graph deletion: {e}")
        instance.delete()

    @action(detail=False, methods=["POST"], url_path="trigger_onboarding_emails")
    def trigger_onboarding_emails(self, request):
        employee_ids = request.data.get("employee_ids", [])
        if not employee_ids:
            return Response(
                {"error": "No employees selected."}, status=status.HTTP_400_BAD_REQUEST
            )

        employees = isolate_queryset(Employee.objects.all(), request.user).filter(
            id__in=employee_ids
        )
        sent_count = 0
        import secrets
        import string
        from django.core.mail import send_mail
        from django.conf import settings
        import threading

        alphabet = string.ascii_letters + string.digits + "!@#$%^&*"

        for emp in employees:
            if emp.user:
                new_password = "".join(secrets.choice(alphabet) for _ in range(10))
                emp.user.set_password(new_password)
                emp.user.save()

                dispatched = False
                try:
                    from core.notifications import NotificationService

                    res = NotificationService.send_credentials(
                        emp, new_password, delivery_method="auto"
                    )
                    if res.get("email_sent") or res.get("sms_sent"):
                        sent_count += 1
                        dispatched = True
                except Exception as e:
                    print(f"NotificationService failed for {emp.id}: {e}")

                if not dispatched and emp.email:
                    login_url = getattr(
                        settings, "HRMS_PORTAL_URL", "http://127.0.0.1:8000"
                    )
                    brand = getattr(emp.organization, "branding_text", None) or (
                        emp.organization.name
                        if emp.organization
                        else getattr(settings, "APP_NAME", "HRMS Management")
                    )
                    subject = f"Welcome to {brand} - Your Login Credentials"
                    message = f"""Hello {emp.first_name},

Welcome to {brand}! Your account is ready.

Website: {login_url}
Login ID: {emp.email}
Password: {new_password}

Please log in and change your password immediately.

Regards,
{brand} Administration
"""
                    try:
                        threading.Thread(
                            target=send_mail,
                            args=(
                                subject,
                                message,
                                settings.DEFAULT_FROM_EMAIL,
                                [emp.email],
                            ),
                            kwargs={"fail_silently": True},
                        ).start()
                        sent_count += 1
                    except Exception as e:
                        print(f"Failed to send email to {emp.email}: {e}")

        return Response({"success": True, "sent_count": sent_count})

    @action(detail=True, methods=["get"])
    def audit_logs(self, request, pk=None):
        employee = self.get_object()
        logs = employee.audit_logs.all().order_by("-timestamp")
        data = []
        for log in logs:
            data.append(
                {
                    "id": log.id,
                    "action": log.action,
                    "performed_by": log.performed_by,
                    "changes": log.changes,
                    "timestamp": log.timestamp.isoformat(),
                }
            )
        return Response(data)

    @action(detail=True, methods=["POST"], url_path="reset_credentials")
    def reset_credentials(self, request, pk=None):
        target_employee = self.get_object()

        # Dynamic permission check: NOT hardcoded to static 'admin' or 'hr' strings
        from authentication.permissions import isolate_queryset, check_module_permission

        caller_accessible = isolate_queryset(
            Employee.objects.all(), request.user
        ).filter(id=target_employee.id)
        if not caller_accessible.exists():
            return Response(
                {
                    "error": "You do not have permission to manage credentials for this employee."
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        caller_emp = getattr(request.user, "employee_profile", None)
        has_perm = False

        if request.user.is_superuser:
            has_perm = True
        elif caller_emp:
            dynamic_role = getattr(caller_emp, "dynamic_role", None)
            if dynamic_role:
                if dynamic_role.access_scope in ("Corporate", "Region"):
                    has_perm = True
                elif dynamic_role.can_manage_users:
                    has_perm = True
                elif check_module_permission(request.user, "Employees", "update"):
                    has_perm = True

        if not has_perm:
            return Response(
                {
                    "error": "Your role does not grant entity-level management rights to reset passwords."
                },
                status=status.HTTP_403_FORBIDDEN,
            )

        password_mode = request.data.get("password_mode") or request.data.get(
            "passwordMode", "auto"
        )
        custom_password = (
            request.data.get("custom_password")
            or request.data.get("customPassword")
            or ""
        ).strip()
        send_email_val = request.data.get("send_email")
        if send_email_val is None:
            send_email_val = request.data.get("sendEmail", True)
        if isinstance(send_email_val, str):
            send_email = send_email_val.lower() in ("true", "1")
        else:
            send_email = bool(send_email_val)

        send_sms_val = request.data.get("send_sms")
        if send_sms_val is None:
            send_sms_val = request.data.get("sendSms", True)
        if isinstance(send_sms_val, str):
            send_sms = send_sms_val.lower() in ("true", "1")
        else:
            send_sms = bool(send_sms_val)

        import secrets
        import string

        if password_mode == "custom" and custom_password:
            new_password = custom_password
        else:
            alphabet = string.ascii_letters + string.digits + "!@#$%^&*"
            new_password = "".join(secrets.choice(alphabet) for _ in range(12))

        from django.contrib.auth.models import User

        user = target_employee.user
        target_email = target_employee.email or (user.email if user else None)
        if not target_email and user and "@" in user.username:
            target_email = user.username

        if not user:
            if not target_email:
                domain = getattr(settings, "INTERNAL_EMAIL_DOMAIN", "hrms.local")
                target_email = f"{target_employee.code.lower()}@{domain}"
            user = User.objects.filter(username=target_email).first()
            if not user and target_employee.code:
                user = User.objects.filter(username=target_employee.code).first()
            if not user:
                user = User.objects.create_user(
                    username=target_email,
                    email=target_email,
                    first_name=target_employee.first_name,
                    last_name=target_employee.last_name,
                )
            target_employee.user = user
            target_employee.save(update_fields=["user"])

        if target_email:
            if not target_employee.email:
                target_employee.email = target_email
                target_employee.save(update_fields=["email"])
            if not user.email:
                user.email = target_email
                user.save(update_fields=["email"])

        user.set_password(new_password)
        user.save()

        try:
            from .models import EmployeeAuditLog

            performed_by = (
                request.user.username
                if request.user and request.user.is_authenticated
                else "System"
            )
            EmployeeAuditLog.objects.create(
                employee=target_employee,
                action="Password Reset",
                performed_by=performed_by,
                changes={
                    "credentials": {
                        "old": "[Protected]",
                        "new": f"Password reset by {performed_by}",
                    }
                },
            )
        except Exception as e:
            print(f"Failed to log password reset: {e}")

        email_sent = False
        if send_email and target_email and "@" in target_email:
            from django.core.mail import send_mail
            from django.conf import settings
            import threading

            origin = request.headers.get("Origin") or request.build_absolute_uri("/")
            login_url = origin.rstrip("/") + "/auth"
            subject = "Your HRMS Login Credentials Have Been Updated"
            message = f"""Hello {target_employee.first_name},

Your password for the HRMS portal has been updated.

Portal URL: {login_url}
Login ID: {target_email}
Password: {new_password}

Please log in and update your password if desired.

Regards,
HR Operations
"""
            try:

                def _send():
                    try:
                        from_email = getattr(
                            settings, "DEFAULT_FROM_EMAIL", None
                        ) or getattr(
                            settings, "EMAIL_HOST_USER", "noreply@vibecopilot.ai"
                        )
                        send_mail(
                            subject,
                            message,
                            from_email,
                            [target_email],
                            fail_silently=False,
                        )
                    except Exception as err:
                        print(
                            f"[Password Reset Email Error] Could not send to {target_email}: {err}"
                        )

                threading.Thread(target=_send, daemon=True).start()
                email_sent = True
            except Exception as e:
                print(f"Failed to start password email thread: {e}")

        sms_sent = False
        target_phone = target_employee.phone or ""
        if send_sms and target_phone:
            import threading
            from core.jio_sms import JioSMSService

            origin = request.headers.get("Origin") or request.build_absolute_uri("/")
            login_url = origin.rstrip("/") + "/auth"
            login_id = target_email or target_employee.code or target_phone

            def _send_sms():
                try:
                    JioSMSService.send_credentials_sms(
                        phone=target_phone,
                        first_name=target_employee.first_name,
                        login_id=login_id,
                        password=new_password,
                        login_url=login_url,
                    )
                except Exception as err:
                    print(f"[Password Reset SMS Error] {err}")

            threading.Thread(target=_send_sms, daemon=True).start()
            sms_sent = True

        status_msg_parts = []
        if email_sent:
            status_msg_parts.append(f"email to {target_email}")
        if sms_sent:
            status_msg_parts.append(f"SMS to {target_phone}")
        status_msg = (
            f"Credentials sent via {', '.join(status_msg_parts)}."
            if status_msg_parts
            else "Password updated successfully."
        )

        return Response(
            {
                "success": True,
                "email_sent": email_sent,
                "emailSent": email_sent,
                "sms_sent": sms_sent,
                "smsSent": sms_sent,
                "recipient": target_email,
                "recipient_phone": target_phone,
                "generated_password": (
                    new_password if password_mode != "custom" else None
                ),
                "generatedPassword": (
                    new_password if password_mode != "custom" else None
                ),
                "message": status_msg,
            }
        )

    @action(detail=True, methods=["get"], url_path="salary-revisions")
    def salary_revisions(self, request, pk=None):
        employee = self.get_object()
        from .models import CompensationHistory
        from .serializers import CompensationHistorySerializer

        revisions = CompensationHistory.objects.filter(employee=employee).order_by(
            "-effective_from", "-created_at"
        )
        serializer = CompensationHistorySerializer(revisions, many=True)
        return Response(serializer.data)

    @action(detail=True, methods=["post"], url_path="revise-salary")
    def revise_salary(self, request, pk=None):
        employee = self.get_object()
        from django.db import transaction
        from django.utils import timezone
        import datetime
        from decimal import Decimal
        from .models import CompensationHistory
        from .serializers import CompensationHistorySerializer
        from payroll.models import SalaryStructure
        from authentication.permissions import is_ceo_user

        if not (
            request.user.is_superuser
            or is_ceo_user(request.user)
            or request.user.has_perm("employees.change_employee")
        ):
            return Response(
                {
                    "error": "Permission denied: Only authorized administrators or executives can revise compensation."
                },
                status=403,
            )

        new_ctc = request.data.get("new_ctc")
        if not new_ctc or int(new_ctc) <= 0:
            return Response(
                {"error": "A valid positive new CTC amount is required."}, status=400
            )
        new_ctc = int(new_ctc)

        effective_from_str = request.data.get("effective_from")
        if not effective_from_str:
            return Response({"error": "Effective from date is required."}, status=400)

        try:
            effective_from = datetime.datetime.strptime(
                effective_from_str, "%Y-%m-%d"
            ).date()
        except ValueError:
            return Response(
                {"error": "Invalid date format for effective_from. Use YYYY-MM-DD."},
                status=400,
            )

        revision_type = request.data.get("revision_type", "Annual Appraisal")
        reason = request.data.get("reason", "")
        notes = request.data.get("notes", "")

        structure_id = request.data.get("salary_structure_id")
        target_structure = None
        if structure_id:
            target_structure = SalaryStructure.objects.filter(id=structure_id).first()
        if not target_structure:
            target_structure = (
                employee.salary_structure
                or SalaryStructure.objects.filter(status="Active").first()
            )

        if not target_structure:
            return Response(
                {
                    "error": "No valid salary structure found to attach to this revision."
                },
                status=400,
            )

        with transaction.atomic():
            old_ctc = int(employee.ctc or 0)
            hike_pct = Decimal("0.00")
            if old_ctc > 0:
                hike_pct = (
                    (Decimal(str(new_ctc)) - Decimal(str(old_ctc)))
                    / Decimal(str(old_ctc))
                    * Decimal("100.0")
                ).quantize(Decimal("0.01"))

            prev_active = CompensationHistory.objects.filter(
                employee=employee, effective_to__isnull=True
            ).first()
            if prev_active:
                prev_active.effective_to = effective_from - datetime.timedelta(days=1)
                prev_active.save(update_fields=["effective_to"])

            new_record = CompensationHistory.objects.create(
                employee=employee,
                previous_ctc=old_ctc,
                ctc=new_ctc,
                hike_percentage=hike_pct,
                revision_type=revision_type,
                salary_structure=target_structure,
                effective_from=effective_from,
                effective_to=None,
                reason=reason,
                notes=notes,
                changed_by=request.user,
            )

            employee.ctc = new_ctc
            employee.salary_structure = target_structure
            employee.save(update_fields=["ctc", "salary_structure", "updated_at"])

            today = timezone.now().date()
            first_day_current_month = today.replace(day=1)
            is_retroactive = effective_from < first_day_current_month

            return Response(
                {
                    "message": "Salary revision recorded successfully.",
                    "revision": CompensationHistorySerializer(new_record).data,
                    "is_retroactive": is_retroactive,
                    "retro_notice": (
                        f"Backdated hike from {effective_from}. Arrears will be calculated in the next payroll run."
                        if is_retroactive
                        else None
                    ),
                    "employee": {
                        "id": employee.id,
                        "code": employee.code,
                        "name": f"{employee.first_name} {employee.last_name}",
                        "current_ctc": employee.ctc,
                        "salary_structure_id": target_structure.id,
                        "salary_structure_name": target_structure.name,
                    },
                }
            )

    @action(
        detail=True, methods=["patch", "put", "post"], url_path="update-profile-details"
    )
    def update_profile_details(self, request, pk=None):
        """
        Allows an employee to edit their bank, statutory, and related details.
        Enforces one-time edit lock: If profile_edit_unlocked is False, prevents editing
        and requires manager approval. Once saved, automatically locks the profile.
        """
        employee = self.get_object()
        user = request.user
        current_emp = getattr(user, "employee_profile", None)

        is_admin_or_super = user.is_superuser or (
            current_emp
            and current_emp.role in ["super_admin", "org_admin", "admin", "site_admin"]
        )

        # If not admin/super, enforce ownership and lock check
        if not is_admin_or_super:
            if current_emp and current_emp.id != employee.id:
                return Response(
                    {
                        "error": "You do not have permission to edit another employee's profile details."
                    },
                    status=403,
                )
            if not employee.profile_edit_unlocked:
                return Response(
                    {
                        "error": "Profile details are locked. Please submit a request to your manager to unlock editing.",
                        "profile_edit_unlocked": False,
                        "profile_unlock_requested": employee.profile_unlock_requested,
                    },
                    status=400,
                )

        data = request.data
        allowed_fields = [
            "bank_name",
            "bank_account",
            "ifsc",
            "pan",
            "aadhaar",
            "uan",
            "esi",
            "phone",
            "emergency_contact",
            "present_address",
            "permanent_address",
        ]

        for f in allowed_fields:
            if f in data:
                setattr(employee, f, data[f])

        # Lock profile if regular employee
        if not is_admin_or_super:
            employee.profile_edit_unlocked = False
            employee.profile_edit_count += 1
            employee.profile_unlock_requested = False
            employee.profile_unlock_reason = None

        employee.save()

        # Audit & notifications
        from .models import Notification

        manager = employee.manager
        if manager and manager != employee:
            Notification.objects.create(
                recipient=manager,
                title=f"Profile Details Updated: {employee.first_name} {employee.last_name}",
                message=f"{employee.first_name} {employee.last_name} ({employee.code}) has updated their bank/statutory details. Profile is now locked.",
                notification_type="PROFILE_UPDATED",
                related_employee_id=employee.id,
            )

        Notification.objects.create(
            recipient=employee,
            title="Profile Details Saved & Locked",
            message="Your bank and statutory details have been saved successfully. Further edits will require manager approval.",
            notification_type="PROFILE_LOCKED",
            related_employee_id=employee.id,
        )

        return Response(
            {
                "message": "Profile details updated and locked successfully.",
                "profile_edit_unlocked": employee.profile_edit_unlocked,
                "profile_edit_count": employee.profile_edit_count,
                "employee": EmployeeSerializer(employee).data,
            }
        )

    @action(detail=True, methods=["post"], url_path="request-profile-unlock")
    def request_profile_unlock(self, request, pk=None):
        """
        Employee requests their reporting manager (or admin) to unlock their profile for editing.
        Sends notification to manager with actionable buttons in notification bar.
        """
        employee = self.get_object()
        user = request.user
        current_emp = getattr(user, "employee_profile", None)

        if current_emp and current_emp.id != employee.id and not user.is_superuser:
            return Response(
                {"error": "You can only request unlock for your own profile."},
                status=403,
            )

        reason = (
            request.data.get("reason", "").strip()
            or "Employee requested permission to update bank/statutory details or upload documents."
        )

        from django.utils import timezone
        from .models import Notification

        employee.profile_unlock_requested = True
        employee.profile_unlock_requested_at = timezone.now()
        employee.profile_unlock_reason = reason
        employee.save(
            update_fields=[
                "profile_unlock_requested",
                "profile_unlock_requested_at",
                "profile_unlock_reason",
            ]
        )

        # Determine manager to notify
        manager = employee.manager
        if not manager:
            # Fallback to site admin or any admin
            manager = Employee.objects.filter(
                site=employee.site, role__in=["site_admin", "admin"]
            ).first()
        if not manager:
            manager = (
                Employee.objects.filter(role__in=["admin", "super_admin"])
                .exclude(id=employee.id)
                .first()
            )

        if manager:
            Notification.objects.create(
                recipient=manager,
                title=f"Profile Edit Request: {employee.first_name} {employee.last_name}",
                message=f"{employee.first_name} {employee.last_name} ({employee.code}) requested profile edit unlock. Reason: {reason}",
                notification_type="PROFILE_UNLOCK_REQUEST",
                related_employee_id=employee.id,
            )

        Notification.objects.create(
            recipient=employee,
            title="Profile Unlock Request Sent",
            message=f"Your edit request has been sent to your manager ({manager.first_name if manager else 'Management'}). You will be notified once approved.",
            notification_type="PROFILE_UNLOCK_PENDING",
            related_employee_id=employee.id,
        )

        return Response(
            {
                "message": "Profile unlock request submitted to your manager.",
                "profile_unlock_requested": True,
                "manager_name": (
                    f"{manager.first_name} {manager.last_name}" if manager else None
                ),
            }
        )

    @action(detail=True, methods=["post"], url_path="approve-profile-unlock")
    def approve_profile_unlock(self, request, pk=None):
        """
        Manager or admin approves profile unlock request directly from notification bar or profile.
        """
        employee = self.get_object()
        user = request.user
        current_emp = getattr(user, "employee_profile", None)

        is_manager = current_emp and (employee.manager_id == current_emp.id)
        is_admin_or_super = user.is_superuser or (
            current_emp
            and current_emp.role in ["super_admin", "org_admin", "admin", "site_admin"]
        )

        if not (is_manager or is_admin_or_super):
            return Response(
                {
                    "error": "Only the reporting manager or administrator can approve profile unlocks."
                },
                status=403,
            )

        from .models import Notification

        employee.profile_edit_unlocked = True
        employee.profile_unlock_requested = False
        employee.profile_unlock_reason = None
        employee.save(
            update_fields=[
                "profile_edit_unlocked",
                "profile_unlock_requested",
                "profile_unlock_reason",
            ]
        )

        # Mark manager's notification as read
        if current_emp:
            Notification.objects.filter(
                recipient=current_emp,
                related_employee_id=employee.id,
                notification_type="PROFILE_UNLOCK_REQUEST",
            ).update(is_read=True)

        # Notify employee
        Notification.objects.create(
            recipient=employee,
            title="Profile Edit Request Approved",
            message=f"Your manager ({current_emp.first_name if current_emp else 'Admin'}) approved your profile edit request. You can now update your bank, statutory, and document details.",
            notification_type="PROFILE_UNLOCKED",
            related_employee_id=employee.id,
        )

        return Response(
            {
                "message": f"Profile unlocked successfully for {employee.first_name} {employee.last_name}.",
                "profile_edit_unlocked": True,
                "profile_unlock_requested": False,
            }
        )

    @action(detail=True, methods=["post"], url_path="reject-profile-unlock")
    def reject_profile_unlock(self, request, pk=None):
        """
        Manager or admin rejects profile unlock request.
        """
        employee = self.get_object()
        user = request.user
        current_emp = getattr(user, "employee_profile", None)

        is_manager = current_emp and (employee.manager_id == current_emp.id)
        is_admin_or_super = user.is_superuser or (
            current_emp
            and current_emp.role in ["super_admin", "org_admin", "admin", "site_admin"]
        )

        if not (is_manager or is_admin_or_super):
            return Response(
                {
                    "error": "Only the reporting manager or administrator can reject profile unlocks."
                },
                status=403,
            )

        reason = (
            request.data.get("reason", "").strip()
            or "Manager did not approve edit request."
        )
        from .models import Notification

        employee.profile_unlock_requested = False
        employee.profile_unlock_reason = None
        employee.save(
            update_fields=["profile_unlock_requested", "profile_unlock_reason"]
        )

        # Mark manager's notification as read
        if current_emp:
            Notification.objects.filter(
                recipient=current_emp,
                related_employee_id=employee.id,
                notification_type="PROFILE_UNLOCK_REQUEST",
            ).update(is_read=True)

        # Notify employee
        Notification.objects.create(
            recipient=employee,
            title="Profile Edit Request Rejected",
            message=f"Your edit request was declined by your manager ({current_emp.first_name if current_emp else 'Admin'}). Reason: {reason}",
            notification_type="PROFILE_UNLOCK_REJECTED",
            related_employee_id=employee.id,
        )

        return Response(
            {
                "message": f"Profile unlock request rejected for {employee.first_name} {employee.last_name}.",
                "profile_unlock_requested": False,
            }
        )


from .models import EmployeeDocument, EmployeeTransfer, EmployeeExit
from .serializers import (
    EmployeeDocumentSerializer,
    EmployeeTransferSerializer,
    EmployeeExitSerializer,
)


class EmployeeDocumentViewSet(DataIsolationMixin, viewsets.ModelViewSet):
    rbac_module = "Documents"
    queryset = EmployeeDocument.objects.all()
    serializer_class = EmployeeDocumentSerializer
    parser_classes = [
        CamelCaseMultiPartParser,
        CamelCaseFormParser,
        CamelCaseJSONParser,
    ]

    def get_queryset(self):
        queryset = super().get_queryset()
        employee_id = self.request.query_params.get("employee")
        if employee_id:
            queryset = queryset.filter(employee_id=employee_id)
        return queryset

    def create(self, request, *args, **kwargs):
        user = request.user
        emp_id = request.data.get("employee")
        current_emp = getattr(user, "employee_profile", None)

        # If user is a normal employee (not admin/super_admin)
        if (
            current_emp
            and current_emp.role
            not in ["super_admin", "org_admin", "admin", "site_admin"]
            and not user.is_superuser
        ):
            target_emp = (
                Employee.objects.filter(id=emp_id).first() if emp_id else current_emp
            )
            if target_emp and not target_emp.profile_edit_unlocked:
                return Response(
                    {
                        "detail": "Document uploading is locked. Please request manager approval to upload new documents."
                    },
                    status=status.HTTP_403_FORBIDDEN,
                )
        return super().create(request, *args, **kwargs)

    def destroy(self, request, *args, **kwargs):
        user = request.user
        current_emp = getattr(user, "employee_profile", None)
        doc = self.get_object()
        if (
            current_emp
            and current_emp.role
            not in ["super_admin", "org_admin", "admin", "site_admin"]
            and not user.is_superuser
        ):
            if doc.employee and not doc.employee.profile_edit_unlocked:
                return Response(
                    {
                        "detail": "Document modification is locked. Please request manager approval."
                    },
                    status=status.HTTP_403_FORBIDDEN,
                )
        return super().destroy(request, *args, **kwargs)


class EmployeeTransferViewSet(DataIsolationMixin, viewsets.ModelViewSet):
    rbac_module = "Employees"
    queryset = EmployeeTransfer.objects.all()
    serializer_class = EmployeeTransferSerializer

    def perform_update(self, serializer):
        transfer = serializer.save()
        # Auto-apply transfer if status changes to Executed
        if transfer.status == "Executed":
            emp = transfer.employee
            if transfer.new_department:
                emp.department = transfer.new_department
            if transfer.new_designation:
                emp.designation = transfer.new_designation
            if transfer.new_site:
                emp.site = transfer.new_site
            if transfer.new_manager:
                emp.manager = transfer.new_manager
            emp.save()


class EmployeeExitViewSet(DataIsolationMixin, viewsets.ModelViewSet):
    rbac_module = "Manage Exits"
    queryset = EmployeeExit.objects.all()
    serializer_class = EmployeeExitSerializer

    def create(self, request, *args, **kwargs):
        emp_id = request.data.get("employee")
        if emp_id:
            existing = EmployeeExit.objects.filter(employee_id=emp_id).first()
            if existing:
                serializer = self.get_serializer(
                    existing, data=request.data, partial=True
                )
                serializer.is_valid(raise_exception=True)
                self.perform_create(serializer)
                return Response(serializer.data, status=status.HTTP_200_OK)
        return super().create(request, *args, **kwargs)

    def perform_create(self, serializer):
        exit_process = serializer.save()
        emp = exit_process.employee

        # Link selected reporting person / manager if provided
        reporting_person_id = self.request.data.get(
            "reporting_person"
        ) or self.request.data.get("manager")
        if reporting_person_id:
            try:
                reporting_emp = Employee.objects.get(id=reporting_person_id)
                if emp.manager != reporting_emp:
                    emp.manager = reporting_emp
                    emp.save(update_fields=["manager"])
            except Exception:
                pass

        # Send notification to the designated reporting manager
        target_manager = emp.manager
        if target_manager:
            from .models import Notification

            Notification.objects.create(
                recipient=target_manager,
                title="Separation Request Received",
                message=f"{emp.first_name} {emp.last_name} ({emp.code}) has submitted a separation request. LWD: {exit_process.last_working_day}.",
                related_employee_id=emp.id,
            )

    def perform_update(self, serializer):
        exit_process = serializer.save()
        if exit_process.status == "Completed":
            emp = exit_process.employee
            emp.status = "Exited"
            emp.save(update_fields=["status"])
            if emp.user:
                emp.user.is_active = False
                emp.user.save(update_fields=["is_active"])

    @action(detail=True, methods=["post"], url_path="clearance")
    def update_clearance(self, request, pk=None):
        from django.utils import timezone

        exit_process = self.get_object()
        department = request.data.get("department")  # "manager", "it", "finance", "hr"
        cleared = request.data.get("cleared", True)
        remarks = request.data.get("remarks", "")

        if department not in ["manager", "it", "finance", "hr"]:
            return Response(
                {"error": "Invalid department. Must be manager, it, finance, or hr."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        clearance_remarks = exit_process.clearance_remarks or {}
        clearance_remarks[department] = {
            "cleared": bool(cleared),
            "remarks": str(remarks),
            "cleared_by": request.user.username,
            "cleared_at": str(timezone.now()),
        }
        exit_process.clearance_remarks = clearance_remarks

        if department == "manager":
            exit_process.manager_approved = bool(cleared)
        elif department == "it":
            exit_process.it_cleared = bool(cleared)
        elif department == "finance":
            exit_process.finance_cleared = bool(cleared)
        elif department == "hr":
            exit_process.hr_cleared = bool(cleared)

        # Check if all clearances are satisfied
        if (
            exit_process.manager_approved
            and exit_process.it_cleared
            and exit_process.finance_cleared
            and exit_process.hr_cleared
        ):
            if exit_process.status in ["Pending", "In Progress"]:
                exit_process.status = "Approved"

        exit_process.save()
        return Response(self.get_serializer(exit_process).data)

    @action(detail=True, methods=["get", "post"], url_path="fnf-settlement")
    def fnf_settlement(self, request, pk=None):
        from decimal import Decimal
        from django.utils import timezone
        from payroll.models import Loan, SalaryAdvance

        exit_process = self.get_object()
        emp = exit_process.employee

        monthly_ctc = Decimal(str(emp.ctc or 0)) / Decimal("12.0")
        daily_rate = (monthly_ctc / Decimal("30.0")).quantize(Decimal("0.01"))

        lwd = exit_process.last_working_day
        worked_days = lwd.day if lwd else 0
        unpaid_salary = (daily_rate * Decimal(str(worked_days))).quantize(
            Decimal("0.01")
        )

        active_loans = Loan.objects.filter(employee=emp, status="Active")
        outstanding_loan = sum((l.outstanding for l in active_loans), Decimal("0.00"))

        active_advances = SalaryAdvance.objects.filter(employee=emp, status="Disbursed")
        outstanding_advance = sum(
            (a.outstanding for a in active_advances), Decimal("0.00")
        )

        resignation_date = exit_process.resignation_date
        actual_notice_days = (
            (lwd - resignation_date).days
            if (lwd and resignation_date)
            else exit_process.notice_period_days
        )
        shortfall_days = max(0, exit_process.notice_period_days - actual_notice_days)
        shortfall_deduction = (daily_rate * Decimal(str(shortfall_days))).quantize(
            Decimal("0.01")
        )

        total_earnings = unpaid_salary
        total_deductions = (
            outstanding_loan + outstanding_advance + shortfall_deduction
        ).quantize(Decimal("0.01"))
        net_payable = (total_earnings - total_deductions).quantize(Decimal("0.01"))

        calculated_statement = {
            "employee_id": emp.id,
            "employee_name": f"{emp.first_name} {emp.last_name}",
            "employee_code": emp.code,
            "annual_ctc": float(emp.ctc or 0),
            "monthly_ctc": float(monthly_ctc.quantize(Decimal("0.01"))),
            "daily_rate": float(daily_rate),
            "last_working_day": str(lwd),
            "worked_days_in_exit_month": worked_days,
            "unpaid_salary": float(unpaid_salary),
            "outstanding_loan_recovery": float(outstanding_loan),
            "outstanding_advance_recovery": float(outstanding_advance),
            "notice_period_days": exit_process.notice_period_days,
            "shortfall_days": shortfall_days,
            "shortfall_deduction": float(shortfall_deduction),
            "total_earnings": float(total_earnings),
            "total_deductions": float(total_deductions),
            "net_fnf_payable": float(net_payable),
        }

        if request.method == "GET":
            return Response(
                {
                    "exit_id": exit_process.id,
                    "fnf_status": exit_process.fnf_status,
                    "fnf_statement": exit_process.fnf_statement or calculated_statement,
                    "preview": calculated_statement,
                }
            )

        waive_shortfall = request.data.get("waive_shortfall", False)
        remarks = request.data.get("remarks", "")
        if waive_shortfall:
            total_deductions = (outstanding_loan + outstanding_advance).quantize(
                Decimal("0.01")
            )
            net_payable = (total_earnings - total_deductions).quantize(Decimal("0.01"))
            calculated_statement["shortfall_days"] = 0
            calculated_statement["shortfall_deduction"] = 0.0
            calculated_statement["total_deductions"] = float(total_deductions)
            calculated_statement["net_fnf_payable"] = float(net_payable)
            calculated_statement["shortfall_waived"] = True

        calculated_statement["settled_by"] = request.user.username
        calculated_statement["settlement_remarks"] = remarks
        calculated_statement["settled_at"] = str(timezone.now())

        exit_process.fnf_status = "Settled"
        exit_process.fnf_statement = calculated_statement
        exit_process.settled_at = timezone.now()
        exit_process.status = "Completed"
        exit_process.save()

        emp.status = "Exited"
        emp.save(update_fields=["status"])
        if emp.user:
            emp.user.is_active = False
            emp.user.save(update_fields=["is_active"])

        for l in active_loans:
            l.outstanding = Decimal("0.00")
            l.status = "Closed"
            l.save(update_fields=["outstanding", "status"])
        for a in active_advances:
            a.outstanding = Decimal("0.00")
            a.status = "Recovered"
            a.save(update_fields=["outstanding", "status"])

        return Response(
            {
                "message": "Full & Final settlement successfully executed. Employee marked Exited and user account deactivated.",
                "exit": self.get_serializer(exit_process).data,
                "fnf_statement": calculated_statement,
            }
        )


class WorkspaceNotificationView(APIView):
    permission_classes = [AllowAny]

    def get(self, request):
        return Response([])


class NotificationViewSet(viewsets.ViewSet):
    permission_classes = [IsAuthenticated]

    def list(self, request):
        user = request.user
        from .models import Notification
        from announcements.models import Announcement

        emp = getattr(user, "employee_profile", None)
        if not emp:
            if user.email:
                emp = Employee.objects.filter(email__iexact=user.email).first()
            if not emp and user.username:
                emp = Employee.objects.filter(code__iexact=user.username).first()

        # Backfill notifications for any active announcements that this user/employee is targeted for
        active_announcements = Announcement.objects.filter(is_active=True)
        for a in active_announcements:
            is_target = False
            if a.created_by == user:
                is_target = True
            elif a.audience_type == "EVERYONE":
                if not a.entity or (emp and a.entity == emp.entity):
                    is_target = True
            elif (
                emp
                and a.audience_type == "ROLE"
                and emp.dynamic_role_id
                and hasattr(a, "target_roles")
                and a.target_roles.filter(id=emp.dynamic_role_id).exists()
            ):
                is_target = True
            elif (
                emp
                and a.audience_type == "DEPARTMENT"
                and emp.department
                and a.target_departments.filter(id=emp.department_id).exists()
            ):
                is_target = True
            elif (
                emp
                and a.audience_type == "INDIVIDUAL"
                and a.target_employees.filter(id=emp.id).exists()
            ):
                is_target = True

            if is_target and emp:
                notif_title = f"Announcement: {a.title}"
                if not Notification.objects.filter(
                    recipient=emp, title=notif_title
                ).exists():
                    Notification.objects.create(
                        recipient=emp,
                        title=notif_title,
                        message=a.content[:180],
                        is_read=False,
                    )

        if emp:
            notifs = Notification.objects.filter(recipient=emp, is_read=False).order_by(
                "-created_at"
            )
        else:
            return Response([])

        data = []
        for n in notifs:
            data.append(
                {
                    "id": n.id,
                    "title": n.title,
                    "message": n.message,
                    "notification_type": getattr(n, "notification_type", None),
                    "related_run_id": n.related_run_id,
                    "related_employee_id": n.related_employee_id,
                    "created_at": n.created_at.isoformat(),
                }
            )
        return Response(data)

    @action(detail=True, methods=["post"])
    def mark_read(self, request, pk=None):
        from .models import Notification

        try:
            emp = getattr(request.user, "employee_profile", None)
            if emp:
                n = Notification.objects.get(pk=pk, recipient=emp)
            else:
                n = Notification.objects.get(pk=pk)
            n.is_read = True
            n.save()
            return Response({"status": "success"})
        except Notification.DoesNotExist:
            return Response({"error": "Not found"}, status=404)


from .models import OfferLetter, OfferTemplate
from .serializers import OfferLetterSerializer, OfferTemplateSerializer


class OfferTemplateViewSet(DataIsolationMixin, viewsets.ModelViewSet):
    rbac_module = "Offer Templates"
    queryset = OfferTemplate.objects.all()
    serializer_class = OfferTemplateSerializer
    permission_classes = [IsAuthenticated]
    parser_classes = [
        CamelCaseMultiPartParser,
        CamelCaseFormParser,
        CamelCaseJSONParser,
    ]


class OfferLetterViewSet(DataIsolationMixin, viewsets.ModelViewSet):
    rbac_module = "Offer Letters"
    queryset = OfferLetter.objects.all().order_by("-created_at")
    serializer_class = OfferLetterSerializer
    permission_classes = [IsAuthenticated]

    @action(detail=False, methods=["get"])
    def dashboard_metrics(self, request):
        from django.db.models import Count

        # Use get_queryset() to enforce DataIsolationMixin RBAC instead of unfiltered self.queryset
        metrics = self.get_queryset().values("status").annotate(count=Count("status"))
        metrics_dict = {m["status"]: m["count"] for m in metrics}

        # Default all statuses to 0
        all_statuses = dict(OfferLetter.STATUS_CHOICES)
        final_metrics = {k: metrics_dict.get(k, 0) for k in all_statuses.keys()}

        from datetime import date
        from django.db.models.functions import Coalesce

        today = date.today()
        upcoming_qs = (
            self.get_queryset()
            .annotate(effective_joining_date=Coalesce("joining_date", "employee__doj"))
            .filter(
                status__in=["Pending Approval", "Awaiting Acceptance", "Accepted"],
                effective_joining_date__gte=today,
            )
            .order_by("effective_joining_date")[:5]
        )

        upcoming = OfferLetterSerializer(upcoming_qs, many=True).data

        recent_qs = self.get_queryset().order_by("-created_at")[:5]
        recent = OfferLetterSerializer(recent_qs, many=True).data

        return Response(
            {"metrics": final_metrics, "upcoming": upcoming, "recent": recent}
        )

    def _render_offer_html(self, employee, template_id, request_user=None):
        from .models import OfferTemplate
        import re
        import datetime
        from django.conf import settings

        template = OfferTemplate.objects.get(id=template_id)
        body = template.body_html or ""

        # Safe access to related fields
        first_name = employee.first_name or ""
        last_name = employee.last_name or ""
        candidate_name = f"{first_name} {last_name}".strip()

        designation = "Employee"
        if employee.designation:
            designation = employee.designation.title

        entity_name = "Our Company"
        if employee.site and employee.site.branch and employee.site.branch.entity:
            entity_name = employee.site.branch.entity.name

        # Additional Safe Access
        department = employee.department.name if employee.department else "N/A"
        reporting_manager = (
            f"{employee.manager.first_name} {employee.manager.last_name}".strip()
            if employee.manager
            else "N/A"
        )
        employment_type = employee.employee_type or "Full Time"
        work_location = employee.site.name if employee.site else "N/A"
        joining_date = employee.doj.strftime("%Y-%m-%d") if employee.doj else "TBD"
        employee_id = employee.code or "TBD"

        # CTC Calculations (50% Basic, 25% HRA, 25% Special Allowance)
        ctc_annual = float(employee.ctc or 0)
        ctc_monthly = round(ctc_annual / 12, 2)

        variable_annual = float(employee.bonus_value or 0)
        fixed_annual = (
            ctc_annual - variable_annual if ctc_annual > variable_annual else ctc_annual
        )
        fixed_monthly = round(fixed_annual / 12, 2)

        basic_annual = round(fixed_annual * 0.50, 2)
        basic_monthly = round(fixed_monthly * 0.50, 2)
        hra_annual = round(fixed_annual * 0.25, 2)
        hra_monthly = round(fixed_monthly * 0.25, 2)
        special_annual = fixed_annual - basic_annual - hra_annual
        special_monthly = fixed_monthly - basic_monthly - hra_monthly

        # Deductions (Default estimates)
        professional_tax_monthly = 200.00 if fixed_monthly > 15000 else 0.00
        provident_fund_monthly = 0.00
        esi_monthly = 0.00
        tds_monthly = 0.00

        total_deductions_monthly = (
            professional_tax_monthly
            + provident_fund_monthly
            + esi_monthly
            + tds_monthly
        )
        net_pay_monthly = fixed_monthly - total_deductions_monthly

        professional_tax_annual = professional_tax_monthly * 12
        provident_fund_annual = provident_fund_monthly * 12
        esi_annual = esi_monthly * 12
        tds_annual = tds_monthly * 12
        total_deductions_annual = total_deductions_monthly * 12
        net_pay_annual = net_pay_monthly * 12

        # Simple Number to Words fallback
        try:
            # You can install num2words in the future: from num2words import num2words
            net_pay_in_words = f"{int(net_pay_monthly)} Rupees Only"
        except:
            net_pay_in_words = f"{net_pay_monthly} Rupees Only"

        acceptance_deadline = (
            datetime.datetime.now() + datetime.timedelta(days=7)
        ).strftime("%Y-%m-%d")

        # Dynamic HR Details
        hr_name = "HR Department"
        hr_designation = "Human Resources"
        hr_email = (
            getattr(settings, "DEFAULT_FROM_EMAIL", None)
            or getattr(settings, "EMAIL_HOST_USER", None)
            or ""
        )
        hr_contact = getattr(settings, "COMPANY_CONTACT_PHONE", "N/A")

        if request_user and request_user.is_authenticated:
            hr_name = (
                f"{request_user.first_name} {request_user.last_name}".strip()
                or request_user.username
            )
            hr_email = request_user.email or hr_email
            if (
                hasattr(request_user, "employee_profile")
                and request_user.employee_profile
            ):
                if request_user.employee_profile.designation:
                    hr_designation = request_user.employee_profile.designation.title
                if request_user.employee_profile.phone:
                    hr_contact = request_user.employee_profile.phone

        # Comprehensive placeholder replacement
        replacements = {
            "{{companyName}}": entity_name,
            "{{entity_name}}": entity_name,
            "{{currentDate}}": datetime.datetime.now().strftime("%Y-%m-%d"),
            "{{issue_date}}": datetime.datetime.now().strftime("%Y-%m-%d"),
            "{{candidateName}}": candidate_name,
            "{{candidate_name}}": candidate_name,
            "{{candidateAddress}}": employee.address or "Address on file",
            "{{candidate_address}}": employee.address or "Address on file",
            "{{designation}}": designation,
            "{{department}}": department,
            "{{employmentType}}": employment_type,
            "{{employment_type}}": employment_type,
            "{{workLocation}}": work_location,
            "{{work_location}}": work_location,
            "{{joiningDate}}": joining_date,
            "{{joining_date}}": joining_date,
            "{{reportingManager}}": reporting_manager,
            "{{reporting_manager}}": reporting_manager,
            "{{probationPeriod}}": "6 months",
            "{{probation_period}}": "6 months",
            "{{workingHours}}": "9:00 AM to 6:00 PM",
            "{{working_hours}}": "9:00 AM to 6:00 PM",
            "{{employee_id}}": employee_id,
            "{{working_days}}": "Monday to Friday",
            # CTC Details
            "{{totalCtcAnnual}}": f"{ctc_annual:,.2f}",
            "{{ctc}}": f"{ctc_annual:,.2f}",
            "{{totalCtcMonthly}}": f"{ctc_monthly:,.2f}",
            "{{monthly_gross}}": f"{ctc_monthly:,.2f}",
            "{{totalFixedAnnual}}": f"{fixed_annual:,.2f}",
            "{{total_fixed_annual}}": f"{fixed_annual:,.2f}",
            "{{totalFixedMonthly}}": f"{fixed_monthly:,.2f}",
            "{{total_fixed_monthly}}": f"{fixed_monthly:,.2f}",
            "{{basicSalaryAnnual}}": f"{basic_annual:,.2f}",
            "{{basic_salary_annual}}": f"{basic_annual:,.2f}",
            "{{basicSalaryMonthly}}": f"{basic_monthly:,.2f}",
            "{{basic_salary_monthly}}": f"{basic_monthly:,.2f}",
            "{{hraAnnual}}": f"{hra_annual:,.2f}",
            "{{hra_annual}}": f"{hra_annual:,.2f}",
            "{{hraMonthly}}": f"{hra_monthly:,.2f}",
            "{{hra_monthly}}": f"{hra_monthly:,.2f}",
            "{{specialAllowanceAnnual}}": f"{special_annual:,.2f}",
            "{{special_allowance_annual}}": f"{special_annual:,.2f}",
            "{{specialAllowanceMonthly}}": f"{special_monthly:,.2f}",
            "{{special_allowance_monthly}}": f"{special_monthly:,.2f}",
            "{{variableAnnual}}": f"{variable_annual:,.2f}",
            "{{variable_pay}}": f"{variable_annual:,.2f}",
            "{{bonus}}": f"{variable_annual:,.2f}",
            # Deductions Details
            "{{professionalTaxMonthly}}": f"{professional_tax_monthly:,.2f}",
            "{{professional_tax_monthly}}": f"{professional_tax_monthly:,.2f}",
            "{{professionalTaxAnnual}}": f"{professional_tax_annual:,.2f}",
            "{{professional_tax_annual}}": f"{professional_tax_annual:,.2f}",
            "{{providentFundMonthly}}": f"{provident_fund_monthly:,.2f}",
            "{{provident_fund_monthly}}": f"{provident_fund_monthly:,.2f}",
            "{{providentFundAnnual}}": f"{provident_fund_annual:,.2f}",
            "{{provident_fund_annual}}": f"{provident_fund_annual:,.2f}",
            "{{esiMonthly}}": f"{esi_monthly:,.2f}",
            "{{esi_monthly}}": f"{esi_monthly:,.2f}",
            "{{esiAnnual}}": f"{esi_annual:,.2f}",
            "{{esi_annual}}": f"{esi_annual:,.2f}",
            "{{tdsMonthly}}": f"{tds_monthly:,.2f}",
            "{{tds_monthly}}": f"{tds_monthly:,.2f}",
            "{{tdsAnnual}}": f"{tds_annual:,.2f}",
            "{{tds_annual}}": f"{tds_annual:,.2f}",
            "{{totalDeductionsMonthly}}": f"{total_deductions_monthly:,.2f}",
            "{{total_deductions_monthly}}": f"{total_deductions_monthly:,.2f}",
            "{{totalDeductionsAnnual}}": f"{total_deductions_annual:,.2f}",
            "{{total_deductions_annual}}": f"{total_deductions_annual:,.2f}",
            "{{netPayMonthly}}": f"{net_pay_monthly:,.2f}",
            "{{net_payable_monthly}}": f"{net_pay_monthly:,.2f}",
            "{{netPayAnnual}}": f"{net_pay_annual:,.2f}",
            "{{net_payable_annual}}": f"{net_pay_annual:,.2f}",
            "{{netPayInWords}}": net_pay_in_words,
            # HR Details
            "{{acceptanceDueDate}}": acceptance_deadline,
            "{{acceptance_deadline}}": acceptance_deadline,
            "{{hrManagerName}}": hr_name,
            "{{hr_name}}": hr_name,
            "{{hrDesignation}}": hr_designation,
            "{{hr_designation}}": hr_designation,
            "{{hrEmail}}": hr_email,
            "{{hrContact}}": hr_contact,
        }

        for key, val in replacements.items():
            body = body.replace(key, str(val))

        # If any placeholders remain unresolved, highlight them (user requested black text)
        body = re.sub(
            r"\{\{[^}]+\}\}",
            '<span style="color: black; font-weight: bold;">[Data Missing]</span>',
            body,
        )

        # (Removed aggressive table regex replacements to preserve custom HTML layouts)
        # Clean up doctype to avoid nested wrapping issues
        body = re.sub(r"<!DOCTYPE[^>]*>", "", body, flags=re.IGNORECASE).strip()

        # Determine dynamic header and footer
        if template.header_html:
            header_content = f'<div id="header_content">{template.header_html}</div>'
        else:
            header_content = '<div id="header_content"></div>'

        if template.footer_html:
            footer_content = f'<div id="footer_content">{template.footer_html}</div>'
        else:
            footer_content = '<div id="footer_content"></div>'

        # Fix page breaks for xhtml2pdf (robust regex for any tag with page-break-before/after: always)
        # First, handle self-closing tags like <hr>
        body = re.sub(
            r"<hr[^>]*?page-break-[^>]*?>",
            "<pdf:nextpage />",
            body,
            flags=re.IGNORECASE,
        )
        # Handle empty divs used for page breaks
        body = re.sub(
            r"<div[^>]*?page-break-[^>]*?>\s*</div>",
            "<pdf:nextpage />",
            body,
            flags=re.IGNORECASE,
        )
        # Handle <p> tags with page break
        body = re.sub(
            r"<p[^>]*?page-break-[^>]*?>\s*</p>",
            "<pdf:nextpage />",
            body,
            flags=re.IGNORECASE,
        )

        # Clean up consecutive or trailing page breaks to prevent blank pages
        body = re.sub(
            r"(<pdf:nextpage />\s*)+", "<pdf:nextpage />", body, flags=re.IGNORECASE
        )
        body = re.sub(r"<pdf:nextpage />\s*$", "", body, flags=re.IGNORECASE)

        # Wrap in HTML skeleton with basic styles for PDF/Email compatibility
        if not body.lower().startswith("<html"):
            body = f"""
            <html>
            <head>
                <meta charset="UTF-8">
                <style>
                    @page {{
                        size: a4 portrait;
                        margin-top: 80pt;
                        margin-bottom: 80pt;
                        margin-left: 50pt;
                        margin-right: 50pt;
                        @frame header_frame {{
                            -pdf-frame-content: header_content;
                            left: 30pt; width: 535pt; top: 15pt; height: 65pt;
                        }}
                        @frame footer_frame {{
                            -pdf-frame-content: footer_content;
                            left: 30pt; width: 535pt; bottom: 15pt; height: 65pt;
                        }}
                    }}
                    body {{
                        font-family: Helvetica, Arial, sans-serif;
                        font-size: 10pt;
                        line-height: 1.4;
                        color: #333333;
                    }}
                    p {{
                        margin-top: 0;
                        margin-bottom: 10pt;
                    }}
                    h1, h2, h3, h4 {{
                        color: #0f172a;
                        margin-bottom: 8px;
                        margin-top: 12px;
                    }}
                    .text-right {{ text-align: right; }}
                    .text-center {{ text-align: center; }}
                    .font-bold {{ font-weight: bold; }}
                </style>
            </head>
            <body>
                {header_content}
                {footer_content}
                <div style="padding-top: 5pt;">
                    {body}
                </div>
            </body>
            </html>
            """

        return body, entity_name

    def send_offer_email(self, instance, template_id, email_body_text=""):
        from django.core.mail import EmailMessage
        from django.conf import settings
        from django.core.files.base import ContentFile
        import os

        def link_callback(uri, rel):
            sUrl = settings.STATIC_URL
            sRoot = getattr(settings, "STATIC_ROOT", None)
            mUrl = settings.MEDIA_URL
            mRoot = settings.MEDIA_ROOT

            # Handle absolute URLs by stripping the domain
            import urllib.parse

            parsed = urllib.parse.urlparse(uri)
            path = parsed.path

            # Handle the proxy prefix
            if path.startswith("/api/media/"):
                path = path.replace("/api/media/", "/media/")

            if path.startswith(mUrl):
                local_path = os.path.join(mRoot, path.replace(mUrl, ""))
            elif sUrl and path.startswith(sUrl):
                local_path = os.path.join(sRoot, path.replace(sUrl, ""))
            else:
                return uri

            if not os.path.isfile(local_path):
                return uri
            return local_path

        try:
            request_user = (
                getattr(self, "request", None).user
                if getattr(self, "request", None)
                else None
            )
            subject = f"Offer of Employment - {entity_name}"

            email_body_text = self.request.data.get("email_body_text", "")
            if email_body_text:
                formatted_lines = []
                for line in email_body_text.splitlines():
                    if line.strip():
                        formatted_lines.append(f"<div>{line}</div>")
                    else:
                        formatted_lines.append("<br>")
                formatted_text = "\n".join(formatted_lines)
                email_body = f"""
                    <html>
                    <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
                        {formatted_text}
                    </body>
                    </html>
                    """
            else:
                designation = (
                    instance.employee.designation.title
                    if getattr(instance.employee, "designation", None)
                    else "Employee"
                )
                email_body = f"""
                    <html>
                    <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
                        <p>Dear <strong>{instance.employee.first_name}</strong>,</p>
                        <p>Congratulations!</p>
                        <p>We are thrilled to extend an offer for the position of <strong>{designation}</strong> at <strong>{entity_name}</strong>.</p>
                        <p>Please find your detailed offer letter attached to this email. Kindly review the document, and if you choose to accept, follow the instructions provided within the attachment.</p>
                        <p>If you have any questions or need further clarification, please feel free to reach out.</p>
                        <br>
                        <p>Best regards,</p>
                        <p><strong>HR Department</strong><br>{entity_name}</p>
                    </body>
                    </html>
                    """

            msg = EmailMessage(
                subject=subject,
                body=email_body,
                from_email=getattr(settings, "DEFAULT_FROM_EMAIL", None)
                or getattr(settings, "EMAIL_HOST_USER", None)
                or "noreply@hrms.local",
                to=[instance.employee.email],
            )
            msg.content_subtype = "html"

            # Generate PDF
            pdf_bytes = None
            try:
                from xhtml2pdf import pisa
                from io import BytesIO

                result = BytesIO()

                # xhtml2pdf does not support SVG and it breaks layout, strip it for PDF only
                import re

                pdf_body = re.sub(
                    r"<svg.*?>.*?</svg>", "", body, flags=re.DOTALL | re.IGNORECASE
                )

                pdf = pisa.pisaDocument(
                    BytesIO(pdf_body.encode("UTF-8")),
                    result,
                    link_callback=link_callback,
                )
                if not pdf.err:
                    pdf_bytes = result.getvalue()
                    instance.pdf_file.save(
                        f"{instance.offer_number}.pdf",
                        ContentFile(pdf_bytes),
                        save=True,
                    )
                    msg.attach(
                        f"Offer_Letter_{instance.employee.first_name}_{instance.employee.last_name}.pdf",
                        pdf_bytes,
                        "application/pdf",
                    )
            except ImportError:
                print("xhtml2pdf not installed. Skipping PDF attachment.")
            except Exception as e:
                print("PDF generation failed:", e)

            import threading

            def send_async_email(email_msg):
                try:
                    email_msg.send(fail_silently=False)
                except Exception as ex:
                    print("Async email send failed:", ex)

            threading.Thread(target=send_async_email, args=(msg,), daemon=True).start()
        except Exception as e:
            print("Failed to prepare offer email:", e)

    @action(detail=False, methods=["post"])
    def preview_email(self, request):
        employee_id = request.data.get("employee_id")
        template_id = request.data.get("template_id")
        if not employee_id or not template_id:
            return Response(
                {"error": "employee_id and template_id are required"}, status=400
            )

        try:
            from authentication.permissions import isolate_queryset

            employee = isolate_queryset(Employee.objects.all(), request.user).get(
                id=employee_id
            )
            html, _ = self._render_offer_html(employee, template_id, request.user)
            return Response({"html": html})
        except Employee.DoesNotExist:
            return Response({"error": "Employee not found"}, status=404)
        except Exception as e:
            return Response({"error": str(e)}, status=500)

    @action(detail=False, methods=["post"])
    def send_custom_email(self, request):
        employee_id = request.data.get("employee_id")
        template_id = request.data.get("template_id")
        html_content = request.data.get("html_content")

        if not employee_id or not template_id or not html_content:
            return Response(
                {"error": "employee_id, template_id, and html_content are required"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        if not isinstance(html_content, str):
            return Response(
                {"error": "html_content must be a string"},
                status=status.HTTP_400_BAD_REQUEST,
            )

        import re

        # Clean up doctype to avoid nested wrapping issues
        html_content = re.sub(
            r"<!DOCTYPE[^>]*>", "", html_content, flags=re.IGNORECASE
        ).strip()

        # (Removed aggressive table regex replacements to preserve custom HTML layouts)
        # Wrap in HTML skeleton with basic styles if missing
        if html_content and not html_content.lower().startswith("<html"):
            html_content = f"""
            <html>
            <head>
                <style>
                    @page {{
                        size: a4 portrait;
                        margin: 2cm;
                    }}
                    body {{
                        font-family: Helvetica, Arial, sans-serif;
                        font-size: 10pt;
                        line-height: 1.6;
                        color: #333333;
                    }}
                    h1, h2, h3, h4 {{
                        color: #0f172a;
                        margin-bottom: 12px;
                        margin-top: 16px;
                    }}
                    .text-right {{ text-align: right; }}
                    .text-center {{ text-align: center; }}
                    .font-bold {{ font-weight: bold; }}
                </style>
            </head>
            <body>
                {html_content}
            </body>
            </html>
            """

        try:
            from authentication.permissions import isolate_queryset

            employee = isolate_queryset(Employee.objects.all(), request.user).get(
                id=employee_id
            )

            from .models import OfferLetter
            import uuid

            offer = OfferLetter.objects.filter(employee=employee).first()
            if not offer:
                offer_num = f"OFF-{employee.code or str(uuid.uuid4())[:8].upper()}"
                offer = OfferLetter.objects.create(
                    employee=employee,
                    offer_number=offer_num,
                    status="Awaiting Acceptance",
                )
            else:
                offer.status = "Awaiting Acceptance"
                offer.save()

            from django.core.mail import EmailMessage
            from django.conf import settings
            from django.core.files.base import ContentFile

            entity_name = "Our Company"
            if employee.site and employee.site.branch and employee.site.branch.entity:
                entity_name = employee.site.branch.entity.name

            subject = f"Offer of Employment - {entity_name}"

            email_body_text = request.data.get("email_body_text", "")
            if email_body_text:
                formatted_lines = []
                for line in email_body_text.splitlines():
                    if line.strip():
                        formatted_lines.append(f"<div>{line}</div>")
                    else:
                        formatted_lines.append("<br>")
                formatted_text = "\n".join(formatted_lines)
                email_body = f"""
                <html>
                <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
                    {formatted_text}
                </body>
                </html>
                """
            else:
                designation = (
                    employee.designation.title
                    if getattr(employee, "designation", None)
                    else "Employee"
                )
                email_body = f"""
                <html>
                <body style="font-family: Arial, sans-serif; line-height: 1.6; color: #333;">
                    <p>Dear <strong>{employee.first_name}</strong>,</p>
                    <p>Congratulations!</p>
                    <p>We are thrilled to extend an offer for the position of <strong>{designation}</strong> at <strong>{entity_name}</strong>.</p>
                    <p>Please find your detailed offer letter attached to this email. Kindly review the document, and if you choose to accept, follow the instructions provided within the attachment.</p>
                    <p>If you have any questions or need further clarification, please feel free to reach out.</p>
                    <br>
                    <p>Best regards,</p>
                    <p><strong>HR Department</strong><br>{entity_name}</p>
                </body>
                </html>
                """

            sender = (
                getattr(settings, "DEFAULT_FROM_EMAIL", None)
                or getattr(settings, "EMAIL_HOST_USER", None)
                or "noreply@hrms.local"
            )
            msg = EmailMessage(
                subject=subject,
                body=email_body,
                from_email=sender,
                to=[employee.email],
            )
            msg.content_subtype = "html"

            # Generate PDF using xhtml2pdf if installed
            pdf_bytes = None
            try:
                from xhtml2pdf import pisa
                from io import BytesIO
                import os

                def link_callback(uri, rel):
                    sUrl = settings.STATIC_URL
                    sRoot = getattr(settings, "STATIC_ROOT", None)
                    mUrl = settings.MEDIA_URL
                    mRoot = settings.MEDIA_ROOT

                    # Handle absolute URLs by stripping the domain
                    import urllib.parse

                    parsed = urllib.parse.urlparse(uri)
                    path = parsed.path

                    # Handle the proxy prefix
                    if path.startswith("/api/media/"):
                        path = path.replace("/api/media/", "/media/")

                    if path.startswith(mUrl):
                        local_path = os.path.join(mRoot, path.replace(mUrl, ""))
                    elif sUrl and path.startswith(sUrl):
                        local_path = os.path.join(sRoot, path.replace(sUrl, ""))
                    else:
                        return uri

                    if not os.path.isfile(local_path):
                        return uri
                    return local_path

                result = BytesIO()

                # xhtml2pdf does not support SVG and it breaks layout, strip it for PDF only
                pdf_html_content = re.sub(
                    r"<svg.*?>.*?</svg>",
                    "",
                    html_content,
                    flags=re.DOTALL | re.IGNORECASE,
                )

                # Ensure the HTML has the correct meta charset for xhtml2pdf
                if (
                    "<head>" in pdf_html_content.lower()
                    and "charset" not in pdf_html_content.lower()
                ):
                    pdf_html_content = re.sub(
                        r"<head>",
                        '<head><meta charset="UTF-8">',
                        pdf_html_content,
                        flags=re.IGNORECASE,
                    )

                pdf = pisa.pisaDocument(
                    BytesIO(pdf_html_content.encode("UTF-8")),
                    result,
                    encoding="UTF-8",
                    link_callback=link_callback,
                )
                if not pdf.err:
                    pdf_bytes = result.getvalue()
                    # Save PDF to model
                    if offer:
                        offer.pdf_file.save(
                            f"{offer.offer_number}.pdf",
                            ContentFile(pdf_bytes),
                            save=True,
                        )
                    # Attach to email
                    msg.attach(
                        f"Offer_Letter_{employee.first_name}_{employee.last_name}.pdf",
                        pdf_bytes,
                        "application/pdf",
                    )
            except ImportError:
                print("xhtml2pdf not installed. Skipping PDF attachment.")
            except Exception as e:
                print("PDF generation failed:", e)

            import threading

            def send_async_email(email_msg):
                try:
                    email_msg.send(fail_silently=False)
                except Exception as ex:
                    print("Async email send failed:", ex)

            threading.Thread(target=send_async_email, args=(msg,), daemon=True).start()

            return Response(
                {
                    "status": "success",
                    "message": "Custom offer sent with PDF attachment (if xhtml2pdf installed)",
                }
            )
        except Employee.DoesNotExist:
            return Response({"error": "Employee not found"}, status=404)
        except Exception as e:
            return Response({"error": str(e)}, status=500)

    def perform_create(self, serializer):
        instance = serializer.save()
        template_id = self.request.data.get("template_id")
        email_body_text = self.request.data.get("email_body_text", "")
        if instance.status == "Awaiting Acceptance" and template_id:
            self.send_offer_email(instance, template_id, email_body_text)

    def perform_update(self, serializer):
        old_status = self.get_object().status
        instance = serializer.save()

        template_id = self.request.data.get("template_id")
        email_body_text = self.request.data.get("email_body_text", "")
        if instance.status == "Awaiting Acceptance" and template_id:
            self.send_offer_email(instance, template_id, email_body_text)

        # Trigger email if accepted
        if old_status != "Accepted" and instance.status == "Accepted":
            from django.core.mail import send_mail
            from django.conf import settings

            subject = f"Offer Accepted - {instance.employee.first_name} {instance.employee.last_name}"
            message = f"Offer letter {instance.offer_number} has been accepted by {instance.employee.first_name} {instance.employee.last_name}."
            sender = (
                getattr(settings, "DEFAULT_FROM_EMAIL", None)
                or getattr(settings, "EMAIL_HOST_USER", None)
                or "noreply@hrms.local"
            )
            recipients = [instance.employee.email]
            if sender and sender != "noreply@hrms.local":
                recipients.append(sender)
            send_mail(
                subject,
                message,
                sender,
                recipients,
                fail_silently=True,
            )


from rest_framework.views import APIView
from django.db.models import Q
from authentication.permissions import isolate_queryset


class GlobalSearchAPIView(APIView):
    permission_classes = [IsAuthenticated]

    def get(self, request, *args, **kwargs):
        q = request.query_params.get("q", "").strip()
        if not q:
            return Response([])

        results = []

        if request.user.is_superuser:
            from admin_org.models import Organization

            org_qs = Organization.objects.filter(
                Q(name__icontains=q) | Q(company_name__icontains=q)
            )[:5]
            for org in org_qs:
                results.append(
                    {
                        "id": org.id,
                        "type": "organization",
                        "title": org.name,
                        "subtitle": org.company_name or "Organization",
                        "url": f"/organizations/{org.id}",
                    }
                )

            from organisation.models import Site

            site_qs = Site.objects.filter(name__icontains=q, is_sub_site=False)[:5]
            for site in site_qs:
                city = (
                    site.branch.city
                    if site.branch and hasattr(site.branch, "city")
                    else "No City"
                )
                code = site.site_code if site.site_code else ""
                results.append(
                    {
                        "id": site.id,
                        "type": "site",
                        "title": site.name,
                        "subtitle": f"{city} • {code}",
                        "url": f"/superadmin-sites",
                    }
                )
            return Response(results)

        # Search Employees (non-superuser only)
        emp_qs = Employee.objects.filter(
            Q(first_name__icontains=q)
            | Q(last_name__icontains=q)
            | Q(email__icontains=q)
            | Q(code__icontains=q)
        )
        emp_qs = isolate_queryset(emp_qs, request.user)[:5]
        for emp in emp_qs:
            results.append(
                {
                    "id": emp.id,
                    "type": "employee",
                    "title": f"{emp.first_name} {emp.last_name}",
                    "subtitle": f"{emp.code} • {emp.email}",
                    "url": f"/employees?edit={emp.id}&tab=personal",
                }
            )

        # Search Sites
        from organisation.models import Site

        site_qs = Site.objects.filter(name__icontains=q)
        site_qs = isolate_queryset(site_qs, request.user)[:5]
        for site in site_qs:
            city = (
                site.branch.city
                if site.branch and hasattr(site.branch, "city")
                else "No City"
            )
            code = site.site_code if site.site_code else ""
            results.append(
                {
                    "id": site.id,
                    "type": "site",
                    "title": site.name,
                    "subtitle": f"{city} • {code}",
                    "url": f"/organisation/sites",
                }
            )

        return Response(results)
