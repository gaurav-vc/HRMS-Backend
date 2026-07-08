from django.db import models

class Organization(models.Model):
    name = models.CharField(max_length=150)
    status = models.CharField(max_length=20, default='Active')
    company_name = models.CharField(max_length=150, blank=True, null=True)
    entity_name = models.CharField(max_length=150, blank=True, null=True)
    site_location = models.CharField(max_length=150, blank=True, null=True)
    country = models.CharField(max_length=50, blank=True, null=True)
    region = models.CharField(max_length=50, blank=True, null=True)
    state = models.CharField(max_length=50, blank=True, null=True)
    city = models.CharField(max_length=50, blank=True, null=True)
    zone = models.CharField(max_length=50, blank=True, null=True)
    
    # Advanced Options
    white_label_enabled = models.BooleanField(default=False)
    sub_domain = models.CharField(max_length=100, blank=True, null=True)
    
    # Billing Config
    solution_type = models.CharField(max_length=50, blank=True, null=True)
    solution_for = models.CharField(max_length=50, blank=True, null=True)
    billing_term = models.CharField(max_length=50, blank=True, null=True)
    rate_of_billing = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    billing_cycle = models.CharField(max_length=50, blank=True, null=True)
    start_date = models.DateField(null=True, blank=True)
    project_duration = models.CharField(max_length=50, blank=True, null=True)
    end_date = models.DateField(null=True, blank=True)
    billing_date = models.DateField(null=True, blank=True)
    payment_status = models.CharField(max_length=20, default='Paid')
    current_due = models.DecimalField(max_digits=10, decimal_places=2, default=0.00)
    
    # Billing Info
    billing_contact_email = models.EmailField(blank=True, null=True)
    tax_id = models.CharField(max_length=50, blank=True, null=True)
    billing_address = models.TextField(blank=True, null=True)
    
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        db_table = 'organisation_organization'

    def __str__(self):
        return self.name

class Invoice(models.Model):
    organization = models.ForeignKey(Organization, on_delete=models.CASCADE, related_name='invoices')
    invoice_number = models.CharField(max_length=50, unique=True)
    billing_date = models.DateField()
    due_date = models.DateField()
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    status = models.CharField(max_length=20, default='Paid') # Paid, Overdue, Pending
    
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        db_table = 'organisation_invoice'

    def __str__(self):
        return f"{self.invoice_number} - {self.organization.name}"
