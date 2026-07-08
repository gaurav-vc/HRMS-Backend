from django.core.management.base import BaseCommand
from django.db import connection

class Command(BaseCommand):
    help = 'Fixes missing columns in organisation_organization table'

    def handle(self, *args, **kwargs):
        cols = [
            "white_label_enabled bool DEFAULT 0", 
            "sub_domain varchar(100) NULL", 
            "solution_type varchar(50) NULL", 
            "solution_for varchar(50) NULL", 
            "billing_term varchar(50) NULL", 
            "rate_of_billing decimal(10, 2) NULL", 
            "billing_cycle varchar(50) NULL", 
            "start_date date NULL", 
            "project_duration varchar(50) NULL", 
            "end_date date NULL", 
            "billing_date date NULL", 
            "payment_status varchar(20) DEFAULT 'Paid'", 
            "current_due decimal(10, 2) DEFAULT 0.0", 
            "billing_contact_email varchar(254) NULL", 
            "tax_id varchar(50) NULL", 
            "billing_address text NULL"
        ]

        with connection.cursor() as cursor:
            for col in cols:
                try:
                    cursor.execute(f"ALTER TABLE organisation_organization ADD COLUMN {col}")
                    self.stdout.write(self.style.SUCCESS(f"Successfully added column {col}"))
                except Exception as e:
                    self.stdout.write(self.style.WARNING(f"Skipped {col.split()[0]} (maybe already exists)"))
            
            try:
                cursor.execute('''CREATE TABLE IF NOT EXISTS "organisation_invoice" ("id" integer NOT NULL PRIMARY KEY AUTOINCREMENT, "invoice_number" varchar(50) NOT NULL UNIQUE, "billing_date" date NOT NULL, "due_date" date NOT NULL, "amount" decimal(12, 2) NOT NULL, "status" varchar(20) NOT NULL, "created_at" datetime NOT NULL, "organization_id" bigint NOT NULL REFERENCES "organisation_organization" ("id") DEFERRABLE INITIALLY DEFERRED);''')
                self.stdout.write(self.style.SUCCESS("Successfully ensured organisation_invoice table exists"))
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"Error creating invoice table: {e}"))
