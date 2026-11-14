from django.core.management.base import BaseCommand
from employees.utils import trigger_birthday_emails


class Command(BaseCommand):
    help = "Triggers daily birthday emails to employees celebrating their birthday today."

    def handle(self, *args, **options):
        self.stdout.write("Checking and sending today's birthday emails...")
        try:
            sent_count = trigger_birthday_emails()
            self.stdout.write(self.style.SUCCESS(f"Successfully processed birthday emails. Total sent: {sent_count}"))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f"Error executing birthday email job: {e}"))

