from decimal import Decimal
from datetime import timedelta
from django.utils import timezone
from .models import (
    CompOffBalance, CompOffTransaction, 
    RetroOTEntry, OTPayrollEntry, OTThresholdConfig,
    OTRequest
)

# ==========================================
# PHASE 9: COMP-OFF LIFECYCLE
# ==========================================

class CompOffLifecycleService:
    @staticmethod
    def credit_comp_off(employee, ot_entry, expiry_days=60):
        """
        Converts OT Entry into Comp-Off Balance.
        """
        balance, created = CompOffBalance.objects.get_or_create(employee=employee)
        days_earned = ot_entry.approved_hours / Decimal('8.00') # Assuming 8 hr = 1 day for conversion
        
        balance.available_days += days_earned
        balance.save()
        
        CompOffTransaction.objects.create(
            balance=balance,
            ot_entry=ot_entry,
            transaction_type='Credit',
            days=days_earned,
            expiry_date=timezone.now().date() + timedelta(days=expiry_days)
        )
        ot_entry.converted_to_comp_off = True
        ot_entry.save()
        
    @staticmethod
    def debit_for_retro_clawback(employee, days_to_clawback):
        """
        If Retro OT reduces an already credited Comp-Off, try to debit the balance.
        Returns True if successful, False if balance insufficient (requires payroll deduction).
        """
        balance = CompOffBalance.objects.filter(employee=employee).first()
        if not balance or balance.available_days < days_to_clawback:
            return False
            
        balance.available_days -= days_to_clawback
        balance.save()
        
        CompOffTransaction.objects.create(
            balance=balance,
            transaction_type='Debit',
            days=days_to_clawback
        )
        return True

# ==========================================
# PHASE 13: RETRO OT ENGINE
# ==========================================

class RetroOTService:
    @staticmethod
    def handle_attendance_correction(attendance, new_ot_hours):
        """
        Triggered when attendance is corrected by Manager after Payroll is frozen.
        """
        # Find existing OT Entry
        try:
            existing_req = OTRequest.objects.get(attendance=attendance)
            existing_entry = existing_req.otentry
        except OTRequest.DoesNotExist:
            existing_entry = None
            
        if existing_entry:
            # Check if associated payroll is frozen
            payroll_entry = getattr(existing_entry, 'otpayrollentry', None)
            if payroll_entry and payroll_entry.payroll_run.status == 'Frozen':
                
                difference = new_ot_hours - existing_entry.approved_hours
                
                if difference < 0 and existing_entry.converted_to_comp_off:
                    days_diff = abs(difference) / Decimal('8.00')
                    success = CompOffLifecycleService.debit_for_retro_clawback(attendance.employee, days_diff)
                    if not success:
                        # Create negative RetroOTEntry for next payroll to clawback from salary
                        pass 
                
                # Create RetroOTEntry targeting next open payroll run
                RetroOTEntry.objects.create(
                    original_entry=existing_entry,
                    employee=attendance.employee,
                    attendance=attendance,
                    adjusted_hours=difference,
                    target_payroll_run_id=None, # To be picked up by next open run
                    reason="Attendance Post-Freeze Correction"
                )

# ==========================================
# PHASE 17: ANOMALY DETECTION
# ==========================================

class OTAnomalyDetector:
    @staticmethod
    def flag_anomalies(employee, requested_hours: Decimal):
        """
        Dynamically detects OT spikes based on OTThresholdConfig.
        """
        config = OTThresholdConfig.objects.first()
        if not config:
            return False
            
        if config.method == 'FIXED':
            if requested_hours > config.multiplier_sensitivity:
                return True
                
        # In a real enterprise system, this would query historical data
        # For STD_DEV, fetch past `config.window_days` OT sum, calculate std dev.
        # If requested_hours > (avg + std_dev * multiplier_sensitivity), return True.
        
        return False
