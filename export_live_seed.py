#!/usr/bin/env python
"""
HRMS Live Server Seed Export Script
====================================
RUN THIS SCRIPT ON THE PRODUCTION / STAGING SERVER.

This script safely exports database records into a clean JSON seed fixture file
(hrms_live_seed.json) that can be sent to the development/QA team.

Safety & Security:
- 100% READ-ONLY: Never modifies or writes to the live production database.
- Credential Protection: In the generated export file, all user password hashes
  are sanitized and replaced with the hash for '123'. Real production passwords
  are NEVER exported or leaked into the JSON file.
- Error Resilient: Exports model-by-model. If an optional table is unmigrated or empty,
  it skips gracefully without failing the entire export.

Usage on Server:
  python export_live_seed.py

Options:
  --output FILENAME    Output file path (default: hrms_live_seed.json)
  --compress           Compress output with gzip (hrms_live_seed.json.gz)
  --include-punches    Include raw daily attendance and punch logs (can be large)
"""

import os
import sys
import json
import gzip
import argparse
from datetime import datetime

# Setup Django Environment
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))
sys.stdout.reconfigure(line_buffering=True)
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')

try:
    import django
    django.setup()
except Exception as e:
    print(f"[FATAL] Failed to initialize Django: {e}")
    print("Please make sure you run this script inside the HRMS backend project folder with the virtualenv active.")
    sys.exit(1)

from django.apps import apps
from django.core.serializers import serialize
from django.contrib.auth.hashers import make_password

# List of models to export in dependency-friendly order
CORE_EXPORT_MODELS = [
    # 1. Organization & Hierarchy
    ('admin_org.Organization', 'Organizations'),
    ('organisation.Entity', 'Entities / Companies'),
    ('organisation.Branch', 'Branches'),
    ('organisation.Site', 'Sites / Offices'),
    ('organisation.Department', 'Departments'),
    ('organisation.Designation', 'Designations'),
    ('organisation.Role', 'User Roles & Permissions'),
    ('organisation.AttendancePolicy', 'Attendance Policies'),
    ('organisation.PunctualitySlab', 'Punctuality Slabs'),
    ('org_engine.OrganizationNodeType', 'Org Hierarchy Types'),
    ('org_engine.OrganizationNode', 'Org Hierarchy Nodes'),
    ('org_engine.NodeRelationship', 'Org Node Relationships'),
    
    # 2. Authentication & Users
    ('auth.Group', 'Auth Groups'),
    ('auth.User', 'User Accounts'),
    
    # 3. Employees
    ('employees.Employee', 'Employees Master'),
    ('employees.EmployeeDocument', 'Employee Documents Metadata'),
    ('employees.EmployeeTransfer', 'Employee Transfers'),
    ('employees.EmployeeExit', 'Employee Exit Records'),
    ('employees.CompensationHistory', 'Compensation History'),
    ('employees.Notification', 'System Notifications'),
    
    # 4. Salary & Payroll Configuration
    ('payroll.SalaryStructure', 'Salary Structures'),
    ('payroll.ComponentRule', 'Salary Component Rules'),
    ('payroll.RuleDependency', 'Salary Rule Dependencies'),
    ('payroll.PayrollSettings', 'Payroll General Settings'),
    ('payroll.TaxRegimeSlab', 'Tax Regime Slabs'),
    ('payroll.CostCenter', 'Cost Centers'),
    ('payroll.EmployeeAllocation', 'Cost Center Allocations'),
    ('payroll.Loan', 'Employee Loans'),
    ('payroll.Reimbursement', 'Employee Reimbursements'),
    ('payroll.WalletPolicy', 'Wallet Policies'),
    ('payroll.EmployeeWallet', 'Employee Wallets'),
    
    # 5. Leaves & Holidays
    ('leaves.LeaveType', 'Leave Types'),
    ('leaves.LeavePolicyConfiguration', 'Leave Policies'),
    ('leaves.LeaveBalance', 'Employee Leave Balances'),
    ('leaves.LeaveRequest', 'Leave Requests'),
    ('leaves.Holiday', 'Leave Holidays'),
    
    # 6. Shift & Attendance Setup
    ('attendance.ShiftDefinition', 'Shift Definitions'),
    ('attendance.ShiftAssignment', 'Shift Assignments'),
    ('attendance.Holiday', 'Attendance Holidays'),
    ('attendance.HolidayRuleGroup', 'Holiday Rule Groups'),
    
    # 7. Overtime Policies
    ('ot_engine.OTPolicy', 'Overtime Policies'),
    ('ot_engine.OTThresholdConfig', 'Overtime Thresholds'),
    
    # 8. Announcements
    ('announcements.Announcement', 'Company Announcements'),
]

OPTIONAL_ATTENDANCE_MODELS = [
    ('attendance.DailyAttendance', 'Daily Attendance Records'),
    ('attendance.PunchLog', 'Biometric / Mobile Punch Logs'),
    ('attendance.ManualOverrideRequest', 'Manual Attendance Requests'),
    ('attendance.RegularizationRequest', 'Regularization Requests'),
]

def export_live_data(output_path, compress=False, include_punches=False):
    print("=" * 75)
    print(" HRMS LIVE SERVER DATABASE SEED EXPORTER")
    print(f" Timestamp: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print("=" * 75)
    print("[*] Note: This operation is 100% READ-ONLY on your live database.")
    print("[*] All exported user accounts will have their passwords set to '123' in the export file.\n")

    models_to_export = list(CORE_EXPORT_MODELS)
    if include_punches:
        models_to_export.extend(OPTIONAL_ATTENDANCE_MODELS)

    # Generate PBKDF2 hash for password '123'
    sanitized_pwd_hash = make_password("123")
    
    all_exported_objects = []
    total_models = len(models_to_export)
    successful_models = 0
    total_records = 0

    for idx, (model_str, label) in enumerate(models_to_export, 1):
        try:
            model = apps.get_model(model_str)
        except LookupError:
            print(f"[{idx:02d}/{total_models}] Skipping {label} ({model_str}): App/Model not installed.")
            continue

        try:
            qs = model.objects.all()
            count = qs.count()
            if count == 0:
                print(f"[{idx:02d}/{total_models}] {label:32} -> 0 records (empty)")
                continue

            # Serialize model queryset to JSON
            raw_json = serialize('json', qs)
            records = json.loads(raw_json)

            # Sanitize passwords for User accounts
            if model_str == 'auth.User':
                for rec in records:
                    if 'fields' in rec and 'password' in rec['fields']:
                        rec['fields']['password'] = sanitized_pwd_hash

            all_exported_objects.extend(records)
            total_records += len(records)
            successful_models += 1
            print(f"[{idx:02d}/{total_models}] {label:32} -> {len(records):5d} records exported")

        except Exception as e:
            print(f"[{idx:02d}/{total_models}] [WARNING] Could not export {label} ({model_str}): {e}")

    print("\n" + "-" * 75)
    print(f"Total Records Collected: {total_records} across {successful_models} models.")
    print(f"Writing to output file: {output_path}...")

    if compress or output_path.endswith('.gz'):
        if not output_path.endswith('.gz'):
            output_path += '.gz'
        with gzip.open(output_path, 'wt', encoding='utf-8') as gz_file:
            json.dump(all_exported_objects, gz_file, indent=2)
    else:
        with open(output_path, 'w', encoding='utf-8') as f:
            json.dump(all_exported_objects, f, indent=2)

    file_size_mb = os.path.getsize(output_path) / (1024 * 1024)
    file_size_kb = os.path.getsize(output_path) / 1024

    size_str = f"{file_size_mb:.2f} MB" if file_size_mb >= 1.0 else f"{file_size_kb:.1f} KB"

    print("=" * 75)
    print(f" SUCCESS! SEED FILE GENERATED: {output_path} ({size_str})")
    print("=" * 75)
    print("\nNext Steps for Deployment Team:")
    print(f"1. Download '{output_path}' from this server.")
    print("2. Send this file to the developer / QA team.")
    print("3. Done! The developer will load this directly into their local environment.")
    print("   All local user passwords will already be '123'.")
    print("=" * 75)

def main():
    parser = argparse.ArgumentParser(description="Safely export live HRMS database to a seed file.")
    parser.add_argument("--output", default="hrms_live_seed.json", help="Output file path (default: hrms_live_seed.json)")
    parser.add_argument("--compress", action="store_true", help="Gzip compress the output file (.json.gz)")
    parser.add_argument("--include-punches", action="store_true", help="Include daily attendance and biometric punches")

    args = parser.parse_args()
    export_live_data(args.output, compress=args.compress, include_punches=args.include_punches)

if __name__ == '__main__':
    main()
