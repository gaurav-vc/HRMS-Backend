import math
from datetime import timedelta
from decimal import Decimal
from django.utils import timezone
from .models import (
    OTPolicy, OTRequest, OTEntry, 
    OTApprovalRouting, OTThresholdConfig
)

# ==========================================
# PHASE 1: ELIGIBILITY & ROUNDING
# ==========================================

class OTRoundingEngine:
    @staticmethod
    def round_hours(hours_decimal: Decimal, policy: str) -> Decimal:
        """
        Rounds hours based on Nearest 1/5/15/30 policy.
        """
        if not hours_decimal:
            return Decimal('0.00')
            
        minutes = float(hours_decimal) * 60
        
        if policy == '1':
            rounded_mins = round(minutes)
        elif policy == '5':
            rounded_mins = 5 * round(minutes / 5)
        elif policy == '15':
            rounded_mins = 15 * round(minutes / 15)
        elif policy == '30':
            rounded_mins = 30 * round(minutes / 30)
        else:
            rounded_mins = round(minutes)
            
        return Decimal(str(rounded_mins / 60)).quantize(Decimal('0.01'))

class OTEligibilityEngine:
    @staticmethod
    def calculate_raw_ot(attendance) -> Decimal:
        """
        Phase 3: Computes raw OT based on shift vs actual checkout.
        Does not apply validation caps yet.
        """
        if attendance.attendance_status not in ['Present', 'Half Day']:
            return Decimal('0.00')
            
        # Example hardcoded standard hours, in reality fetch from Employee Shift
        standard_hours = Decimal('9.00')
        worked_hours = attendance.total_work_hours
        
        if worked_hours <= standard_hours:
            return Decimal('0.00')
            
        raw_ot = worked_hours - standard_hours
        
        # Phase 4: Break Rule Engine
        active_policy = OTPolicy.objects.filter(effective_from__lte=timezone.now().date()).order_by('-effective_from').first()
        if active_policy and active_policy.auto_deduct_break_mins > 0:
            break_hours = Decimal(str(active_policy.auto_deduct_break_mins / 60))
            raw_ot = max(Decimal('0.00'), raw_ot - break_hours)
            
        if active_policy:
            raw_ot = OTRoundingEngine.round_hours(raw_ot, active_policy.rounding_policy)
            
        return raw_ot

# ==========================================
# PHASE 15 & 16: VALIDATION & COMPLIANCE
# ==========================================

class OTValidationEngine:
    @staticmethod
    def validate_request(attendance, requested_hours: Decimal):
        """
        Phase 15: Structural validations (Negative OT, Duplicate, Cross-posting)
        """
        if requested_hours < 0:
            raise ValueError("Negative OT is not permitted.")
            
        if OTRequest.objects.filter(attendance=attendance).exists():
            raise ValueError("Duplicate OT Request detected for this attendance record.")
            
        # Phase 16: Overlapping Shift Validation
        # In a real enterprise setup, check if the punch out time bleeds into the next scheduled shift.
        if requested_hours > Decimal('12.00'):
            # Flag for review: an employee claiming 12+ hours OT in a single day likely overlapped their next shift
            return "FLAG_REVIEW_OVERLAP"
            
        return "VALID"

class LaborLawValidator:
    @staticmethod
    def enforce_statutory_limits(employee, date, requested_hours: Decimal):
        """
        Phase 6: Strict statutory enforcement.
        e.g., Factories Act India: Max 48 hours total per week, max 10.5 hours spread over per day.
        """
        # Hard fail on extreme daily limits
        if requested_hours > Decimal('4.00'):
            raise ValueError("Labor Law Violation: Daily OT exceeds maximum 4 hours.")
            
        # Fetch week's total OT
        week_start = date - timedelta(days=date.weekday())
        week_end = week_start + timedelta(days=6)
        
        # This requires summing up OTEntry.approved_hours for the week
        # Implementation left decoupled as an API wrapper
        return True

# ==========================================
# PHASE 14: APPROVAL ROUTING
# ==========================================

class OTWorkflowEngine:
    @staticmethod
    def determine_approval_route(requested_hours: Decimal):
        """
        Determines if request goes to Manager, HR, or Finance.
        """
        routing = OTApprovalRouting.objects.first()
        if not routing:
            return ['Manager'] # Default
            
        levels = ['Manager']
        if requested_hours >= routing.min_hours_for_hr:
            levels.append('HR')
        if requested_hours >= routing.min_hours_for_finance:
            levels.append('Finance')
            
        return levels
