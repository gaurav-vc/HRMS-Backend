from django.core.management.base import BaseCommand
from django.utils import timezone
from leaves.models import LeaveType, LeaveBalance
from django.db import transaction

class Command(BaseCommand):
    help = 'Executes the year-end leave carry forward process for all active leave balances.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--year',
            type=int,
            help='The target year to roll over INTO. Defaults to current year.',
        )

    def handle(self, *args, **options):
        current_year = timezone.now().year
        target_year = options.get('year') or current_year
        previous_year = target_year - 1

        self.stdout.write(f"Initiating leave carry-forward from {previous_year} to {target_year}...")

        # Find all leave types that allow carry forward
        carry_forward_types = LeaveType.objects.filter(active=True, carry_forward_allowed=True)

        if not carry_forward_types.exists():
            self.stdout.write(self.style.WARNING("No active leave types allow carry forward."))
            return

        total_rolled_over = 0

        with transaction.atomic():
            for l_type in carry_forward_types:
                # Get all balances for the previous year
                balances = LeaveBalance.objects.filter(leave_type=l_type, year=previous_year)
                
                for balance in balances:
                    # Calculate how much can be carried over
                    carry_over_amount = min(balance.remaining_days, l_type.max_carry_forward)
                    
                    if carry_over_amount > 0:
                        # Create or update the new year's balance
                        new_balance, created = LeaveBalance.objects.get_or_create(
                            employee=balance.employee,
                            leave_type=l_type,
                            year=target_year,
                            defaults={
                                'allocated_days': l_type.annual_entitlement + carry_over_amount,
                                'used_days': 0,
                                'remaining_days': l_type.annual_entitlement + carry_over_amount
                            }
                        )
                        
                        if not created:
                            # If it already existed, just add the carry over
                            new_balance.allocated_days += carry_over_amount
                            new_balance.remaining_days += carry_over_amount
                            new_balance.save()
                            
                        # Zero out the old balance to prevent double carry-over if script runs twice
                        balance.remaining_days -= carry_over_amount
                        balance.save()
                        
                        total_rolled_over += 1

        self.stdout.write(self.style.SUCCESS(f"Successfully processed {total_rolled_over} employee leave balances for {target_year}."))
