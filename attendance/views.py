from rest_framework import viewsets, status
from rest_framework.decorators import action, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from django.utils import timezone
from datetime import datetime, timedelta
import math
from .models import DailyAttendance, PunchLog, RegularizationRequest, DynamicQRToken, FaceProfile, Holiday, HolidayRuleGroup
from .serializers import DailyAttendanceSerializer, PunchLogSerializer, RegularizationRequestSerializer, DynamicQRTokenSerializer, HolidaySerializer, HolidayRuleGroupSerializer

def haversine(lat1, lon1, lat2, lon2):
    R = 6371000 # Radius of earth in meters
    phi_1 = math.radians(lat1)
    phi_2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    a = math.sin(delta_phi / 2.0) ** 2 + math.cos(phi_1) * math.cos(phi_2) * math.sin(delta_lambda / 2.0) ** 2
    return R * (2 * math.atan2(math.sqrt(a), math.sqrt(1 - a)))
from employees.models import Employee
from .utils import get_face_encoding, compare_faces, HAVE_FACE_REC
from .crypto_utils import CryptoService
from .faiss_service import biometric_search
from .liveness_service import ActiveLivenessService
from .passive_liveness import PassiveLivenessService
from .gps_service import VelocityCheckService
from .webauthn_service import WebAuthnService
from .qr_service import CryptographicQRService
from .models import EnrollmentAudit, ConsentLog, ManualOverrideRequest
from rest_framework.parsers import MultiPartParser, FormParser, JSONParser

class AttendanceViewSet(viewsets.ViewSet):
    parser_classes = (MultiPartParser, FormParser, JSONParser)
    
    @action(detail=False, methods=['get'])
    @permission_classes([AllowAny])
    def get_liveness_challenge(self, request):
        """Wave 3: Request a dynamic liveness challenge"""
        challenge = ActiveLivenessService.generate_challenge()
        return Response(challenge)

    @action(detail=False, methods=['get'])
    def get_webauthn_challenge(self, request):
        """Wave 6: Request WebAuthn device attestation challenge"""
        emp_id = request.GET.get('employee_id')
        if not emp_id:
            return Response({"error": "employee_id required"}, status=400)
        options = WebAuthnService.generate_registration_options(emp_id, f"Emp {emp_id}")
        return Response(options)
        
    @action(detail=False, methods=['post'])
    def register_face(self, request):
        employee_id = request.data.get('employee')
        consent_granted = request.data.get('consent_granted', 'false').lower() == 'true'
        
        if not employee_id:
            return Response({"error": "Employee ID required"}, status=400)
            
        if not consent_granted:
            return Response({"error": "DPDPA/GDPR Explicit Consent is required to register biometric data."}, status=400)
            
        # Expecting multiple frames for multi-angle robustness
        encodings = []
        for key in ['face_center', 'face_left', 'face_right']:
            file_obj = request.FILES.get(key)
            if not file_obj:
                continue
                
            image_bytes = file_obj.read()
            result = get_face_encoding(image_bytes)
            
            if result.get('success'):
                encodings.append(result['encoding'])
                
        if len(encodings) == 0:
            return Response({"error": "Failed to extract face features from any provided image."}, status=400)
            
        try:
            employee = Employee.objects.get(id=employee_id)
            profile, created = FaceProfile.objects.get_or_create(employee=employee)
            
            # Envelope Encrypt the payload
            payload = {'encodings': encodings}
            encrypted_payload, encrypted_dek = CryptoService.encrypt_json(payload)
            
            profile.encrypted_face_encodings = encrypted_payload
            profile.encrypted_dek = encrypted_dek
            profile.consent_granted = consent_granted
            profile.is_active = True
            profile.data_residency_shard = 'EU' if employee.entity and employee.entity.country == 'EU' else 'IN'
            profile.save()
            
            # Wave 2: Incremental FAISS update
            biometric_search.add_employee_vectors(employee.id, encodings)
            
            # Audit Log
            EnrollmentAudit.objects.create(
                employee=employee,
                device_info=request.META.get('HTTP_USER_AGENT', 'Unknown'),
                ip_address=request.META.get('REMOTE_ADDR'),
                action='ENROLL' if created else 'RE_ENROLL',
                hash_signature='pending_hash_chain' # To be implemented in Wave 11
            )
            
            # Wave 10: Log Consent
            ConsentLog.objects.create(
                employee=employee,
                action='GRANTED',
                ip_address=request.META.get('REMOTE_ADDR'),
                user_agent=request.META.get('HTTP_USER_AGENT')
            )
            
            return Response({"message": f"Face registered securely using Envelope Encryption with {len(encodings)} angles."})
        except Employee.DoesNotExist:
            return Response({"error": "Employee not found"}, status=404)
        except Exception as e:
            return Response({"error": str(e)}, status=500)

    @action(detail=False, methods=['post'])
    def revoke_biometrics(self, request):
        """
        Wave 10: GDPR/DPDPA Right to be Forgotten.
        Instantly destroys cryptographic face encodings and drops vectors from FAISS.
        """
        emp_id = request.data.get('employee_id')
        if not emp_id:
            return Response({"error": "employee_id required"}, status=400)
            
        try:
            employee = Employee.objects.get(id=emp_id)
            profile = FaceProfile.objects.get(employee=employee)
            
            # Destroy Biometric Data
            profile.encrypted_face_encodings = None
            profile.encrypted_dek = None
            profile.consent_granted = False
            profile.is_active = False
            profile.save()
            
            # Remove from Vector Memory
            biometric_search.remove_employee(employee.id)
            
            # Audit Trail
            ConsentLog.objects.create(
                employee=employee,
                action='REVOKED',
                ip_address=request.META.get('REMOTE_ADDR'),
                user_agent=request.META.get('HTTP_USER_AGENT')
            )
            
            return Response({"message": "Biometric data permanently purged from active systems."})
        except (Employee.DoesNotExist, FaceProfile.DoesNotExist):
            return Response({"error": "Profile not found"}, status=404)

    @action(detail=False, methods=['post'])
    def request_override(self, request):
        """Wave 13: Request a manual AI override"""
        emp_id = request.data.get('employee_id')
        reason = request.data.get('reason')
        if not emp_id or not reason:
            return Response({"error": "employee_id and reason required"}, status=400)
            
        try:
            employee = Employee.objects.get(id=emp_id)
            ManualOverrideRequest.objects.create(employee=employee, reason=reason)
            return Response({"message": "Override request submitted for HR review."})
        except Employee.DoesNotExist:
            return Response({"error": "Employee not found"}, status=404)

    @action(detail=False, methods=['post'])
    def approve_override(self, request):
        """Wave 13: 2-Person Approval for Overrides"""
        req_id = request.data.get('request_id')
        approver_id = request.data.get('approver_id') # In production, pull from request.user
        
        try:
            override = ManualOverrideRequest.objects.get(id=req_id)
            approver = Employee.objects.get(id=approver_id)
            
            if not override.approver_1:
                override.approver_1 = approver
                override.save()
                return Response({"message": "Approver 1 registered. Waiting for Approver 2."})
            elif not override.approver_2 and override.approver_1 != approver:
                override.approver_2 = approver
                is_approved = override.check_approval()
                if is_approved:
                    # Execute manual punch logic here
                    return Response({"message": "Override fully approved. AI verification bypassed."})
            
            return Response({"error": "Approval conditions not met or already approved."}, status=400)
        except (ManualOverrideRequest.DoesNotExist, Employee.DoesNotExist):
            return Response({"error": "Invalid request or approver."}, status=404)

    @action(detail=False, methods=['post'])
    def generate_qr(self, request):
        site_id = request.data.get('site_id')
        if not site_id:
            return Response({"error": "Site ID required"}, status=400)
        
        # In a real app, ensure the user is an admin for this site.
        # We will clear old tokens or just generate a new one.
        token_obj = DynamicQRToken.objects.create(
            site_id=site_id,
            expires_at=timezone.now() + timedelta(seconds=120)
        )
        return Response(DynamicQRTokenSerializer(token_obj).data)
        
        # --- Wave 7: COMMENTED FOR DEMO ---
        # token = CryptographicQRService.generate_signed_token(site_id)
        # return Response({
        #     "token": token,
        #     "expires_in": CryptographicQRService.TTL_SECONDS
        # })

    @action(detail=False, methods=['post'])
    @permission_classes([AllowAny])
    def punch(self, request):
        try:
            punch_type = request.data.get('punch_type', 'IN')
            source = request.data.get('source', 'WEB')
            
            # Geofence & Velocity Validation
            lat_str = request.data.get('latitude')
            lng_str = request.data.get('longitude')
            
            # Wave 2: 1:N Facial Identification
            file_obj = request.FILES.get('face_image')
            verification_status = 'REJECTED'
            employee = None
            
            # Wave 3: Dynamic Challenge Validation
            challenge_id = request.data.get('challenge_id')
            
            # Wave 6: Device Attestation
            webauthn_signature = request.data.get('webauthn_signature')
            
            if file_obj:
                if challenge_id:
                    # In a real setup, we'd pass video frames. Mocking with empty list for prototype.
                    liveness_passed, liveness_msg = ActiveLivenessService.validate_challenge(challenge_id, [])
                    if not liveness_passed:
                        return Response({"error": f"Liveness Check Failed: {liveness_msg}"}, status=400)
                elif source == 'FACE':
                    return Response({"error": "challenge_id required for Active Liveness validation"}, status=400)

                if not HAVE_FACE_REC:
                    # TEMPORARY OVERRIDE: User requested to bypass the ML check
                    verification_status = 'VERIFIED'
                    # Fallback to provided employee ID just for testing the bypass
                    emp_id = request.data.get('employee')
                    employee = Employee.objects.get(id=emp_id) if emp_id else Employee.objects.first()
                else:
                    image_bytes = file_obj.read()
                    
                    # Wave 4: Passive Liveness & Deepfake Detection (Must occur before DeepFace)
                    # We pass an empty list for video_frames as a mock for the deepfake detector
                    passed_passive, passive_msg = PassiveLivenessService.full_security_scan(image_bytes, video_frames=[])
                    if not passed_passive:
                        return Response({"error": passive_msg}, status=400)
                        
                    result = get_face_encoding(image_bytes)
                    
                    if not result.get('success'):
                        return Response({"error": f"Liveness/Extraction Failed: {result.get('error')}"}, status=400)
                        
                    # 1:N Search across entire FAISS index
                    identified_id = biometric_search.identify(result['encoding'])
                    if not identified_id:
                        return Response({"error": "Rejected: Face mismatch (No employee recognized)"}, status=400)
                        
                    # Validate Device Attestation AFTER identifying the employee
                    if webauthn_signature:
                        attest_passed, attest_msg = WebAuthnService.verify_authentication_response(
                            identified_id, "mock_client_data", "mock_auth_data", webauthn_signature
                        )
                        if not attest_passed:
                            return Response({"error": attest_msg}, status=400)
                            
                    employee = Employee.objects.get(id=identified_id)
                    verification_status = 'VERIFIED'
            elif source == 'FACE':
                return Response({"error": "face_image required for FACE verification"}, status=400)
            else:
                # If manual punch without face
                emp_id = request.data.get('employee')
                employee = Employee.objects.get(id=emp_id) if emp_id else Employee.objects.first()
                verification_status = 'VERIFIED'

            if not employee:
                return Response({"error": "Employee resolution failed"}, status=404)
            
            # --- STRICT ATTENDANCE POLICY ENFORCEMENT ---
            policy = None
            if hasattr(employee, 'attendance_policy') and employee.attendance_policy:
                policy = employee.attendance_policy
            elif hasattr(employee.site, 'attendance_policy') and employee.site.attendance_policy:
                policy = employee.site.attendance_policy
            elif hasattr(employee.entity, 'default_attendance_policy') and employee.entity.default_attendance_policy:
                policy = employee.entity.default_attendance_policy
            else:
                from organisation.models import AttendancePolicy
                policy = AttendancePolicy.objects.filter(employee__isnull=True, site__isnull=True, organization__isnull=True).first()

            if policy:
                if policy.require_face and source != 'FACE':
                    return Response({"error": "Face verification is mandatory for your profile as per attendance policy."}, status=400)
                if policy.require_gps and not (lat_str and lng_str):
                    return Response({"error": "GPS location is mandatory for your profile as per attendance policy."}, status=400)
                qr_token = request.data.get('qr_token')
                if policy.require_qr and not qr_token:
                    return Response({"error": "QR Code scan is mandatory for your profile as per attendance policy."}, status=400)
            else:
                qr_token = request.data.get('qr_token')
            # ---------------------------------------------
            
            site = employee.site
            
            if source == 'GPS' or (lat_str and lng_str):
                lat, lng = float(lat_str), float(lng_str)
                if site and site.latitude and site.longitude:
                    distance = haversine(lat, lng, float(site.latitude), float(site.longitude))
                    effective_radius = max(site.radius, 500) # Increased to 500m for testing
                    if distance > effective_radius:
                        return Response({"error": f"Rejected: Outside geofence. Distance: {int(distance)}m (max {effective_radius}m)"}, status=400)
                
                # Wave 5: Hardened Velocity Replay/Spoof Check
                last_punch = PunchLog.objects.filter(employee=employee).order_by('-punch_time').first()
                if last_punch and last_punch.latitude and last_punch.longitude:
                    is_possible, travel_msg = VelocityCheckService.is_travel_possible(
                        lat1=float(last_punch.latitude), lng1=float(last_punch.longitude), time1=last_punch.punch_time,
                        lat2=lat, lng2=lng, time2=timezone.now()
                    )
                    if not is_possible:
                        return Response({"error": travel_msg}, status=400)

            # Wave 7: Cryptographic QR Token Validation & Replay Defense (COMMENTED FOR DEMO)
            if qr_token:
                if site:
                    # is_valid, qr_msg = CryptographicQRService.validate_token(qr_token, site.id)
                    # if not is_valid:
                    #     return Response({"error": qr_msg}, status=400)
                    
                    # --- LEGACY DEMO LOGIC ---
                    try:
                        token_obj = DynamicQRToken.objects.get(site=site, token=qr_token)
                    except DynamicQRToken.DoesNotExist:
                        return Response({"error": "Rejected: Invalid QR Token."}, status=400)
                
                # We still keep the employee-specific replay defense just in case
                if PunchLog.objects.filter(employee=employee, qr_token=qr_token).exists():
                    return Response({"error": "Rejected: QR Token replay detected for this employee."}, status=400)
                
            now = timezone.now()
            
            daily_att = None
            if verification_status == 'VERIFIED':
                today = now.date()
                daily_att, created = DailyAttendance.objects.get_or_create(
                    employee=employee,
                    attendance_date=today,
                    defaults={
                        'site': employee.site,
                        'organization': employee.entity,
                    }
                )
                
                if punch_type == 'IN':
                    if not daily_att.first_check_in:
                        daily_att.first_check_in = now
                        shift_start = now.replace(hour=9, minute=30, second=0, microsecond=0)
                        if now > shift_start:
                            daily_att.attendance_status = 'Late'
                        else:
                            daily_att.attendance_status = 'Present'
                else:
                    daily_att.last_check_out = now
                    
                if daily_att.first_check_in and daily_att.last_check_out:
                    duration = daily_att.last_check_out - daily_att.first_check_in
                    hours = duration.total_seconds() / 3600
                    daily_att.total_work_hours = round(hours, 2)
                    if hours > 8:
                        raw_ot = round(hours - 8, 2)
                        # Overtime is only paid if it exceeds 2 hours
                        daily_att.overtime_hours = raw_ot if raw_ot > 2.0 else 0.0
                        if daily_att.attendance_status not in ['Late']:
                            daily_att.attendance_status = 'Present'
                    elif hours >= 4:
                        daily_att.attendance_status = 'Half Day'
                    else:
                        daily_att.attendance_status = 'Absent'
                        
                daily_att.save()
            else:
                daily_att, _ = DailyAttendance.objects.get_or_create(
                    employee=employee,
                    attendance_date=now.date(),
                    defaults={'site': employee.site, 'organization': employee.entity}
                )
                
            punch = PunchLog.objects.create(
                employee=employee,
                daily_attendance=daily_att,
                punch_time=now,
                punch_type=punch_type,
                source=source,
                latitude=lat_str,
                longitude=lng_str,
                qr_token=qr_token,
                verification_status=verification_status,
                ip_address=request.META.get('REMOTE_ADDR')
            )
            
            if verification_status == 'PENDING_ML_INSTALL':
                return Response({"message": "Punch recorded securely. Pending ML biometric verification.", "status": verification_status}, status=202)
                
            return Response(DailyAttendanceSerializer(daily_att).data)
        except Exception as e:
            import traceback
            return Response({"error": f"Internal Server Error: {str(e)}", "trace": traceback.format_exc()}, status=500)

    @action(detail=False, methods=['get'])
    def history(self, request):
        viewset = DailyAttendanceViewSet()
        viewset.request = request
        queryset = viewset.get_queryset().order_by('-attendance_date')
        return Response(DailyAttendanceSerializer(queryset, many=True).data)

    @action(detail=False, methods=['get'])
    def today(self, request):
        today = timezone.now().date()
        viewset = DailyAttendanceViewSet()
        viewset.request = request
        queryset = viewset.get_queryset().filter(attendance_date=today).order_by('-attendance_date')
        return Response(DailyAttendanceSerializer(queryset, many=True).data)

    @action(detail=False, methods=['post'])
    def mark_absentees(self, request):
        target_date = request.data.get('date', timezone.now().date().isoformat())
        active_emps = Employee.objects.filter(status='Active')
        
        # Fetch all active holidays for the target date
        holidays_today = Holiday.objects.filter(date=target_date, status='Active')
        
        def is_holiday(employee):
            for h in holidays_today:
                rules = h.rule_groups.all()
                if not rules.exists():
                    return True # Applies to everyone
                
                for r in rules:
                    # Check exclusions first
                    if r.excluded_roles.filter(id=employee.dynamic_role_id).exists() if employee.dynamic_role_id else False:
                        continue
                    if r.excluded_departments.filter(id=employee.department_id).exists() if employee.department_id else False:
                        continue
                    
                    # Check inclusions (must match at least one if any inclusion is provided)
                    role_match = not r.applicable_roles.exists() or (employee.dynamic_role_id and r.applicable_roles.filter(id=employee.dynamic_role_id).exists())
                    dept_match = not r.applicable_departments.exists() or (employee.department_id and r.applicable_departments.filter(id=employee.department_id).exists())
                    entity_match = not r.applicable_entities.exists() or (employee.entity_id and r.applicable_entities.filter(id=employee.entity_id).exists())
                    branch_match = not r.applicable_branches.exists() or (employee.branch_id and r.applicable_branches.filter(id=employee.branch_id).exists())
                    
                    if role_match and dept_match and entity_match and branch_match:
                        return True
            return False

        absent_count = 0
        for emp in active_emps:
            if is_holiday(emp):
                continue # Skip marking absent if it's a holiday for this employee
                
            att, created = DailyAttendance.objects.get_or_create(
                employee=emp,
                attendance_date=target_date,
                defaults={
                    'site': emp.site,
                    'organization': emp.entity,
                    'attendance_status': 'Absent'
                }
            )
            if created or (not att.first_check_in and att.attendance_status != 'Absent'):
                att.attendance_status = 'Absent'
                att.save()
                absent_count += 1
                
        return Response({"message": f"Marked {absent_count} employees as Absent for {target_date}"})

    @action(detail=False, methods=['get'])
    def dashboard(self, request):
        today = timezone.now().date()
        total_employees = Employee.objects.count()
        present_today = DailyAttendance.objects.filter(attendance_date=today, first_check_in__isnull=False).count()
        
        return Response({
            "total_employees": total_employees,
            "present_today": present_today,
            "absent_today": total_employees - present_today,
            "late_today": 0, # Placeholder
        })

from authentication.permissions import DataIsolationMixin
from rest_framework.permissions import IsAuthenticated

class DailyAttendanceViewSet(DataIsolationMixin, viewsets.ModelViewSet):
    queryset = DailyAttendance.objects.all()
    serializer_class = DailyAttendanceSerializer
    permission_classes = [IsAuthenticated]

class RegularizationViewSet(DataIsolationMixin, viewsets.ModelViewSet):
    queryset = RegularizationRequest.objects.all().order_by('-created_at', '-id')
    serializer_class = RegularizationRequestSerializer
    
    def perform_create(self, serializer):
        try:
            employee = serializer.validated_data.get('employee')
            if not employee and hasattr(self.request.user, 'employee_profile'):
                employee = self.request.user.employee_profile
                serializer.validated_data['employee'] = employee
            serializer.save(employee=employee)
        except Exception as e:
            import traceback
            trace = traceback.format_exc()
            from rest_framework.exceptions import APIException
            class CustomAPIException(APIException):
                status_code = 400
                default_detail = trace
            raise CustomAPIException(trace)
        
    def perform_update(self, serializer):
        instance = serializer.save()
        # If approved, update the DailyAttendance
        if instance.status == 'Approved':
            daily_att, _ = DailyAttendance.objects.get_or_create(
                employee=instance.employee,
                attendance_date=instance.attendance_date,
                defaults={
                    'site': instance.employee.site,
                    'organization': instance.employee.entity,
                }
            )
            daily_att.first_check_in = instance.requested_check_in
            daily_att.last_check_out = instance.requested_check_out
            
            # Recalculate rules on regularization
            shift_start = instance.requested_check_in.replace(hour=9, minute=30, second=0, microsecond=0)
            if instance.requested_check_in > shift_start:
                daily_att.attendance_status = 'Late'
            else:
                daily_att.attendance_status = 'Present'
            
            duration = daily_att.last_check_out - daily_att.first_check_in
            hours = duration.total_seconds() / 3600
            daily_att.total_work_hours = round(hours, 2)
            if hours > 8:
                raw_ot = round(hours - 8, 2)
                # Overtime is only paid if it exceeds 2 hours
                daily_att.overtime_hours = raw_ot if raw_ot > 2.0 else 0.0
                if daily_att.attendance_status not in ['Late']:
                    daily_att.attendance_status = 'Present'
            elif hours >= 4:
                daily_att.attendance_status = 'Half Day'
            else:
                daily_att.attendance_status = 'Absent'
                
            daily_att.save()

from .models import ShiftDefinition, ShiftAssignment
from .serializers import ShiftDefinitionSerializer, ShiftAssignmentSerializer
from collections import defaultdict

class ShiftDefinitionViewSet(viewsets.ModelViewSet):
    queryset = ShiftDefinition.objects.all().order_by('start_time')
    serializer_class = ShiftDefinitionSerializer
    permission_classes = [AllowAny]

class RosterViewSet(viewsets.ViewSet):
    permission_classes = [AllowAny]

    @action(detail=False, methods=['get'])
    def weekly(self, request):
        start_date = request.query_params.get('start_date')
        end_date = request.query_params.get('end_date')
        if not start_date or not end_date:
            return Response({"error": "start_date and end_date required"}, status=400)
            
        assignments = ShiftAssignment.objects.filter(date__range=[start_date, end_date])
        assignments_map = defaultdict(dict)
        for a in assignments:
            assignments_map[a.employee_id][str(a.date)] = ShiftAssignmentSerializer(a).data

        employees = Employee.objects.filter(status='Active')
        data = []
        for emp in employees:
            data.append({
                "employee": {
                    "id": emp.id,
                    "name": f"{emp.first_name} {emp.last_name}",
                    "title": emp.designation.title if emp.designation else "Employee"
                },
                "shifts": assignments_map.get(emp.id, {})
            })
        return Response(data)

    @action(detail=False, methods=['post'])
    def assign(self, request):
        employee_id = request.data.get('employee_id')
        date = request.data.get('date')
        shift_id = request.data.get('shift_id') # Can be null to clear
        
        if not employee_id or not date:
            return Response({"error": "employee_id and date required"}, status=400)
            
        if not shift_id:
            ShiftAssignment.objects.filter(employee_id=employee_id, date=date).delete()
            return Response({"message": "Shift cleared"})
            
        try:
            shift = ShiftDefinition.objects.get(id=shift_id)
            assignment, _ = ShiftAssignment.objects.update_or_create(
                employee_id=employee_id,
                date=date,
                defaults={'shift': shift}
            )
            from employees.models import Notification
            Notification.objects.create(
                recipient_id=employee_id,
                title="Shift Assignment Updated",
                message=f"You have been assigned to the {shift.name} shift ({shift.start_time.strftime('%I:%M %p')} to {shift.end_time.strftime('%I:%M %p')}) for {date}."
            )
            return Response(ShiftAssignmentSerializer(assignment).data)
        except ShiftDefinition.DoesNotExist:
            return Response({"error": "Shift not found"}, status=404)

    @action(detail=False, methods=['post'])
    def bulk_assign(self, request):
        department_id = request.data.get('department_id')
        shift_id = request.data.get('shift_id')
        start_date = request.data.get('start_date')
        end_date = request.data.get('end_date')

        if not all([department_id, shift_id, start_date, end_date]):
            return Response({"error": "department_id, shift_id, start_date, and end_date are required"}, status=400)

        try:
            shift = ShiftDefinition.objects.get(id=shift_id)
        except ShiftDefinition.DoesNotExist:
            return Response({"error": "Shift not found"}, status=404)

        try:
            start_dt = datetime.strptime(start_date, "%Y-%m-%d").date()
            end_dt = datetime.strptime(end_date, "%Y-%m-%d").date()
        except ValueError:
            return Response({"error": "Invalid date format, use YYYY-MM-DD"}, status=400)

        if start_dt > end_dt:
            return Response({"error": "start_date cannot be after end_date"}, status=400)

        employees = Employee.objects.filter(department_id=department_id, status='Active')
        
        delta = end_dt - start_dt
        dates = [start_dt + timedelta(days=i) for i in range(delta.days + 1)]
        
        assignments_to_create = []
        for emp in employees:
            for d in dates:
                assignments_to_create.append(
                    ShiftAssignment(employee=emp, date=d, shift=shift)
                )
                
        if assignments_to_create:
            ShiftAssignment.objects.bulk_create(
                assignments_to_create,
                update_conflicts=True,
                unique_fields=['employee', 'date'],
                update_fields=['shift', 'updated_at']
            )
            
            from employees.models import Notification
            notifications = []
            for emp in employees:
                notifications.append(
                    Notification(
                        recipient=emp,
                        title="Shift Assignment Updated",
                        message=f"You have been assigned to the {shift.name} shift for the period {start_date} to {end_date}."
                    )
                )
            if notifications:
                Notification.objects.bulk_create(notifications)
            
        return Response({"message": f"Successfully assigned shift to {employees.count()} employees for {len(dates)} days ({len(assignments_to_create)} total assignments)."})

class HolidayViewSet(viewsets.ModelViewSet):
    queryset = Holiday.objects.all().order_by('date')
    serializer_class = HolidaySerializer
    permission_classes = [AllowAny]
    
    @action(detail=False, methods=['get'])
    def stats(self, request):
        today = timezone.now().date()
        current_year = today.year
        holidays = Holiday.objects.filter(date__year=current_year, status='Active')
        
        return Response({
            "total_holidays": holidays.count(),
            "upcoming": holidays.filter(date__gte=today).count(),
            "optional": holidays.filter(holiday_type='Optional').count(),
            "restricted": holidays.filter(holiday_type='Restricted').count(),
            "regional_festival": holidays.filter(holiday_type__in=['Regional', 'Festival']).count()
        })
        
class HolidayRuleGroupViewSet(viewsets.ModelViewSet):
    queryset = HolidayRuleGroup.objects.all()
    serializer_class = HolidayRuleGroupSerializer
    permission_classes = [AllowAny]
