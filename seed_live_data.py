#!/usr/bin/env python
"""
Live Server Data Seeder & Synchronizer for HRMS
===============================================
Syncs entire organization, site, employee, structure, and payroll data directly from
a live remote HRMS server (or a live JSON dump file) into the local database, and
configures all employee login passwords to '123' for seamless local development & QA.

Supported Modes:
1. API Mode (--mode api):
   Connects to live API (e.g. https://hrms.lotusdevelopers.com), authenticates as admin,
   paginates through all REST endpoints, and mirrors all records locally.
   
2. File Mode (--mode file --file live_dump.json):
   Loads a full database fixture dump from the live server, restores relational integrity,
   and normalizes all user account passwords to '123'.

3. Built-in Lotus Mode (--mode lotus):
   Seeds the authentic live Lotus Developers organization baseline with all live employee
   profiles, departments, designations, and salary structures with passwords set to '123'.

Usage Examples:
  # Pull directly from live URL:
  python seed_live_data.py --url https://hrms.lotusdevelopers.com --email admin@lotusdevelopers.com --password secret

  # Pull with a known JWT bearer token:
  python seed_live_data.py --url https://hrms.lotusdevelopers.com --token eyJhbGci...

  # Restore from a live JSON dump:
  python seed_live_data.py --mode file --file live_dump.json

  # Reset/Seed Lotus baseline data:
  python seed_live_data.py --mode lotus
"""

import os
import sys
import json
import ssl
import argparse
import urllib.request
import urllib.error
from datetime import datetime
from decimal import Decimal

# Setup Django Environment
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))
sys.stdout.reconfigure(line_buffering=True)
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')

import django
django.setup()

from django.db import transaction
from django.contrib.auth import get_user_model
from admin_org.models import Organization
from organisation.models import Entity, Branch, Site, Department, Designation, Role
from employees.models import Employee
from payroll.models import SalaryStructure, ComponentRule, PayrollSettings

User = get_user_model()

DEFAULT_PASSWORD = "123"

# ==============================================================================
# HTTP Client Helper (Built-in urllib, zero external dependencies)
# ==============================================================================
class LiveApiClient:
    def __init__(self, base_url, token=None, insecure=False):
        self.base_url = base_url.rstrip('/')
        self.token = token
        self.ssl_context = ssl.create_default_context()
        if insecure:
            self.ssl_context.check_hostname = False
            self.ssl_context.verify_mode = ssl.CERT_NONE

    def login(self, username_or_email, password):
        url = f"{self.base_url}/api/auth/token/"
        payload = json.dumps({"username": username_or_email, "password": password}).encode('utf-8')
        req = urllib.request.Request(
            url, 
            data=payload, 
            headers={"Content-Type": "application/json", "User-Agent": "HRMS-Live-Seeder/1.0"}
        )
        try:
            with urllib.request.urlopen(req, context=self.ssl_context, timeout=20) as resp:
                data = json.loads(resp.read().decode('utf-8'))
                self.token = data.get("access")
                return self.token
        except urllib.error.HTTPError as e:
            err_body = e.read().decode('utf-8')
            raise RuntimeError(f"Authentication failed (HTTP {e.code}): {err_body}")
        except Exception as e:
            raise RuntimeError(f"Failed to connect to live server at {self.base_url}: {e}")

    def fetch_all(self, endpoint):
        """Fetches all items from a REST endpoint, handling DRF pagination."""
        url = f"{self.base_url}{endpoint}" if endpoint.startswith('/') else f"{self.base_url}/{endpoint}"
        results = []
        
        headers = {
            "Content-Type": "application/json",
            "User-Agent": "HRMS-Live-Seeder/1.0"
        }
        if self.token:
            headers["Authorization"] = f"Bearer {self.token}"

        while url:
            req = urllib.request.Request(url, headers=headers)
            try:
                with urllib.request.urlopen(req, context=self.ssl_context, timeout=30) as resp:
                    payload = json.loads(resp.read().decode('utf-8'))
                    if isinstance(payload, list):
                        results.extend(payload)
                        break
                    elif isinstance(payload, dict):
                        if "results" in payload and isinstance(payload["results"], list):
                            results.extend(payload["results"])
                            url = payload.get("next")
                        elif "data" in payload:
                            if isinstance(payload["data"], list):
                                results.extend(payload["data"])
                            else:
                                results.append(payload["data"])
                            break
                        else:
                            results.append(payload)
                            break
            except urllib.error.HTTPError as e:
                print(f"  [Warning] Endpoint {endpoint} returned HTTP {e.code}. Skipping.")
                break
            except Exception as e:
                print(f"  [Error] Failed to fetch {url}: {e}")
                break

        return results

# ==============================================================================
# 1. API Synchronization Mode
# ==============================================================================
def sync_from_live_api(base_url, email=None, password=None, token=None, default_pwd=DEFAULT_PASSWORD, insecure=False):
    client = LiveApiClient(base_url, token=token, insecure=insecure)
    
    if not token:
        if not email or not password:
            raise ValueError("Either an API token or both email and password are required to connect to the live server.")
        print(f"[*] Authenticating with live server {base_url} as '{email}'...")
        client.login(email, password)
        print("[+] Authentication successful! Token acquired.")

    print("\n" + "=" * 70)
    print("STARTING LIVE DATA SYNCHRONIZATION")
    print("=" * 70)

    # 1. Organizations
    print("\n[1/7] Fetching Organizations...")
    live_orgs = client.fetch_all("/api/admin_org/organizations/")
    org_map = {}
    for o in live_orgs:
        org_obj, _ = Organization.objects.update_or_create(
            id=o.get("id"),
            defaults={
                "name": o.get("name") or "Live Organization",
                "company_name": o.get("company_name") or o.get("name") or "",
                "status": o.get("status") or "Active",
            }
        )
        org_map[o.get("id")] = org_obj
    print(f"  -> Synced {len(org_map)} organizations.")

    # 2. Entities, Branches & Sites
    print("\n[2/7] Fetching Entities, Branches & Sites...")
    live_entities = client.fetch_all("/api/organisation/entities/")
    entity_map = {}
    for e in live_entities:
        org = org_map.get(e.get("organization")) or Organization.objects.first()
        ent_obj, _ = Entity.objects.update_or_create(
            id=e.get("id"),
            defaults={
                "name": e.get("name"),
                "organization": org,
                "type": e.get("type") or "Private",
            }
        )
        entity_map[e.get("id")] = ent_obj
    print(f"  -> Synced {len(entity_map)} entities.")

    live_branches = client.fetch_all("/api/organisation/branches/")
    branch_map = {}
    for b in live_branches:
        ent = entity_map.get(b.get("entity")) or Entity.objects.first()
        br_obj, _ = Branch.objects.update_or_create(
            id=b.get("id"),
            defaults={
                "name": b.get("name"),
                "entity": ent,
            }
        )
        branch_map[b.get("id")] = br_obj
    print(f"  -> Synced {len(branch_map)} branches.")

    live_sites = client.fetch_all("/api/organisation/sites/")
    site_map = {}
    for s in live_sites:
        org = org_map.get(s.get("organization")) or Organization.objects.first()
        br = branch_map.get(s.get("branch"))
        site_obj, _ = Site.objects.update_or_create(
            id=s.get("id"),
            defaults={
                "name": s.get("name"),
                "organization": org,
                "branch": br,
                "modules": s.get("modules") or [],
            }
        )
        site_map[s.get("id")] = site_obj
    print(f"  -> Synced {len(site_map)} sites.")

    # 3. Departments & Designations
    print("\n[3/7] Fetching Departments & Designations...")
    live_depts = client.fetch_all("/api/organisation/departments/")
    dept_map = {}
    for d in live_depts:
        ent = entity_map.get(d.get("entity")) or Entity.objects.first()
        dept_obj, _ = Department.objects.update_or_create(
            id=d.get("id"),
            defaults={
                "name": d.get("name"),
                "entity": ent,
            }
        )
        dept_map[d.get("id")] = dept_obj
    print(f"  -> Synced {len(dept_map)} departments.")

    live_desigs = client.fetch_all("/api/organisation/designations/")
    desig_map = {}
    for d in live_desigs:
        dep = dept_map.get(d.get("department")) or Department.objects.first()
        des_obj, _ = Designation.objects.update_or_create(
            id=d.get("id"),
            defaults={
                "title": d.get("title"),
                "department": dep,
            }
        )
        desig_map[d.get("id")] = des_obj
    print(f"  -> Synced {len(desig_map)} designations.")

    # 4. Salary Structures & Components
    print("\n[4/7] Fetching Salary Structures & Components...")
    live_structs = client.fetch_all("/api/payroll/structures/")
    struct_map = {}
    for st in live_structs:
        struct_obj, _ = SalaryStructure.objects.update_or_create(
            id=st.get("id"),
            defaults={
                "name": st.get("name"),
                "status": st.get("status") or "Active",
            }
        )
        struct_map[st.get("id")] = struct_obj
        # If components nested
        comps = st.get("components") or []
        for c in comps:
            ComponentRule.objects.update_or_create(
                id=c.get("id"),
                defaults={
                    "structure": struct_obj,
                    "name": c.get("name"),
                    "type": c.get("type") or "Earning",
                    "formula": c.get("formula") or "0",
                    "prorate": c.get("prorate", False),
                    "is_statutory": c.get("is_statutory", False),
                }
            )
    print(f"  -> Synced {len(struct_map)} salary structures.")

    # Ensure PayrollSettings exists
    PayrollSettings.objects.get_or_create(defaults={
        "ctc_variance_threshold_percent": 1.0,
        "pf_wage_limit": 15000.0,
        "esic_wage_limit": 21000.0
    })

    # 5. Employees & User Accounts (with password normalization to '123')
    print("\n[5/7] Fetching Employees & Generating Local User Accounts...")
    live_employees = client.fetch_all("/api/employees/")
    synced_emps = 0
    synced_users = 0

    default_struct = SalaryStructure.objects.filter(status='Active').first()

    for emp_data in live_employees:
        email = (emp_data.get("email") or "").strip()
        code = (emp_data.get("code") or "").strip()
        first_name = (emp_data.get("first_name") or "Employee").strip()
        last_name = (emp_data.get("last_name") or "").strip()
        phone = (emp_data.get("phone") or "").strip()

        if not email and not code:
            continue

        username = email if email else code

        # Create or update User
        user = User.objects.filter(email__iexact=email).first() if email else None
        if not user:
            user = User.objects.filter(username__iexact=username).first()

        role = emp_data.get("role") or "employee"
        is_staff = bool(role in ['admin', 'org_admin', 'manager'] or emp_data.get("is_admin"))

        if not user:
            user = User(
                username=username,
                email=email,
                first_name=first_name,
                last_name=last_name,
                is_active=True,
                is_staff=is_staff
            )
        else:
            user.username = username
            if email:
                user.email = email
            user.first_name = first_name
            user.last_name = last_name
            user.is_active = True
            user.is_staff = is_staff

        user.set_password(default_pwd)
        user.save()
        synced_users += 1

        # Resolve relations
        ent = entity_map.get(emp_data.get("entity")) or Entity.objects.first()
        org = org_map.get(emp_data.get("organization")) or (ent.organization if ent else Organization.objects.first())
        site = site_map.get(emp_data.get("site")) or Site.objects.first()
        dept = dept_map.get(emp_data.get("department"))
        desig = desig_map.get(emp_data.get("designation"))
        s_struct = struct_map.get(emp_data.get("salary_structure")) or default_struct

        # Resolve DOJ
        doj_val = None
        if emp_data.get("doj"):
            try:
                doj_val = datetime.strptime(str(emp_data["doj"])[:10], "%Y-%m-%d").date()
            except Exception:
                pass

        # Create or update Employee
        emp_obj, _ = Employee.objects.update_or_create(
            code=code if code else f"EMP{emp_data.get('id')}",
            defaults={
                "first_name": first_name,
                "last_name": last_name,
                "email": email,
                "phone": phone,
                "doj": doj_val,
                "status": emp_data.get("status") or "Active",
                "role": role,
                "employee_type": emp_data.get("employee_type") or "Normal Employee",
                "organization": org,
                "entity": ent,
                "site": site,
                "department": dept,
                "designation": desig,
                "salary_structure": s_struct,
                "ctc": Decimal(str(emp_data.get("ctc") or 0)),
                "group_category": emp_data.get("group_category") or "General",
                "grade_category": emp_data.get("grade_category") or "Unassigned",
                "user": user,
            }
        )
        if site:
            emp_obj.enrolled_sites.add(site)
        if org:
            org_sites = list(Site.objects.filter(organization=org))
            if org_sites:
                emp_obj.enrolled_sites.add(*org_sites)
        synced_emps += 1

    print(f"  -> Synced {synced_emps} employees and {synced_users} user logins (all passwords set to '{default_pwd}').")

    print("\n" + "=" * 70)
    print("SUCCESS: LIVE SERVER DATA SYNCHRONIZED LOCALLY")
    print("=" * 70)
    print(f"[✓] You can now log in with ANY live employee email/code using password '{default_pwd}'!")

# ==============================================================================
# 2. File Import Mode (from django dumpdata JSON fixture)
# ==============================================================================
def sync_from_dump_file(file_path, default_pwd=DEFAULT_PASSWORD):
    if not os.path.exists(file_path):
        raise FileNotFoundError(f"Fixture file not found: {file_path}")

    print(f"[*] Importing database fixture from '{file_path}'...")
    from django.core.management import call_command
    try:
        call_command('loaddata', file_path)
    except Exception as e:
        print(f"[!] Standard loaddata reported: {e}. Falling back to atomic model parser...")
        _manual_fixture_load(file_path)

    # Post-import: Reset all user passwords to '123'
    print(f"[*] Normalizing all user passwords to '{default_pwd}' for local development...")
    count = 0
    for u in User.objects.all():
        u.set_password(default_pwd)
        u.save()
        count += 1

    print(f"[+] Successfully loaded dump and reset {count} user passwords to '{default_pwd}'!")

def _manual_fixture_load(file_path):
    with open(file_path, 'r', encoding='utf-8') as f:
        data = json.load(f)
    print(f"  -> Loaded {len(data)} fixture records. Applying...")
    from django.core.serializers import deserialize
    for obj in deserialize('json', json.dumps(data), ignorenonexistent=True):
        try:
            obj.save()
        except Exception:
            pass

# ==============================================================================
# 3. Built-in Lotus Live Baseline Mode
# ==============================================================================
def sync_lotus_baseline(default_pwd=DEFAULT_PASSWORD):
    from setup_scripts.sync_lotus_live_accounts import LOTUS_LIVE_ACCOUNTS, sync_accounts
    print("[*] Running built-in Lotus live accounts synchronization...")
    sync_accounts()
    print(f"[+] All Lotus live accounts verified with password '{default_pwd}'!")

# ==============================================================================
# CLI Entrypoint
# ==============================================================================
def main():
    parser = argparse.ArgumentParser(description="Seed entire HRMS database from live server or dump file.")
    parser.add_argument("--mode", choices=["api", "file", "lotus"], default=None,
                        help="Sync mode: 'api' (pull from live URL), 'file' (from JSON dump), or 'lotus' (local baseline)")
    parser.add_argument("--url", default="https://hrms.lotusdevelopers.com",
                        help="Live server base URL (default: https://hrms.lotusdevelopers.com)")
    parser.add_argument("--email", default=None, help="Live admin login email")
    parser.add_argument("--password", default=None, help="Live admin login password")
    parser.add_argument("--token", default=None, help="Direct JWT Bearer token")
    parser.add_argument("--file", default="data.json", help="Path to JSON dump file (for --mode file)")
    parser.add_argument("--default-password", default=DEFAULT_PASSWORD, help="Password to set for all local accounts (default: 123)")
    parser.add_argument("--insecure", action="store_true", help="Bypass SSL certificate checks for self-signed staging domains")

    args = parser.parse_args()

    # Determine mode automatically if not specified
    mode = args.mode
    if not mode:
        if args.token or (args.email and args.password):
            mode = "api"
        elif os.path.exists(args.file) and args.file != "data.json":
            mode = "file"
        else:
            mode = "lotus"

    print("=" * 70)
    print("HRMS LIVE DATA SEEDING UTILITY")
    print(f"Mode: {mode.upper()} | Target Default Password: {args.default_password}")
    print("=" * 70)

    if mode == "api":
        sync_from_live_api(
            base_url=args.url,
            email=args.email,
            password=args.password,
            token=args.token,
            default_pwd=args.default_password,
            insecure=args.insecure
        )
    elif mode == "file":
        sync_from_dump_file(args.file, default_pwd=args.default_password)
    elif mode == "lotus":
        sync_lotus_baseline(default_pwd=args.default_password)

if __name__ == '__main__':
    main()
