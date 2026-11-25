import os
import sys
import django
from datetime import datetime

# Setup Django environment
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))
sys.stdout.reconfigure(line_buffering=True)
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

from organisation.models import Organization, Entity, Department, Designation, Site
from employees.models import Employee
from authentication.models import User
from payroll.models import SalaryStructure

LOTUS_LIVE_ACCOUNTS = [
    {
        "code": "CEO001",
        "first_name": "Sanjay",
        "last_name": "S",
        "email": "sanjay@lotusdevelopers.com",
        "phone": "9820000001",
        "doj": None,
        "department_name": "CEO",
        "designation_title": None,
        "group_category": "General",
        "grade_category": "Unassigned",
        "role": "admin",
        "ctc": 3600000.0,
    },
    {
        "code": "EMP-1004",
        "first_name": "Dinesh",
        "last_name": "Kumar",
        "email": "dinesh.kumar@lotushq.com",
        "phone": "9820001004",
        "doj": "2024-01-01",
        "department_name": "IT",
        "designation_title": "EXECUTIVES",
        "group_category": "General",
        "grade_category": "Unassigned",
        "role": "employee",
        "ctc": 600000.0,
    },
    {
        "code": "EMP-1005",
        "first_name": "Rajnikant",
        "last_name": "Deokar",
        "email": "rajnikant.deokar@lotushq.com",
        "phone": "9820001005",
        "doj": "2024-01-01",
        "department_name": "IT",
        "designation_title": "EXECUTIVES",
        "group_category": "General",
        "grade_category": "Unassigned",
        "role": "employee",
        "ctc": 960000.0,
    },
    {
        "code": "EMP-1006",
        "first_name": "Naresh",
        "last_name": "Kalluri",
        "email": "naresh.kalluri@lotushq.com",
        "phone": "9820001006",
        "doj": "2024-01-01",
        "department_name": "IT",
        "designation_title": "EXECUTIVES",
        "group_category": "General",
        "grade_category": "Unassigned",
        "role": "employee",
        "ctc": 300000.0,
    },
    {
        "code": "EMP-22119",
        "first_name": "Paras",
        "last_name": "Desai",
        "email": "parasdesai@lotusdevelopers.com",
        "phone": "9820022119",
        "doj": None,
        "department_name": "IT",
        "designation_title": "EXECUTIVES",
        "group_category": "General",
        "grade_category": "Unassigned",
        "role": "employee",
        "ctc": 720000.0,
    },
    {
        "code": "LD0293",
        "first_name": "Apurva Ajay",
        "last_name": "Petkar",
        "email": "apurva@lotusdevelopers.com",
        "phone": "9820000293",
        "doj": "2025-05-19",
        "department_name": "Architects & Interior Designers",
        "designation_title": None,
        "group_category": "General",
        "grade_category": "Unassigned",
        "role": "employee",
        "ctc": 720000.0,
    },
    {
        "code": "LD0288",
        "first_name": "Manuraj",
        "last_name": "Esakimuthu",
        "email": "8850145843@gmail.com",
        "phone": "8850145843",
        "doj": "2025-04-14",
        "department_name": "IT",
        "designation_title": "EXECUTIVES",
        "group_category": "General",
        "grade_category": "Unassigned",
        "role": "employee",
        "ctc": 600000.0,
    },
    {
        "code": "LD0294",
        "first_name": "Murugan",
        "last_name": "Arumugam",
        "email": "9821132998@gmail.com",
        "phone": "9821132998",
        "doj": "2025-06-02",
        "department_name": "IT",
        "designation_title": "EXECUTIVES",
        "group_category": "General",
        "grade_category": "Unassigned",
        "role": "employee",
        "ctc": 600000.0,
    },
    {
        "code": "LD0192",
        "first_name": "Mukund",
        "last_name": "Zujam",
        "email": "zujamm@lotusdevelopers.com",
        "phone": "9820000192",
        "doj": "2006-04-01",
        "department_name": "Accounts & Finance",
        "designation_title": "Senior Manager",
        "group_category": "General",
        "grade_category": "Unassigned",
        "role": "manager",
        "ctc": 1440000.0,
    },
    {
        "code": "LD0150",
        "first_name": "Ilaiyaraja",
        "last_name": "Krishnan",
        "email": "raja@lotusdevelopers.com",
        "phone": "9820000150",
        "doj": "2019-01-14",
        "department_name": "IT",
        "designation_title": "IT Manager",
        "group_category": "General",
        "grade_category": "Unassigned",
        "role": "manager",
        "ctc": 1200000.0,
    },
]

def sync_accounts():
    org = Organization.objects.get(id=2)
    entity = Entity.objects.filter(organization=org).order_by('id').first() or Entity.objects.get(id=6)
    site = Site.objects.filter(organization=org).first() or Site.objects.get(id=9)
    salary_structure = SalaryStructure.objects.filter(id=6).first() or SalaryStructure.objects.first()

    print(f"Target Org: [{org.id}] {org.name}")
    print(f"Target Entity: [{entity.id}] {entity.name}")
    print(f"Target Site: [{site.id}] {site.name}")
    print(f"Target Salary Structure: [{salary_structure.id}] {salary_structure.name}")

    results = []

    for acc in LOTUS_LIVE_ACCOUNTS:
        code = acc["code"]
        first_name = acc["first_name"]
        last_name = acc["last_name"]
        email = acc["email"]
        phone = acc["phone"]
        doj_str = acc["doj"]
        dept_name = acc["department_name"]
        desig_title = acc["designation_title"]
        group_cat = acc["group_category"]
        grade_cat = acc["grade_category"]
        role = acc["role"]
        ctc = acc["ctc"]

        # Parse DOJ
        doj = datetime.strptime(doj_str, "%Y-%m-%d").date() if doj_str else None

        # Resolve or create Department
        dept = None
        if dept_name:
            dept, _ = Department.objects.get_or_create(name=dept_name, entity=entity)

        # Resolve or create Designation
        desig = None
        if desig_title and dept:
            desig, _ = Designation.objects.get_or_create(title=desig_title, department=dept)
        elif desig_title:
            desig = Designation.objects.filter(title__iexact=desig_title).first()

        # 1. Resolve or create User
        user = User.objects.filter(email__iexact=email).first()
        if not user:
            user = User.objects.filter(username__iexact=email).first()
        
        # Check if updating an existing employee who had a previous dummy user
        if not user and code == "LD0192":
            # Previous Mukund Zujam employee was EMP-1001 with mukund.zujam@lotushq.com
            emp_prev = Employee.objects.filter(code="EMP-1001").first()
            if emp_prev and emp_prev.user:
                user = emp_prev.user

        if not user:
            user = User(
                username=email,
                email=email,
                first_name=first_name,
                last_name=last_name,
                is_active=True,
                is_staff=True if role in ['admin', 'manager'] else False
            )
        else:
            user.username = email
            user.email = email
            user.first_name = first_name
            user.last_name = last_name
            user.is_active = True
            if role in ['admin', 'manager']:
                user.is_staff = True

        # Set password to 123
        user.set_password("123")
        user.save()

        # 2. Resolve or create Employee
        emp = Employee.objects.filter(code=code).first()
        if not emp:
            emp = Employee.objects.filter(email__iexact=email).first()

        if not emp and code == "LD0192":
            emp = Employee.objects.filter(code="EMP-1001").first()

        if not emp:
            emp = Employee(
                code=code,
                first_name=first_name,
                last_name=last_name,
                email=email,
                phone=phone,
                doj=doj,
                status="Active",
                role=role,
                employee_type="Normal Employee",
                organization=org,
                entity=entity,
                site=site,
                department=dept,
                designation=desig,
                group_category=group_cat,
                grade_category=grade_cat,
                salary_structure=salary_structure,
                ctc=ctc,
                user=user
            )
        else:
            emp.code = code
            emp.first_name = first_name
            emp.last_name = last_name
            emp.email = email
            if phone:
                emp.phone = phone
            emp.doj = doj
            emp.status = "Active"
            emp.role = role
            emp.organization = org
            emp.entity = entity
            emp.site = site
            emp.department = dept
            emp.designation = desig
            emp.group_category = group_cat
            emp.grade_category = grade_cat
            emp.salary_structure = salary_structure
            if not emp.ctc or emp.ctc <= 0:
                emp.ctc = ctc
            emp.user = user

        emp.save()
        # Ensure employee is enrolled into all organization sites so they are visible under any selected site
        org_sites = list(Site.objects.filter(organization=org))
        if org_sites:
            emp.enrolled_sites.add(*org_sites)

        # Verify password validation via check_password
        auth_ok = user.check_password("123")

        results.append({
            "code": emp.code,
            "name": f"{emp.first_name} {emp.last_name}",
            "email": emp.email,
            "username": user.username,
            "user_id": user.id,
            "emp_id": emp.id,
            "dept": dept.name if dept else "—",
            "desig": desig.title if desig else "—",
            "doj": str(emp.doj) if emp.doj else "—",
            "password_123_verified": auth_ok
        })

    # Also ensure organization admin (mathurvibhu865@gmail.com) has password '123' for testing
    admin_u = User.objects.filter(email='mathurvibhu865@gmail.com').first()
    if admin_u:
        admin_u.set_password('123')
        admin_u.save()
        print(f"Updated Lotus Admin ({admin_u.email}) password to '123': True")

    super_u = User.objects.filter(username='Admin').first()
    if super_u:
        super_u.set_password('123')
        super_u.save()
        print(f"Updated Super Admin ({super_u.username}) password to '123': True")

    print("\n" + "=" * 80)
    print("LOTUS ACCOUNTS SYNCHRONIZATION SUMMARY")
    print("=" * 80)
    for r in results:
        print(f"[{r['code']}] {r['name']:<22} | {r['email']:<32} | PWD Valid: {r['password_123_verified']} | Dept: {r['dept']:<25} | Desig: {r['desig']}")

if __name__ == '__main__':
    sync_accounts()
