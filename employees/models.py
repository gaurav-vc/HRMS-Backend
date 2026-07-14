from django.db import models
from django.contrib.auth.models import User
from organisation.models import Entity, Branch, Site, Department, Designation, Role
from admin_org.models import Organization

ROLE_CHOICES = [
    ('super_admin', 'Super Admin'),
    ('org_admin', 'Org Admin'),
    ('site_admin', 'Site Admin'),
    ('hr', 'HR'),
    ('manager', 'Manager'),
    ('employee', 'Employee'),
]

EMPLOYEE_TYPE_CHOICES = [
    ('Service Employee', 'Service Employee'),
    ('Normal Employee', 'Normal Employee'),
]

class Employee(models.Model):
    employee_type = models.CharField(max_length=50, choices=EMPLOYEE_TYPE_CHOICES, default='Normal Employee')
    # Authentication & Access
    user = models.OneToOneField(User, on_delete=models.CASCADE, null=True, blank=True, related_name='employee_profile')
    role = models.CharField(max_length=20, choices=ROLE_CHOICES, default='employee')
    dynamic_role = models.ForeignKey(Role, on_delete=models.SET_NULL, null=True, blank=True, related_name='employees')
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, null=True, blank=True, related_name='employees')
    mfa_enabled = models.BooleanField(default=False)

    # Personal Details
    code = models.CharField(max_length=50, unique=True)
    first_name = models.CharField(max_length=100)
    last_name = models.CharField(max_length=100)
    email = models.EmailField(unique=True)
    phone = models.CharField(max_length=20, blank=True, null=True)
    dob = models.DateField(blank=True, null=True)
    gender = models.CharField(max_length=20, default="Male")
    address = models.TextField(blank=True, null=True)
    
    # Employment Details
    doj = models.DateField(blank=True, null=True)
    status = models.CharField(max_length=20, default="Active")
    ctc = models.IntegerField(default=0)
    
    # Tax Configuration
    TAX_REGIME_CHOICES = [('New', 'New Regime'), ('Old', 'Old Regime')]
    tax_regime = models.CharField(max_length=10, choices=TAX_REGIME_CHOICES, default='New')
    tax_saving_deductions = models.DecimalField(max_digits=12, decimal_places=2, default=0.0, help_text="Total approved tax savings (e.g. 80C) used only for Old Regime calculations.")
    
    # Bonus Configuration
    bonus_applicable = models.BooleanField(default=False)
    BONUS_TYPE_CHOICES = [
        ('Fixed Amount', 'Fixed Amount'),
        ('Percentage', 'Percentage'),
        ('Monthly Salary', 'Monthly Salary'),
    ]
    bonus_type = models.CharField(max_length=50, choices=BONUS_TYPE_CHOICES, blank=True, null=True)
    bonus_value = models.DecimalField(max_digits=12, decimal_places=2, default=0.0)
    bonus_months = models.IntegerField(default=1)
    
    # Compliance / Bank Details
    pf_applicable = models.BooleanField(default=False)
    pan = models.CharField(max_length=50, blank=True, null=True)
    aadhaar = models.CharField(max_length=50, blank=True, null=True)
    uan = models.CharField(max_length=50, blank=True, null=True)
    esi = models.CharField(max_length=50, blank=True, null=True)
    bank_name = models.CharField(max_length=100, blank=True, null=True)
    bank_account = models.CharField(max_length=50, blank=True, null=True)
    ifsc = models.CharField(max_length=50, blank=True, null=True)
    salary_structure = models.ForeignKey('payroll.SalaryStructure', on_delete=models.SET_NULL, null=True, blank=True, related_name='employees')
    
    # Organisation Relations
    entity = models.ForeignKey(Entity, on_delete=models.SET_NULL, null=True, blank=True, related_name='employees')
    branch = models.ForeignKey(Branch, on_delete=models.SET_NULL, null=True, blank=True, related_name='employees')
    site = models.ForeignKey(Site, on_delete=models.SET_NULL, null=True, blank=True, related_name='employees')
    enrolled_sites = models.ManyToManyField(Site, related_name='enrolled_employees', blank=True)
    department = models.ForeignKey(Department, on_delete=models.SET_NULL, null=True, blank=True, related_name='employees')
    designation = models.ForeignKey(Designation, on_delete=models.SET_NULL, null=True, blank=True, related_name='employees')
    
    # Self-referential Manager relation
    manager = models.ForeignKey('self', on_delete=models.SET_NULL, null=True, blank=True, related_name='reportees')
    
    def __str__(self):
        return f"{self.first_name} {self.last_name} ({self.code})"

class Notification(models.Model):
    recipient = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='notifications')
    title = models.CharField(max_length=200)
    message = models.TextField()
    is_read = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    related_run_id = models.IntegerField(null=True, blank=True)
    related_employee_id = models.IntegerField(null=True, blank=True)
    
    class Meta:
        ordering = ['-created_at']
        
    def __str__(self):
        return f"To {self.recipient.code}: {self.title}"

class EmployeeDocument(models.Model):
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='documents')
    document_type = models.CharField(max_length=50) # e.g., 'ID Proof', 'Offer Letter', 'Resignation Letter'
    name = models.CharField(max_length=100)
    file = models.FileField(upload_to='employee_documents/')
    uploaded_at = models.DateTimeField(auto_now_add=True)
    
    def __str__(self):
        return f"{self.employee.code} - {self.name}"

class EmployeeTransfer(models.Model):
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='transfers')
    effective_date = models.DateField()
    
    # Snapshot of previous state
    old_department = models.ForeignKey(Department, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    old_designation = models.ForeignKey(Designation, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    old_site = models.ForeignKey(Site, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    old_manager = models.ForeignKey(Employee, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    
    # New state
    new_department = models.ForeignKey(Department, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    new_designation = models.ForeignKey(Designation, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    new_site = models.ForeignKey(Site, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    new_manager = models.ForeignKey(Employee, on_delete=models.SET_NULL, null=True, blank=True, related_name='+')
    
    reason = models.TextField(blank=True, null=True)
    status = models.CharField(max_length=20, default='Pending') # Pending, Approved, Rejected, Executed
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

class EmployeeExit(models.Model):
    EXIT_TYPES = [
        ('Resignation', 'Resignation'),
        ('Termination', 'Termination'),
        ('Absconding', 'Absconding'),
        ('Retirement', 'Retirement')
    ]
    employee = models.OneToOneField(Employee, on_delete=models.CASCADE, related_name='exit_process')
    exit_type = models.CharField(max_length=50, choices=EXIT_TYPES)
    reason = models.TextField(blank=True, null=True)
    
    notice_period_days = models.IntegerField(default=30)
    resignation_date = models.DateField(auto_now_add=True)
    last_working_day = models.DateField()
    
    manager_approved = models.BooleanField(default=False)
    hr_cleared = models.BooleanField(default=False)
    it_cleared = models.BooleanField(default=False)
    finance_cleared = models.BooleanField(default=False)
    
    fnf_status = models.CharField(max_length=50, default='Pending') # Full & Final
    status = models.CharField(max_length=50, default='Pending') # Pending, Approved, Rejected, Deactivated
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

class CompensationHistory(models.Model):
    """
    Immutable ledger of all CTC and Salary Structure changes for an employee.
    Used by the Retro Arrears engine to recalculate backdated frozen payroll runs.
    """
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name='compensation_history')
    ctc = models.IntegerField()
    salary_structure = models.ForeignKey('payroll.SalaryStructure', on_delete=models.PROTECT)
    effective_from = models.DateField()
    effective_to = models.DateField(null=True, blank=True)
    
    reason = models.TextField(blank=True, null=True)
    changed_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    
    class Meta:
        ordering = ['-effective_from', '-created_at']
        
    def __str__(self):
        return f"{self.employee.code} | {self.ctc} | {self.effective_from}"

class OfferTemplate(models.Model):
    name = models.CharField(max_length=150)
    category = models.CharField(max_length=100) # e.g. Graduate Hire, Experienced Hire
    body_html = models.TextField(blank=True, null=True)
    placeholders = models.JSONField(default=list) # e.g. ["EmployeeName", "Designation", "JoiningDate"]
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return self.name

class OfferLetter(models.Model):
    STATUS_CHOICES = [
        ('Draft', 'Draft'),
        ('Pending Approval', 'Pending Approval'),
        ('Awaiting Acceptance', 'Awaiting Acceptance'),
        ('Accepted', 'Accepted'),
        ('Rejected', 'Rejected'),
        ('Expired', 'Expired'),
        ('Joined', 'Joined'),
        ('Declined', 'Declined'),
    ]
    
    employee = models.OneToOneField(Employee, on_delete=models.CASCADE, related_name='offer_letter')
    offer_number = models.CharField(max_length=50, unique=True)
    status = models.CharField(max_length=50, choices=STATUS_CHOICES, default='Pending Approval')
    joining_date = models.DateField(null=True, blank=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    def __str__(self):
        return f"{self.offer_number} - {self.employee.first_name} {self.employee.last_name}"
