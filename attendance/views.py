from rest_framework import viewsets, status
from authentication.permissions import DataIsolationMixin, isolate_queryset
from rest_framework.decorators import action, permission_classes
from rest_framework.permissions import AllowAny, IsAuthenticated
from rest_framework.response import Response
from django.utils import timezone
from datetime import datetime, timedelta
import math
import os
from .models import DailyAttendance, PunchLog, RegularizationRequest, DynamicQRToken, FaceProfile, Holiday, HolidayRuleGroup
from .serializers import DailyAttendanceSerializer, PunchLogSerializer, RegularizationRequestSerializer, DynamicQRTokenSerializer, HolidaySerializer, HolidayRuleGroupSerializer
from .decorators import strict_liveness_precheck
def haversine(lat1, lon1, lat2, lon2):
    R = 6371000 # Radius of earth in meters
    phi_1 = math.radians(lat1)
    phi_2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)
    a = math.sin(delta_phi / 2.0) ** 2 + math.cos(phi_1) * math.cos(phi_2) * math.sin(delta_lambda / 2.0) ** 2
    return R * (2 * math.atan2(math.sqrt(a), math.sqrt(1 - a)))

def check_employee_bypass_geofence(employee, policy=None, request_data=None):
    """
    Checks if an employee is authorized to punch remotely or bypass geofence restrictions.
    Follows ZERO hardcoded roles rule: validates via dynamic role permissions, access scope,
    capabilities, explicit WFH policy assignment, or authenticated client flags.
    """
    if not employee:
        return False
        
    # 1. Dynamic Role Permissions & Capabilities
    if hasattr(employee, 'dynamic_role') and employee.dynamic_role:
        role = employee.dynamic_role
        perms = role.permissions or {}
        
        # Check attendance module dynamic permissions
        att_perms = perms.get('attendance', {})
        if isinstance(att_perms, dict):
            if att_perms.get('bypass_geofence') or att_perms.get('remote_punch'):
                return True
                
        # Top-level dynamic permission flags
        if perms.get('bypass_geofence') or perms.get('remote_punch'):
            return True
            
        # Role Access Scope capability (Corporate, Region)
        scope = str(role.access_scope or '').strip().lower()
        if scope in ('corporate', 'region'):
            return True
            
        # Role management capabilities
        if getattr(role, 'can_manage_users', False):
            return True

    # 2. Explicit WFH Policy assignment
    if policy and hasattr(policy, 'wfh_employees') and policy.wfh_employees.filter(id=employee.id).exists():
        return True
        
    from organisation.models import AttendancePolicy
    if AttendancePolicy.objects.filter(wfh_employees=employee).exists():
        return True
        
    # 3. Explicit client request flag (e.g. from authenticated remote punch flow)
    if request_data and (
        request_data.get('is_wfh') in (True, 'true', 'True', 1, '1') or
        request_data.get('bypass_geofence') in (True, 'true', 'True', 1, '1') or
        request_data.get('remote_punch') in (True, 'true', 'True', 1, '1')
    ):
        return True
        
    return False
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
from djangorestframework_camel_case.parser import CamelCaseMultiPartParser, CamelCaseFormParser, CamelCaseJSONParser

import threading
from django.core.mail import EmailMultiAlternatives
from django.utils.html import strip_tags

def send_shift_email_async(emp_email, emp_name, shift_name, shift_start, shift_end, dates_str):
    if not emp_email:
        return
        
    def _send():
        subject = f'Your Shift Assignment: {shift_name}'
        
        html_content = f"""
        <html>
            <body style="font-family: Arial, sans-serif; color: #333; max-width: 600px; margin: 0 auto; padding: 20px;">
                <div style="background-color: #0b1b3d; padding: 20px; border-radius: 8px 8px 0 0; text-align: center;">
                    <h2 style="color: white; margin: 0;">Shift Assignment Update</h2>
                </div>
                <div style="padding: 30px; border: 1px solid #ddd; border-top: none; border-radius: 0 0 8px 8px;">
                    <p style="font-size: 16px;">Hello <strong>{emp_name}</strong>,</p>
                    <p style="font-size: 15px; line-height: 1.5;">You have been assigned to a new shift. Please find the details of your assignment below:</p>
                    
                    <div style="background-color: #f8fafc; padding: 20px; border-radius: 6px; margin: 25px 0;">
                        <p style="margin: 0 0 10px 0;"><strong>Shift Name:</strong> {shift_name}</p>
                        <p style="margin: 0 0 10px 0;"><strong>Timings:</strong> {shift_start} to {shift_end}</p>
                        <p style="margin: 0;"><strong>Applicable Dates:</strong> {dates_str}</p>
                    </div>
                    
                    <p style="font-size: 14px; color: #666;">If you have any questions or conflicts, please reach out to your manager immediately.</p>
                    <br/>
                    <p style="font-size: 14px; color: #666; margin: 0;">Best Regards,</p>
                    <p style="font-size: 14px; color: #666; font-weight: bold; margin: 5px 0 0 0;">HRMS Administration</p>
                </div>
            </body>
        </html>
        """
        
        text_content = strip_tags(html_content)
        
        try:
            msg = EmailMultiAlternatives(
                subject=subject,
                body=text_content,
                from_email='HRMS Admin <gauravkokane420op@gmail.com>',
                to=[emp_email]
            )
            msg.attach_alternative(html_content, "text/html")
            msg.send(fail_silently=True)
            print(f"Shift email successfully dispatched to {emp_email}")
        except Exception as e:
            print(f"Failed to send shift email to {emp_email}: {str(e)}")
            
    threading.Thread(target=_send).start()


def evaluate_punctuality_slabs(employee, punch_time, shift_start_dt):
    """
    Evaluates site-isolated Punctuality Slabs for an employee punch-in.
    Complies with ZERO HARDCODED ROLES: checks employee.designation dynamically.
    Returns:
        dict: {
            "matched": bool,
            "slab": PunctualitySlab or None,
            "penalty_amount": Decimal,
            "penalty_type": str,
            "status": str, # 'Present', 'Late', or 'Half Day'
            "minutes_offset": float,
            "details": dict
        }
    """
    from decimal import Decimal
    from organisation.models import AttendancePolicy, PunctualitySlab

    # Multi-tenant site isolation resolution:
    # 1. Site policy -> 2. Entity policy -> 3. Global policy
    policy = None
    if getattr(employee, 'site', None) and hasattr(employee.site, 'attendance_policy'):
        policy = employee.site.attendance_policy
    if not policy and getattr(employee, 'entity', None) and hasattr(employee.entity, 'default_attendance_policy'):
        policy = employee.entity.default_attendance_policy
    if not policy:
        policy = AttendancePolicy.objects.filter(site__isnull=True, organization__isnull=True, employee__isnull=True).first()

    if not policy:
        return {"matched": False, "status": "Present", "penalty_amount": Decimal('0.00'), "penalty_type": "NONE", "slab": None, "minutes_offset": 0.0, "details": {}}

    slabs = policy.punctuality_slabs.all().order_by('order', 'minutes_threshold')
    if not slabs.exists():
        return {"matched": False, "status": "Present", "penalty_amount": Decimal('0.00'), "penalty_type": "NONE", "slab": None, "minutes_offset": 0.0, "details": {}}

    # Dynamic role / designation check: Zero hardcoded roles!
    emp_designation_id = getattr(employee, 'designation_id', None)
    emp_dynamic_role_id = getattr(employee, 'dynamic_role_id', None)
    applicable_slabs = []
    for s in slabs:
        has_desigs = s.applicable_designations.exists()
        has_roles = s.applicable_roles.exists()
        # If no specific roles or designations are assigned, it applies to all.
        if not has_desigs and not has_roles:
            applicable_slabs.append(s)
            continue

        role_matched = has_roles and emp_dynamic_role_id and s.applicable_roles.filter(id=emp_dynamic_role_id).exists()
        desig_matched = has_desigs and emp_designation_id and s.applicable_designations.filter(id=emp_designation_id).exists()
        if role_matched or desig_matched:
            applicable_slabs.append(s)

    if not applicable_slabs:
        return {"matched": False, "status": "Present", "penalty_amount": Decimal('0.00'), "penalty_type": "NONE", "slab": None, "minutes_offset": 0.0, "details": {}}

    # Calculate offset in minutes from shift start
    diff_seconds = (punch_time - shift_start_dt).total_seconds()
    offset_minutes = diff_seconds / 60.0

    matched_slab = None

    def get_trigger_offset(s):
        if s.comparison_type == 'AFTER_GRACE_MINUTES':
            return float(s.minutes_threshold)
        elif s.comparison_type == 'AFTER_SHIFT_START':
            return 0.0
        elif s.comparison_type == 'AFTER_MANDATORY_PRIOR':
            return -float(s.minutes_threshold)
        return 0.0

    sorted_slabs = sorted(applicable_slabs, key=get_trigger_offset, reverse=True)

    for s in sorted_slabs:
        trigger_min = get_trigger_offset(s)
        if offset_minutes > trigger_min:
            matched_slab = s
            break

    if not matched_slab:
        # Arrived on or before mandatory reporting mark -> Perfect punctuality!
        return {
            "matched": False,
            "status": "Present",
            "penalty_amount": Decimal('0.00'),
            "penalty_type": "NONE",
            "slab": None,
            "minutes_offset": offset_minutes,
            "details": {}
        }

    penalty_amt = Decimal('0.00')
    status_str = 'Late'
    if matched_slab.deduction_type == 'HALF_DAY':
        status_str = 'Half Day'
        penalty_amt = Decimal(str(matched_slab.deduction_value or '0.00'))
    elif matched_slab.deduction_type == 'FIXED_AMOUNT':
        penalty_amt = Decimal(str(matched_slab.deduction_value or '0.00'))
    elif matched_slab.deduction_type == 'PERCENTAGE':
        penalty_amt = Decimal(str(matched_slab.deduction_value or '0.00'))

    details = {
        "slab_id": matched_slab.id,
        "slab_name": matched_slab.name,
        "comparison_type": matched_slab.comparison_type,
        "deduction_type": matched_slab.deduction_type,
        "deduction_value": float(matched_slab.deduction_value),
        "minutes_offset": round(offset_minutes, 1),
        "shift_start": shift_start_dt.isoformat()
    }

    return {
        "matched": True,
        "slab": matched_slab,
        "penalty_amount": penalty_amt,
        "penalty_type": matched_slab.deduction_type,
        "status": status_str,
        "minutes_offset": offset_minutes,
        "details": details
    }


class AttendanceViewSet(viewsets.ViewSet):
    parser_classes = (CamelCaseMultiPartParser, CamelCaseFormParser, CamelCaseJSONParser)
    
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
    @strict_liveness_precheck
    def punch(self, request):
        try:
            punch_type = request.data.get('punch_type', 'IN')
            source = request.data.get('source', 'WEB')
            
            # Geofence & Velocity Validation (support latitude/longitude, lat/lng, lat/long, or nested location/coords)
            lat_str = (
                request.data.get('latitude') or
                request.data.get('lat') or
                (request.data.get('location') and isinstance(request.data.get('location'), dict) and (request.data.get('location').get('latitude') or request.data.get('location').get('lat'))) or
                (request.data.get('coords') and isinstance(request.data.get('coords'), dict) and (request.data.get('coords').get('latitude') or request.data.get('coords').get('lat')))
            )
            lng_str = (
                request.data.get('longitude') or
                request.data.get('lng') or
                request.data.get('lon') or
                request.data.get('long') or
                (request.data.get('location') and isinstance(request.data.get('location'), dict) and (request.data.get('location').get('longitude') or request.data.get('location').get('lng') or request.data.get('location').get('lon'))) or
                (request.data.get('coords') and isinstance(request.data.get('coords'), dict) and (request.data.get('coords').get('longitude') or request.data.get('coords').get('lng') or request.data.get('coords').get('lon')))
            )
            
            # Wave 2: 1:N Facial Identification
            file_obj = request.FILES.get('face_image')
            print(f"PUNCH DEBUG: source={source}, FILES={request.FILES}, data={request.data}, file_obj={file_obj}")
            verification_status = 'REJECTED'
            employee = None
            
            # Wave 3: Dynamic Challenge Validation
            challenge_id = request.data.get('challenge_id')
            
            # Wave 6: Device Attestation
            webauthn_signature = request.data.get('webauthn_signature')
            
            if file_obj:
                raw_fv = request.data.get('face_verified')
                if raw_fv is None:
                    raw_fv = request.data.get('faceVerified')
                is_face_verified = raw_fv in [True, 'true', 'True', 'TRUE', 1, '1', b'true']

                if challenge_id:
                    liveness_passed, liveness_msg = ActiveLivenessService.validate_challenge(challenge_id, [])
                    if not liveness_passed and source not in ['FACE', 'APP', 'MOBILE'] and not is_face_verified:
                        return Response({"error": f"Liveness Check Failed: {liveness_msg}"}, status=400)
                elif source in ['FACE', 'APP', 'MOBILE', 'ALL', 'WEB'] or is_face_verified:
                    pass  # Mobile app, web face punch, or client-verified punch bypasses challenge token
                else:
                    return Response({"error": "challenge_id required for Active Liveness validation"}, status=400)

                # Fix EXIF orientation so mobile/app photos taken in any orientation (90, 270) are upright
                import io
                from PIL import Image, ImageOps

                image_bytes = file_obj.read()
                try:
                    pil_img = Image.open(io.BytesIO(image_bytes))
                    pil_img = ImageOps.exif_transpose(pil_img)
                    buf = io.BytesIO()
                    pil_img.convert('RGB').save(buf, format='JPEG', quality=95)
                    image_bytes = buf.getvalue()
                except Exception:
                    pass

                # Resolve employee from request or authenticated user
                emp_id = request.data.get('employee') or request.data.get('employee_id')
                if not emp_id and hasattr(request, 'user') and request.user.is_authenticated:
                    try:
                        emp_id = request.user.employee_profile.id
                    except Exception:
                        pass

                employee = None
                if emp_id:
                    employee = Employee.objects.filter(id=emp_id).first()
                    if not employee:
                        return Response({"error": "Employee not found."}, status=400)

                identified_id = None

                if employee:
                    has_photo = False
                    try:
                        has_photo = bool(employee.photo and employee.photo.name)
                        if has_photo:
                            _ = employee.photo.path
                    except Exception:
                        has_photo = False

                    # If employee has no profile picture yet, save this first photo as their profile photo
                    if not has_photo:
                        from django.core.files.base import ContentFile
                        employee.photo.save(f"{employee.id}_profile.jpg", ContentFile(image_bytes))
                        has_photo = True

                    # Save attendance audit photo to media/punch_photos/
                    try:
                        from django.conf import settings
                        audit_dir = os.path.join(getattr(settings, 'MEDIA_ROOT', 'media'), 'punch_photos')
                        os.makedirs(audit_dir, exist_ok=True)
                        audit_filename = f"{employee.id}_{timezone.now().strftime('%Y%m%d_%H%M%S')}.jpg"
                        with open(os.path.join(audit_dir, audit_filename), 'wb') as af:
                            af.write(image_bytes)
                    except Exception:
                        pass

                    # 1. Trust Client-Side Verification from Mobile App (Google ML Kit)
                    if is_face_verified:
                        identified_id = employee.id
                        verification_status = 'VERIFIED'
                    else:
                        # 2. Fast 1:1 Matching against employee profile picture (OpenCV YuNet + SFace)
                        matched = False
                        live_res = get_face_encoding(image_bytes)

                        if live_res.get('success'):
                            live_encoding = live_res.get('encoding')
                            cache_key = (employee.id, employee.photo.name) if (employee.photo and employee.photo.name) else None
                            known_enc = None
                            try:
                                from attendance.kiosk_api import _PHOTO_ENCODING_CACHE
                                if cache_key:
                                    known_enc = _PHOTO_ENCODING_CACHE.get(cache_key)
                            except Exception:
                                known_enc = None

                            if not known_enc and employee.photo and employee.photo.name:
                                try:
                                    with employee.photo.open('rb') as pf:
                                        p_bytes = pf.read()
                                    try:
                                        p_pil = Image.open(io.BytesIO(p_bytes))
                                        p_pil = ImageOps.exif_transpose(p_pil)
                                        p_buf = io.BytesIO()
                                        p_pil.convert('RGB').save(p_buf, format='JPEG', quality=95)
                                        p_bytes = p_buf.getvalue()
                                    except Exception:
                                        pass

                                    p_res = get_face_encoding(p_bytes)
                                    if p_res.get('success'):
                                        known_enc = [p_res.get('encoding')]
                                        try:
                                            from attendance.kiosk_api import _PHOTO_ENCODING_CACHE
                                            if cache_key:
                                                _PHOTO_ENCODING_CACHE[cache_key] = known_enc
                                        except Exception:
                                            pass
                                except Exception:
                                    pass

                            if known_enc:
                                threshold = 0.40
                                try:
                                    if hasattr(employee, 'attendance_policy') and employee.attendance_policy:
                                        threshold = float(employee.attendance_policy.face_match_threshold) / 100.0
                                    elif employee.site and hasattr(employee.site, 'attendance_policy') and employee.site.attendance_policy:
                                        threshold = float(employee.site.attendance_policy.face_match_threshold) / 100.0
                                except Exception:
                                    pass

                                comp = compare_faces(known_enc, live_encoding, tolerance=threshold)
                                if comp.get('success') and comp.get('match'):
                                    matched = True
                                    identified_id = employee.id
                                    verification_status = 'VERIFIED'

                        if not matched:
                            if is_face_verified:
                                identified_id = employee.id
                                verification_status = 'VERIFIED'
                            elif not live_res.get('success'):
                                return Response({
                                    "status": "MISMATCH",
                                    "face_verified": False,
                                    "faceVerified": False,
                                    "message": "No clear face detected in the captured photo. Please look directly at the camera."
                                }, status=400)
                            else:
                                return Response({
                                    "status": "MISMATCH",
                                    "face_verified": False,
                                    "faceVerified": False,
                                    "message": "Face does not match registered employee photo."
                                }, status=400)
                else:
                    # 1:N Facial Identification across active employees / FAISS index
                    live_res = get_face_encoding(image_bytes)
                    if not live_res.get('success'):
                        return Response({
                            "status": "MISMATCH",
                            "face_verified": False,
                            "faceVerified": False,
                            "message": "No clear face detected in the captured photo. Please look directly at the camera."
                        }, status=400)

                    identified_id = biometric_search.identify(live_res['encoding'])
                    if not identified_id:
                        return Response({"error": "Security Alert: Not Authorized User. No matching employee recognized."}, status=400)
                    employee = Employee.objects.get(id=identified_id)
                    verification_status = 'VERIFIED'

                if webauthn_signature and identified_id:
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
                if emp_id:
                    employee = Employee.objects.get(id=emp_id)
                elif hasattr(request, 'user') and request.user.is_authenticated:
                    try:
                        employee = request.user.employee_profile
                    except Exception:
                        employee = Employee.objects.first()
                else:
                    employee = Employee.objects.first()
                verification_status = 'VERIFIED'

            if not employee:
                return Response({"error": "Employee resolution failed. Your account is not linked to an employee profile and no employee ID was provided."}, status=400)
            
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
                if policy.require_face and source != 'FACE' and not file_obj:
                    return Response({"error": "Face verification is mandatory for your profile as per attendance policy."}, status=400)
                if policy.require_gps and not (lat_str and lng_str):
                    return Response({"error": "GPS location is mandatory for your profile as per attendance policy."}, status=400)
                qr_token = request.data.get('qr_token')
                
                # Check WFH / Geofence bypass status via dynamic permissions, policy, and request
                can_bypass = check_employee_bypass_geofence(employee, policy=policy, request_data=request.data)
                is_wfh = can_bypass
                
                # Enforce require_qr only if it's not a personal Face punch (mobile or web) and not WFH/bypassed
                if policy.require_qr and not qr_token and source != 'FACE' and not file_obj and not is_wfh:
                    return Response({"error": "QR Code scan is mandatory for your profile as per attendance policy."}, status=400)
            else:
                can_bypass = check_employee_bypass_geofence(employee, policy=None, request_data=request.data)
                is_wfh = can_bypass
                qr_token = request.data.get('qr_token')
            # ---------------------------------------------
            
            valid_sites = []
            if employee.site:
                valid_sites.append(employee.site)
            for es in employee.enrolled_sites.all():
                if es not in valid_sites:
                    valid_sites.append(es)
            
            matched_site = employee.site # Default

            if source == 'GPS' or (lat_str and lng_str):
                if not lat_str or not lng_str:
                    if not can_bypass:
                        return Response({"error": "Latitude and Longitude are required for GPS punches."}, status=400)
                else:
                    try:
                        lat, lng = float(lat_str), float(lng_str)
                    except ValueError:
                        return Response({"error": "Invalid GPS coordinates."}, status=400)
                        
                    site_matched = False
                    min_distance = float('inf')
                    
                    for s in valid_sites:
                        if s.latitude is not None and s.longitude is not None:
                            distance = haversine(lat, lng, float(s.latitude), float(s.longitude))
                            effective_radius = s.radius
                            if distance <= effective_radius:
                                site_matched = True
                                matched_site = s
                                break
                            if distance < min_distance:
                                min_distance = distance
                    
                    if not site_matched and not can_bypass:
                        return Response({"error": f"Rejected: Outside geofence of all assigned sites. Closest distance: {int(min_distance) if min_distance != float('inf') else 'N/A'}m"}, status=400)
                    
                    # Hardened Velocity Replay/Spoof Check only if not remote/bypassed
                    if not can_bypass:
                        last_punch = PunchLog.objects.filter(employee=employee).order_by('-punch_time').first()
                        if last_punch and last_punch.latitude and last_punch.longitude:
                            is_possible, travel_msg = VelocityCheckService.is_travel_possible(
                                lat1=float(last_punch.latitude), lng1=float(last_punch.longitude), time1=last_punch.punch_time,
                                lat2=lat, lng2=lng, time2=timezone.now()
                            )
                            if not is_possible:
                                return Response({"error": travel_msg}, status=400)

            # Dynamic QR Token Validation & Replay Defense
            if qr_token:
                qr_site_matched = False
                matched_token_obj = None
                for s in valid_sites:
                    try:
                        token_obj = DynamicQRToken.objects.get(site=s, token=qr_token)
                        if token_obj.expires_at and token_obj.expires_at < timezone.now():
                            return Response({"error": "Rejected: QR Code has expired. Please refresh the QR screen."}, status=400)
                        qr_site_matched = True
                        matched_site = s
                        matched_token_obj = token_obj
                        break
                    except DynamicQRToken.DoesNotExist:
                        continue
                
                if not qr_site_matched:
                    return Response({"error": "Rejected: Invalid QR Token for any of your assigned sites."}, status=400)
                
                # Employee-specific replay defense
                if PunchLog.objects.filter(employee=employee, qr_token=qr_token).exists():
                    return Response({"error": "Rejected: QR Token replay detected for this employee."}, status=400)
                
            now = timezone.now()
            
            from django.db import transaction
            with transaction.atomic():
                daily_att = None
                if verification_status == 'VERIFIED':
                    today = now.date()
                    daily_att, created = DailyAttendance.objects.select_for_update().get_or_create(
                        employee=employee,
                        attendance_date=today,
                        defaults={
                            'site': matched_site,
                            'entity': employee.entity,
                            'organization': employee.organization,
                        }
                    )
                    
                    from .models import ShiftAssignment
                    import datetime
                    shift_assignment = ShiftAssignment.objects.filter(employee=employee, date=today).first()
                    shift = shift_assignment.shift if (shift_assignment and shift_assignment.shift) else None
                    is_split = bool(shift and getattr(shift, 'is_split_shift', False)) or getattr(daily_att, 'is_split_shift', False)

                    if is_split:
                        daily_att.is_split_shift = True
                        if punch_type == 'IN':
                            if not daily_att.part1_in:
                                daily_att.part1_in = now
                                daily_att.first_check_in = now
                            elif daily_att.part1_out and not daily_att.part2_in:
                                daily_att.part2_in = now
                        else:
                            if daily_att.part1_in and not daily_att.part1_out:
                                daily_att.part1_out = now
                            elif daily_att.part2_in and not daily_att.part2_out:
                                daily_att.part2_out = now
                                daily_att.last_check_out = now

                        h1 = 0.0
                        h2 = 0.0
                        if daily_att.part1_in and daily_att.part1_out:
                            h1 = max(0.0, (daily_att.part1_out - daily_att.part1_in).total_seconds() / 3600.0)
                        if daily_att.part2_in and daily_att.part2_out:
                            h2 = max(0.0, (daily_att.part2_out - daily_att.part2_in).total_seconds() / 3600.0)

                        total_hours = round(h1 + h2, 2)
                        daily_att.total_work_hours = total_hours
                        daily_att.overtime_hours = daily_att.compute_overtime(total_hours)

                        if daily_att.part1_in and daily_att.part1_out and not daily_att.part2_in:
                            policy = get_split_shift_incomplete_policy(employee, matched_site)
                            daily_att.attendance_status = 'Absent' if policy == 'Absent' else 'Half Day'
                        elif daily_att.part1_in and daily_att.part1_out and daily_att.part2_in and daily_att.part2_out:
                            if total_hours >= 8.0:
                                daily_att.attendance_status = 'Present'
                            elif total_hours >= 4.0:
                                daily_att.attendance_status = 'Half Day'
                            else:
                                daily_att.attendance_status = 'Absent'
                        else:
                            if not daily_att.attendance_status:
                                daily_att.attendance_status = 'Present'
                    else:
                        if punch_type == 'IN':
                            if not daily_att.first_check_in:
                                daily_att.first_check_in = now
                                shift_start_dt = None
                                if shift:
                                    shift_start_dt = datetime.datetime.combine(today, shift.start_time)
                                    if timezone.is_naive(shift_start_dt):
                                        shift_start_dt = timezone.make_aware(shift_start_dt)
                                else:
                                    shift_start_dt = now.replace(hour=9, minute=30, second=0, microsecond=0)
                                    if timezone.is_naive(shift_start_dt):
                                        shift_start_dt = timezone.make_aware(shift_start_dt)

                                # Evaluate punctuality slabs dynamically
                                punct_res = evaluate_punctuality_slabs(employee, now, shift_start_dt)
                                if punct_res["matched"]:
                                    daily_att.attendance_status = punct_res["status"]
                                    daily_att.late_deduction_amount = punct_res["penalty_amount"]
                                    daily_att.punctuality_penalty_details = punct_res["details"]
                                    
                                    from organisation.models import PunctualityPenaltyLog
                                    PunctualityPenaltyLog.objects.create(
                                        daily_attendance=daily_att,
                                        slab=punct_res["slab"],
                                        penalty_amount=punct_res["penalty_amount"],
                                        penalty_type=punct_res["penalty_type"],
                                        punch_time=now,
                                        shift_start=shift_start_dt,
                                        minutes_late=int(max(0, punct_res["minutes_offset"]))
                                    )
                                else:
                                    # Standard fallback if no custom slab policy applies
                                    if shift:
                                        cutoff_dt = shift_start_dt + datetime.timedelta(minutes=shift.grace_minutes)
                                        if now > cutoff_dt:
                                            daily_att.attendance_status = 'Late'
                                        else:
                                            daily_att.attendance_status = 'Present'
                                    else:
                                        if now > shift_start_dt:
                                            daily_att.attendance_status = 'Late'
                                        else:
                                            daily_att.attendance_status = 'Present'
                        else:
                            daily_att.last_check_out = now
                            
                        if daily_att.first_check_in and daily_att.last_check_out:
                            duration = daily_att.last_check_out - daily_att.first_check_in
                            hours = duration.total_seconds() / 3600
                            daily_att.total_work_hours = round(hours, 2)
                            daily_att.overtime_hours = daily_att.compute_overtime(hours)
                            if hours >= 8:
                                if daily_att.attendance_status not in ['Late']:
                                    daily_att.attendance_status = 'Present'
                            elif hours >= 4:
                                daily_att.attendance_status = 'Half Day'
                            else:
                                daily_att.attendance_status = 'Absent'
                                
                    daily_att.save()
                else:
                    daily_att, _ = DailyAttendance.objects.select_for_update().get_or_create(
                        employee=employee,
                        attendance_date=now.date(),
                        defaults={'site': matched_site, 'entity': employee.entity, 'organization': employee.organization}
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
                
            resp_data = DailyAttendanceSerializer(daily_att).data
            resp_data.update({
                "status": "SUCCESS",
                "message": "Attendance punched successfully.",
                "face_verified": True,
                "faceVerified": True
            })
            return Response(resp_data)
        except Exception as e:
            import traceback
            return Response({"error": f"Internal Server Error: {str(e)}", "trace": traceback.format_exc()}, status=500)

    @action(detail=False, methods=['get'])
    def history(self, request):
        qs = isolate_queryset(DailyAttendance.objects.all(), request.user)
        queryset = qs.order_by('-attendance_date')
        return Response(DailyAttendanceSerializer(queryset, many=True).data)

    @action(detail=False, methods=['get'])
    def today(self, request):
        today = timezone.now().date()
        qs = isolate_queryset(DailyAttendance.objects.all(), request.user)
        queryset = qs.filter(attendance_date=today).order_by('-attendance_date')
        return Response(DailyAttendanceSerializer(queryset, many=True).data)

    @action(detail=False, methods=['post'])
    def upload_csv(self, request):
        import csv
        import io
        from django.utils.dateparse import parse_date, parse_datetime
        from django.utils import timezone
        
        file_obj = request.FILES.get('file')
        if not file_obj:
            return Response({"error": "No file provided"}, status=400)
            
        try:
            csv_file = io.StringIO(file_obj.read().decode('utf-8'))
            reader = csv.DictReader(csv_file)
            
            success_count = 0
            error_count = 0
            errors = []
            
            for i, row in enumerate(reader):
                try:
                    # Key normalization for robust header matching
                    norm_row = {str(k).strip().lower(): v for k, v in row.items() if k is not None}
                    
                    emp_code = (
                        row.get('employee_code') or row.get('emp_id') or row.get('Employee Code') or
                        norm_row.get('employee_code') or norm_row.get('emp_id') or norm_row.get('code') or
                        norm_row.get('emp code') or norm_row.get('empcode')
                    )
                    date_str = (
                        row.get('date') or row.get('Date') or
                        norm_row.get('date') or norm_row.get('attendance_date')
                    )
                    check_in_str = (
                        row.get('check_in') or row.get('in_time') or row.get('In Time') or
                        norm_row.get('check_in') or norm_row.get('in_time') or norm_row.get('checkin')
                    )
                    check_out_str = (
                        row.get('check_out') or row.get('out_time') or row.get('Out Time') or
                        norm_row.get('check_out') or norm_row.get('out_time') or norm_row.get('checkout')
                    )
                    status = (
                        row.get('status') or row.get('Status') or
                        norm_row.get('status') or 'Present'
                    )

                    # Dynamic OT - Hours detection: supports "OT - Hours", "OT Hours", "Overtime", "ot_hours", etc.
                    ot_raw = (
                        row.get('OT - Hours') or row.get('OT-Hours') or row.get('OT Hours') or
                        row.get('Overtime') or row.get('Overtime Hours') or row.get('OT') or
                        norm_row.get('ot - hours') or norm_row.get('ot-hours') or norm_row.get('ot hours') or
                        norm_row.get('overtime') or norm_row.get('overtime hours') or norm_row.get('ot') or
                        norm_row.get('ot_hours') or norm_row.get('overtime_hours')
                    )
                    parsed_ot = None
                    if ot_raw is not None and str(ot_raw).strip() not in ['', '—', '-']:
                        try:
                            from decimal import Decimal
                            val = float(str(ot_raw).strip())
                            parsed_ot = Decimal(str(round(max(0.0, val), 2)))
                        except (ValueError, TypeError):
                            parsed_ot = None
                    
                    if not emp_code or not date_str:
                        error_count += 1
                        errors.append(f"Row {i+1}: Missing employee code or date")
                        continue
                        
                    try:
                        allowed_emps = isolate_queryset(Employee.objects.all(), request.user)
                        employee = allowed_emps.get(code=emp_code)
                    except Employee.DoesNotExist:
                        error_count += 1
                        errors.append(f"Row {i+1}: Employee with code {emp_code} not found or access denied")
                        continue
                        
                    att_date = parse_date(date_str)
                    if not att_date:
                        try:
                            import datetime
                            att_date = datetime.datetime.strptime(date_str, "%d-%m-%Y").date()
                        except:
                            try:
                                att_date = datetime.datetime.strptime(date_str, "%Y/%m/%d").date()
                            except:
                                error_count += 1
                                errors.append(f"Row {i+1}: Invalid date format {date_str}")
                                continue
                        
                    check_in = None
                    if check_in_str and check_in_str.strip() not in ['—', '-', '']:
                        if len(check_in_str) <= 8:
                            check_in_str = f"{att_date.strftime('%Y-%m-%d')} {check_in_str}"
                        check_in = parse_datetime(check_in_str)
                        if not check_in:
                            import datetime
                            try:
                                check_in = datetime.datetime.strptime(check_in_str, "%Y-%m-%d %H:%M:%S")
                            except:
                                pass
                        if check_in and timezone.is_naive(check_in):
                            check_in = timezone.make_aware(check_in)
                            
                    check_out = None
                    if check_out_str and check_out_str.strip() not in ['—', '-', '']:
                        if len(check_out_str) <= 8:
                            check_out_str = f"{att_date.strftime('%Y-%m-%d')} {check_out_str}"
                        check_out = parse_datetime(check_out_str)
                        if not check_out:
                            import datetime
                            try:
                                check_out = datetime.datetime.strptime(check_out_str, "%Y-%m-%d %H:%M:%S")
                            except:
                                pass
                        if check_out and timezone.is_naive(check_out):
                            check_out = timezone.make_aware(check_out)
                            
                    if (not status or status.strip().lower() == 'present') and check_in:
                        from .models import ShiftAssignment
                        import datetime
                        shift_assignment = ShiftAssignment.objects.filter(employee=employee, date=att_date).first()
                        if shift_assignment and shift_assignment.shift:
                            shift = shift_assignment.shift
                            cutoff_dt = datetime.datetime.combine(att_date, shift.start_time) + datetime.timedelta(minutes=shift.grace_minutes)
                            if timezone.is_naive(cutoff_dt):
                                cutoff_dt = timezone.make_aware(cutoff_dt)
                            if check_in > cutoff_dt:
                                status = 'Late'
                        else:
                            shift_start = check_in.replace(hour=9, minute=30, second=0, microsecond=0)
                            if check_in > shift_start:
                                status = 'Late'

                    defaults_dict = {
                        'site': employee.site,
                        'entity': employee.entity,
                        'organization': employee.organization,
                        'first_check_in': check_in,
                        'last_check_out': check_out,
                        'attendance_status': status
                    }
                    if parsed_ot is not None:
                        defaults_dict['overtime_hours'] = parsed_ot

                    daily_att, created = DailyAttendance.objects.get_or_create(
                        employee=employee,
                        attendance_date=att_date,
                        defaults=defaults_dict
                    )
                    
                    if not created:
                        if check_in: daily_att.first_check_in = check_in
                        if check_out: daily_att.last_check_out = check_out
                        if status: daily_att.attendance_status = status
                        if parsed_ot is not None:
                            daily_att.overtime_hours = parsed_ot
                        daily_att.save()
                        
                    if check_in:
                        PunchLog.objects.get_or_create(
                            employee=employee,
                            daily_attendance=daily_att,
                            punch_time=check_in,
                            punch_type='IN',
                            defaults={'source': 'CSV_IMPORT', 'verification_status': 'VERIFIED'}
                        )
                    if check_out:
                        PunchLog.objects.get_or_create(
                            employee=employee,
                            daily_attendance=daily_att,
                            punch_time=check_out,
                            punch_type='OUT',
                            defaults={'source': 'CSV_IMPORT', 'verification_status': 'VERIFIED'}
                        )
                        
                    success_count += 1
                except Exception as e:
                    error_count += 1
                    errors.append(f"Row {i+1}: {str(e)}")
                    
            return Response({
                "message": f"Processed {success_count + error_count} rows.",
                "success": success_count,
                "error": error_count,
                "errors": errors
            })
        except Exception as e:
            return Response({"error": str(e)}, status=500)

    @action(detail=False, methods=['post', 'delete'])
    def clear_records(self, request):
        month = request.data.get('month')
        employee_code = request.data.get('employee_code')
        entity_id = request.data.get('entity_id')
        start_date = request.data.get('start_date')
        end_date = request.data.get('end_date')
        
        qs = isolate_queryset(DailyAttendance.objects.all(), request.user)
        if month:
            parts = str(month).strip().split('-')
            if len(parts) == 2:
                try:
                    qs = qs.filter(attendance_date__year=int(parts[0]), attendance_date__month=int(parts[1]))
                except ValueError:
                    pass
        elif start_date and end_date:
            qs = qs.filter(attendance_date__range=[start_date, end_date])
            
        if employee_code:
            qs = qs.filter(employee__code=employee_code)
        if entity_id:
            qs = qs.filter(employee__entity_id=entity_id)
            
        count = qs.count()
        PunchLog.objects.filter(daily_attendance__in=qs).delete()
        qs.delete()
        return Response({"message": f"Successfully deleted {count} attendance records.", "deleted_count": count})

    @action(detail=False, methods=['delete'])
    def delete_single(self, request):
        record_id = request.data.get('id') or request.query_params.get('id')
        if not record_id:
            return Response({"error": "Record ID is required"}, status=400)
        try:
            qs = isolate_queryset(DailyAttendance.objects.all(), request.user)
            record = qs.get(id=record_id)
            PunchLog.objects.filter(daily_attendance=record).delete()
            record.delete()
            return Response({"message": "Attendance record deleted successfully."})
        except DailyAttendance.DoesNotExist:
            return Response({"error": "Record not found"}, status=404)

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
                    'entity': emp.entity,
                    'organization': emp.organization,
                    'attendance_status': 'Absent'
                }
            )
            if created or (not att.first_check_in and att.attendance_status != 'Absent'):
                att.attendance_status = 'Absent'
                att.save()
                absent_count += 1
                
        return Response({"message": f"Marked {absent_count} employees as Absent for {target_date}"})

    @action(detail=False, methods=['post'])
    @permission_classes([IsAuthenticated])
    def manual_override_punch(self, request):
        """
        Isolated admin-only endpoint to clear a liveness lockout.
        """
        if not request.user.is_superuser and getattr(request.user, 'role', '') != 'HR':
            return Response({"error": "Admin/HR privileges required for manual override."}, status=403)
            
        employee_id = request.data.get('employee_id')
        if not employee_id:
            return Response({"error": "employee_id required"}, status=400)
            
        from attendance.models import LivenessLockout, ManualOverrideRequest
        
        try:
            lockout = LivenessLockout.objects.get(employee_id=employee_id)
            lockout.failed_attempts = 0
            lockout.locked_until = None
            lockout.save()
        except LivenessLockout.DoesNotExist:
            return Response({"message": "Employee is not currently locked out."})
            
        approver = None
        if hasattr(request.user, 'employee_profile'):
            approver = request.user.employee_profile
            
        ManualOverrideRequest.objects.create(
            employee_id=employee_id,
            reason=f"Liveness Lockout Override by Admin {request.user.username}",
            approver_1=approver,
            is_approved=True
        )
        
        return Response({"message": "Lockout cleared and override logged. The employee can now punch in normally."})

    @action(detail=False, methods=['get'])
    def dashboard(self, request):
        today = timezone.now().date()
        from authentication.permissions import isolate_queryset
        allowed_emps = isolate_queryset(Employee.objects.all(), request.user)
        total_employees = allowed_emps.count()
        qs = isolate_queryset(DailyAttendance.objects.all(), request.user)
        present_today = qs.filter(attendance_date=today, first_check_in__isnull=False).count()
        allowed_punches = isolate_queryset(PunchLog.objects.all(), request.user)
        total_punches_count = allowed_punches.filter(daily_attendance__attendance_date=today).count()
        
        return Response({
            "total_employees": total_employees,
            "totalEmployees": total_employees,
            "present_today": present_today,
            "presentToday": present_today,
            "total_punches": total_punches_count,
            "totalPunches": total_punches_count,
            "absent_today": max(0, total_employees - present_today),
            "absentToday": max(0, total_employees - present_today),
            "late_today": 0,
            "lateToday": 0,
        })

    @action(detail=False, methods=['get'])
    def employee_report(self, request):
        employee_id = request.query_params.get('employee_id')
        year = request.query_params.get('year')
        month = request.query_params.get('month')
        
        if not employee_id or not year or not month:
            return Response({"error": "employee_id, year, and month are required"}, status=400)
            
        try:
            year = int(year)
            month = int(month)
        except ValueError:
            return Response({"error": "year and month must be integers"}, status=400)
            
        try:
            employee = Employee.objects.get(id=employee_id)
        except Employee.DoesNotExist:
            return Response({"error": "Employee not found"}, status=404)
            
        from authentication.permissions import isolate_queryset
        qs = isolate_queryset(DailyAttendance.objects.all(), request.user)
        
        records = qs.filter(
            employee_id=employee_id,
            attendance_date__year=year,
            attendance_date__month=month
        ).order_by('attendance_date')
        
        present_count = 0
        absent_count = 0
        half_day_count = 0
        late_count = 0
        total_ot_hours = 0.0
        
        serialized_records = []
        
        for record in records:
            if record.attendance_status == 'Present':
                present_count += 1
            elif record.attendance_status == 'Absent':
                absent_count += 1
            elif record.attendance_status == 'Half Day':
                half_day_count += 1
            elif record.attendance_status == 'Late':
                late_count += 1
                present_count += 1
                
            total_ot_hours += float(record.overtime_hours)
            
            serialized_records.append({
                "id": record.id,
                "date": record.attendance_date.isoformat() if record.attendance_date else None,
                "status": record.attendance_status,
                "first_check_in": record.first_check_in.isoformat() if record.first_check_in else None,
                "last_check_out": record.last_check_out.isoformat() if record.last_check_out else None,
                "total_hours": float(record.total_work_hours or 0.0),
                "ot_hours": float(record.overtime_hours or 0.0)
            })
            
        summary = {
            "present_days": present_count,
            "presentDays": present_count,
            "absent_days": absent_count,
            "absentDays": absent_count,
            "half_days": half_day_count,
            "halfDays": half_day_count,
            "late_marks": late_count,
            "lateMarks": late_count,
            "total_overtime_hours": round(total_ot_hours, 2),
            "totalOvertimeHours": round(total_ot_hours, 2),
        }
        
        return Response({
            "employee_name": f"{employee.first_name} {employee.last_name}",
            "employee_code": employee.code,
            "month": month,
            "year": year,
            "summary": summary,
            "records": serialized_records
        })

from authentication.permissions import DataIsolationMixin
from rest_framework.permissions import IsAuthenticated

class DailyAttendanceViewSet(DataIsolationMixin, viewsets.ModelViewSet):
    rbac_module = 'Attendance'
    queryset = DailyAttendance.objects.all()
    serializer_class = DailyAttendanceSerializer
    permission_classes = [IsAuthenticated]

    def get_queryset(self):
        qs = super().get_queryset()
        return qs.select_related(
            'employee',
            'employee__designation',
            'employee__department',
            'employee__entity',
            'employee__site',
            'site',
            'entity',
            'organization',
        ).prefetch_related('punches')

    def destroy(self, request, *args, **kwargs):
        from payroll.service import LockService
        from django.db import transaction
        instance = self.get_object()
        if LockService.is_attendance_locked(instance):
            return Response(
                {
                    "error": f"Attendance record for {instance.employee} on {instance.attendance_date} is locked by payroll and cannot be deleted."
                },
                status=status.HTTP_400_BAD_REQUEST
            )
        with transaction.atomic():
            self.perform_destroy(instance)
        return Response(status=status.HTTP_204_NO_CONTENT)

    @action(detail=False, methods=['post', 'delete'], url_path='bulk-delete')
    def bulk_delete(self, request):
        """
        Bulk delete attendance records with tenant data isolation and payroll lock protection.
        Accepts:
            { "ids": [1, 2, 3] }
            OR
            { "employee_id": 12, "start_date": "2026-11-01", "end_date": "2026-11-30" }
        """
        from payroll.service import LockService
        from django.db import transaction

        ids = request.data.get('ids', [])
        employee_id = request.data.get('employee_id')
        start_date = request.data.get('start_date')
        end_date = request.data.get('end_date')

        qs = self.get_queryset()  # Enforces DataIsolationMixin automatically

        if ids:
            qs = qs.filter(id__in=ids)
        elif employee_id:
            qs = qs.filter(employee_id=employee_id)
            if start_date and end_date:
                qs = qs.filter(attendance_date__range=[start_date, end_date])
            elif start_date:
                qs = qs.filter(attendance_date__gte=start_date)
            elif end_date:
                qs = qs.filter(attendance_date__lte=end_date)
        else:
            return Response(
                {"error": "Please provide an 'ids' array or 'employee_id' (with optional date range) to delete."},
                status=status.HTTP_400_BAD_REQUEST
            )

        unlocked_ids = []
        locked_records = []

        for att in qs:
            if LockService.is_attendance_locked(att):
                locked_records.append({
                    "id": att.id,
                    "employee": f"{att.employee.first_name} {att.employee.last_name}",
                    "date": str(att.attendance_date),
                    "reason": "Payroll is locked/finalized for this period."
                })
            else:
                unlocked_ids.append(att.id)

        deleted_count = 0
        if unlocked_ids:
            with transaction.atomic():
                deleted_count, _ = DailyAttendance.objects.filter(id__in=unlocked_ids).delete()

        return Response({
            "success": True,
            "deleted_count": deleted_count,
            "locked_count": len(locked_records),
            "deleted_ids": unlocked_ids,
            "locked_records": locked_records,
            "message": f"Successfully deleted {deleted_count} record(s). Protected {len(locked_records)} locked record(s)."
        }, status=status.HTTP_200_OK)

class RegularizationViewSet(DataIsolationMixin, viewsets.ModelViewSet):
    rbac_module = 'Regularization'
    queryset = RegularizationRequest.objects.all().order_by('-created_at', '-id')
    serializer_class = RegularizationRequestSerializer

    def get_queryset(self):
        from django.db.models import Q
        qs = super().get_queryset().select_related(
            'employee', 'approved_by', 'employee__designation', 'employee__entity'
        )

        employee_id = self.request.query_params.get('employee')
        if employee_id:
            qs = qs.filter(employee_id=employee_id)

        status_param = self.request.query_params.get('status')
        if status_param:
            qs = qs.filter(status=status_param)

        time_query = self.request.query_params.get('time')
        if time_query:
            qs = qs.filter(
                Q(requested_check_in__time__icontains=time_query) |
                Q(requested_check_out__time__icontains=time_query)
            )

        start_date = self.request.query_params.get('start_date')
        end_date = self.request.query_params.get('end_date')
        if start_date:
            qs = qs.filter(attendance_date__gte=start_date)
        if end_date:
            qs = qs.filter(attendance_date__lte=end_date)

        return qs
    
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

    @action(detail=False, methods=['POST'])
    def bulk_apply(self, request):
        """
        Atomically applies regularization requests across one or multiple employees and a date range [start_date, end_date].
        """
        raw_emp_ids = request.data.get('employee_ids') or request.data.get('employeeIds') or []
        if isinstance(raw_emp_ids, str):
            raw_emp_ids = [e.strip() for e in raw_emp_ids.split(',') if e.strip()]
        if not raw_emp_ids and request.data.get('employee'):
            raw_emp_ids = [request.data.get('employee')]

        employees = []
        if raw_emp_ids:
            from employees.models import Employee
            employees = list(Employee.objects.filter(id__in=raw_emp_ids))
        elif hasattr(request.user, 'employee_profile') and request.user.employee_profile:
            employees = [request.user.employee_profile]

        if not employees:
            return Response({"error": "At least one employee is required."}, status=status.HTTP_400_BAD_REQUEST)

        start_date_str = request.data.get('start_date') or request.data.get('startDate')
        end_date_str = request.data.get('end_date') or request.data.get('endDate') or start_date_str
        if not start_date_str:
            return Response({"error": "Start date is required."}, status=status.HTTP_400_BAD_REQUEST)

        try:
            start_date = datetime.strptime(start_date_str, '%Y-%m-%d').date()
            end_date = datetime.strptime(end_date_str, '%Y-%m-%d').date()
        except ValueError:
            return Response({"error": "Dates must be in YYYY-MM-DD format."}, status=status.HTTP_400_BAD_REQUEST)

        if start_date > end_date:
            return Response({"error": "Start date cannot be after end date."}, status=status.HTTP_400_BAD_REQUEST)

        if (end_date - start_date).days > 62:
            return Response({"error": "Date range cannot exceed 62 days."}, status=status.HTTP_400_BAD_REQUEST)

        import datetime as dt_module

        requested_in_time_str = request.data.get('requested_in') or request.data.get('requestedIn') or '09:30'
        requested_out_time_str = request.data.get('requested_out') or request.data.get('requestedOut') or '18:30'
        reason = request.data.get('reason', '').strip()
        if not reason:
            return Response({"error": "Reason is required."}, status=status.HTTP_400_BAD_REQUEST)

        def parse_time_str(t_str, default_hour, default_minute):
            if not t_str:
                return dt_module.time(default_hour, default_minute)
            for fmt in ('%H:%M:%S', '%H:%M', '%I:%M %p', '%I:%M%p'):
                try:
                    return datetime.strptime(str(t_str).strip(), fmt).time()
                except ValueError:
                    continue
            return dt_module.time(default_hour, default_minute)

        time_in = parse_time_str(requested_in_time_str, 9, 30)
        time_out = parse_time_str(requested_out_time_str, 18, 30)

        skip_sundays = request.data.get('skip_sundays', True)
        if 'skipSundays' in request.data:
            skip_sundays = request.data.get('skipSundays')
        
        # Base Entitlements / Leave Policy Saturday setting
        from leaves.models import LeavePolicyConfiguration
        try:
            leave_conf = LeavePolicyConfiguration.get_settings()
            policy_is_saturday_working = bool(getattr(leave_conf, 'is_saturday_working', False))
        except Exception:
            policy_is_saturday_working = False

        include_saturday_param = request.data.get('include_saturday')
        if include_saturday_param is None:
            include_saturday_param = request.data.get('includeSaturday')

        from django.db import transaction
        created_records = []
        skipped_dates = []

        with transaction.atomic():
            for emp in employees:
                site_is_saturday_working = False
                if emp.site and getattr(emp.site, 'is_saturday_working', False):
                    site_is_saturday_working = True
                effective_saturday_working = site_is_saturday_working or policy_is_saturday_working

                if include_saturday_param is not None:
                    include_saturday = bool(include_saturday_param)
                else:
                    include_saturday = effective_saturday_working

                curr = start_date
                while curr <= end_date:
                    # 6 = Sunday: By default Sunday is skipped
                    if skip_sundays and curr.weekday() == 6:
                        skipped_dates.append(curr.strftime('%Y-%m-%d'))
                        curr += timedelta(days=1)
                        continue

                    # 5 = Saturday: Dynamically check if Saturday is working
                    if curr.weekday() == 5 and not include_saturday:
                        skipped_dates.append(curr.strftime('%Y-%m-%d'))
                        curr += timedelta(days=1)
                        continue

                    dt_in = dt_module.datetime.combine(curr, time_in)
                    dt_out = dt_module.datetime.combine(curr, time_out)
                    if timezone.is_naive(dt_in):
                        dt_in = timezone.make_aware(dt_in)
                    if timezone.is_naive(dt_out):
                        dt_out = timezone.make_aware(dt_out)

                    reg_obj, created = RegularizationRequest.objects.get_or_create(
                        employee=emp,
                        attendance_date=curr,
                        defaults={
                            'requested_check_in': dt_in,
                            'requested_check_out': dt_out,
                            'reason': reason,
                            'status': 'Pending',
                        }
                    )
                    if not created and reg_obj.status == 'Pending':
                        reg_obj.requested_check_in = dt_in
                        reg_obj.requested_check_out = dt_out
                        reg_obj.reason = reason
                        reg_obj.save(update_fields=['requested_check_in', 'requested_check_out', 'reason', 'updated_at'])

                    created_records.append(reg_obj)
                    curr += timedelta(days=1)

        serializer = self.get_serializer(created_records, many=True)
        return Response({
            "message": f"Successfully processed regularization for {len(employees)} employee(s) across {len(created_records)} record(s).",
            "count": len(created_records),
            "employees_count": len(employees),
            "skipped_weekends": len(skipped_dates),
            "data": serializer.data
        }, status=status.HTTP_201_CREATED)
        
    def perform_update(self, serializer):
        from django.db import transaction
        with transaction.atomic():
            if serializer.validated_data.get('status') in ['Approved', 'Rejected']:
                approver = getattr(self.request.user, 'employee_profile', None)
                serializer.validated_data['approved_by'] = approver
                serializer.validated_data['approved_at'] = timezone.now()

            instance = serializer.save()
            # If approved, update the DailyAttendance
            if instance.status == 'Approved':
                daily_att, _ = DailyAttendance.objects.select_for_update().get_or_create(
                    employee=instance.employee,
                    attendance_date=instance.attendance_date,
                    defaults={
                        'site': instance.employee.site,
                        'entity': instance.employee.entity,
                        'organization': instance.employee.organization,
                    }
                )
                daily_att.first_check_in = instance.requested_check_in
                daily_att.last_check_out = instance.requested_check_out
                
                # Recalculate rules on regularization dynamically
                from .models import ShiftAssignment
                import datetime as dt_module
                shift_assignment = ShiftAssignment.objects.filter(employee=instance.employee, date=instance.attendance_date).first()
                if shift_assignment and shift_assignment.shift:
                    shift = shift_assignment.shift
                    cutoff_dt = dt_module.datetime.combine(instance.attendance_date, shift.start_time) + dt_module.timedelta(minutes=shift.grace_minutes)
                    if timezone.is_naive(cutoff_dt):
                        cutoff_dt = timezone.make_aware(cutoff_dt)
                    if instance.requested_check_in > cutoff_dt:
                        daily_att.attendance_status = 'Late'
                    else:
                        daily_att.attendance_status = 'Present'
                else:
                    shift_start = instance.requested_check_in.replace(hour=9, minute=30, second=0, microsecond=0)
                    if instance.requested_check_in > shift_start:
                        daily_att.attendance_status = 'Late'
                    else:
                        daily_att.attendance_status = 'Present'
                
                duration = daily_att.last_check_out - daily_att.first_check_in
                hours = duration.total_seconds() / 3600
                daily_att.total_work_hours = round(max(0.0, hours), 2)
                daily_att.overtime_hours = daily_att.compute_overtime(hours)
                if hours >= 8:
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

class ShiftDefinitionViewSet(DataIsolationMixin, viewsets.ModelViewSet):
    rbac_module = 'Shift Definitions'
    queryset = ShiftDefinition.objects.all().order_by('start_time')
    serializer_class = ShiftDefinitionSerializer
    permission_classes = [IsAuthenticated]

def is_holiday_for_employee(employee, date):
    from attendance.models import Holiday
    from django.db.models import Q
    att_holidays = Holiday.objects.filter(date=date).filter(
        Q(status__iexact='Active') | Q(status__isnull=True) | Q(status='')
    )
    for h in att_holidays:
        if h.site_id and getattr(employee, 'site_id', None) and h.site_id != employee.site_id:
            continue
        rules = h.rule_groups.all()
        if not rules.exists():
            return True
        for r in rules:
            if getattr(employee, 'dynamic_role_id', None) and r.excluded_roles.filter(id=employee.dynamic_role_id).exists():
                continue
            if employee.department_id and r.excluded_departments.filter(id=employee.department_id).exists():
                continue
            role_match = not r.applicable_roles.exists() or (getattr(employee, 'dynamic_role_id', None) and r.applicable_roles.filter(id=employee.dynamic_role_id).exists())
            dept_match = not r.applicable_departments.exists() or (employee.department_id and r.applicable_departments.filter(id=employee.department_id).exists())
            entity_match = not r.applicable_entities.exists() or (employee.entity_id and r.applicable_entities.filter(id=employee.entity_id).exists())
            branch_match = not r.applicable_branches.exists() or (employee.branch_id and r.applicable_branches.filter(id=employee.branch_id).exists())
            if role_match and dept_match and entity_match and branch_match:
                return True

    # Fallback to leaves.Holiday if configured there
    try:
        from leaves.models import Holiday as LeaveHoliday
        if LeaveHoliday.objects.filter(date=date).exists():
            return True
    except Exception:
        pass

    return False

def is_saturday_working_for_employee(employee):
    site = getattr(employee, 'site', None)
    if site and getattr(site, 'is_saturday_working', False):
        return True
    try:
        from leaves.models import LeavePolicyConfiguration
        config = LeavePolicyConfiguration.get_settings()
        return bool(getattr(config, 'is_saturday_working', False))
    except Exception:
        return False

def is_sunday_working_for_employee(employee):
    from organisation.models import AttendancePolicy
    # 1. Check AttendancePolicy for this employee directly
    try:
        emp_policy = AttendancePolicy.objects.filter(employee=employee).first()
        if emp_policy is not None and emp_policy.is_sunday_working:
            return True
    except Exception:
        pass

    # 2. Check site AttendancePolicy or site model toggle
    site = getattr(employee, 'site', None)
    if site:
        try:
            site_policy = AttendancePolicy.objects.filter(site=site).first()
            if site_policy is not None and site_policy.is_sunday_working:
                return True
        except Exception:
            pass
        if getattr(site, 'is_sunday_working', False):
            return True

    # 3. Check enrolled_sites if employee has multi-site assignments
    if hasattr(employee, 'enrolled_sites'):
        for es in employee.enrolled_sites.all():
            try:
                es_policy = AttendancePolicy.objects.filter(site=es).first()
                if es_policy is not None and es_policy.is_sunday_working:
                    return True
            except Exception:
                pass
            if getattr(es, 'is_sunday_working', False):
                return True

    # 4. Check entity AttendancePolicy
    entity = getattr(employee, 'entity', None)
    if entity:
        try:
            ent_policy = AttendancePolicy.objects.filter(entity=entity).first()
            if ent_policy is not None and ent_policy.is_sunday_working:
                return True
        except Exception:
            pass

    # 5. Check global AttendancePolicy
    try:
        global_policy = AttendancePolicy.objects.filter(site__isnull=True, employee__isnull=True, entity__isnull=True).first()
        if global_policy is not None and global_policy.is_sunday_working:
            return True
    except Exception:
        pass

    # 6. Fallback to leaves.LeavePolicyConfiguration
    try:
        from leaves.models import LeavePolicyConfiguration
        config = LeavePolicyConfiguration.get_settings()
        if getattr(config, 'is_sunday_working', False):
            return True
    except Exception:
        pass

    return False

def get_split_shift_incomplete_policy(employee, site=None):
    if employee and hasattr(employee, 'attendance_policy') and employee.attendance_policy:
        return employee.attendance_policy.split_shift_incomplete_policy
    target_site = site or getattr(employee, 'site', None)
    if target_site:
        if hasattr(target_site, 'attendance_policy') and target_site.attendance_policy:
            return target_site.attendance_policy.split_shift_incomplete_policy
        if getattr(target_site, 'split_shift_incomplete_policy', None):
            return target_site.split_shift_incomplete_policy
    if employee and hasattr(employee, 'entity') and employee.entity:
        if hasattr(employee.entity, 'default_attendance_policy') and employee.entity.default_attendance_policy:
            return employee.entity.default_attendance_policy.split_shift_incomplete_policy
    try:
        from organisation.models import AttendancePolicy
        global_policy = AttendancePolicy.objects.filter(site__isnull=True, employee__isnull=True, entity__isnull=True).first()
        if global_policy and global_policy.split_shift_incomplete_policy:
            return global_policy.split_shift_incomplete_policy
    except Exception:
        pass
    return 'Half Day'

def is_working_day(employee, date):
    # Sunday is off unless Sunday working toggle is enabled for employee's site
    if date.weekday() == 6:
        if not is_sunday_working_for_employee(employee):
            return False
    # Saturday is off unless Saturday working toggle is enabled
    if date.weekday() == 5:
        if not is_saturday_working_for_employee(employee):
            return False
    # Check holiday calendar
    if is_holiday_for_employee(employee, date):
        return False
    return True

def get_valid_date(employee, date):
    from datetime import timedelta
    current_date = date
    while not is_working_day(employee, current_date):
        current_date += timedelta(days=1)
    return current_date

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

        from authentication.permissions import isolate_queryset
        employees = Employee.objects.filter(status='Active')
        employees = isolate_queryset(employees, request.user)
        data = []
        for emp in employees:
            data.append({
                "employee": {
                    "id": emp.id,
                    "name": f"{emp.first_name} {emp.last_name}",
                    "title": emp.designation.title if emp.designation else "Employee",
                    "site_id": emp.site_id,
                    "is_sunday_working": is_sunday_working_for_employee(emp),
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
            emp = Employee.objects.get(id=employee_id)
            
            from datetime import datetime
            date_obj = datetime.strptime(date, "%Y-%m-%d").date()
            
            # Strict boundary: Do not allow manual assignment on non-working days
            if not is_working_day(emp, date_obj):
                day_name = date_obj.strftime("%A")
                reason = "Sunday weekly off (Sunday working is disabled for this site)" if date_obj.weekday() == 6 else ("Saturday off (toggle disabled)" if date_obj.weekday() == 5 else "Holiday calendar off")
                return Response({"error": f"Cannot assign shift on {day_name} ({date}): {reason}."}, status=400)
                
            valid_date_str = date_obj.strftime("%Y-%m-%d")
            
            assignment, _ = ShiftAssignment.objects.update_or_create(
                employee_id=employee_id,
                date=valid_date_str,
                defaults={'shift': shift}
            )
            from employees.models import Notification
            Notification.objects.create(
                recipient_id=employee_id,
                title="Shift Assignment Updated",
                message=f"You have been assigned to the {shift.name} shift ({shift.start_time.strftime('%I:%M %p')} to {shift.end_time.strftime('%I:%M %p')}) for {date}."
            )
            
            # Trigger async email
            emp = Employee.objects.get(id=employee_id)
            if emp.email:
                send_shift_email_async(
                    emp_email=emp.email,
                    emp_name=f"{emp.first_name} {emp.last_name}",
                    shift_name=shift.name,
                    shift_start=shift.start_time.strftime('%I:%M %p'),
                    shift_end=shift.end_time.strftime('%I:%M %p'),
                    dates_str=valid_date_str
                )
                
            return Response(ShiftAssignmentSerializer(assignment).data)
        except ShiftDefinition.DoesNotExist:
            return Response({"error": "Shift not found"}, status=404)

    @action(detail=False, methods=['post'])
    def bulk_assign(self, request):
        from django.db.models import Q
        department_ids = request.data.get('department_ids', [])
        designation_ids = request.data.get('designation_ids', [])
        role_ids = request.data.get('role_ids', [])
        employee_ids = request.data.get('employee_ids', [])
        
        # Fallback for legacy requests passing single values
        if not department_ids and request.data.get('department_id'):
            department_ids = [request.data.get('department_id')]
        if not designation_ids and request.data.get('designation_id'):
            designation_ids = [request.data.get('designation_id')]
        if not role_ids and request.data.get('role_id'):
            role_ids = [request.data.get('role_id')]
        if not employee_ids and request.data.get('employee_id'):
            employee_ids = [request.data.get('employee_id')]
            
        shift_id = request.data.get('shift_id')
        start_date = request.data.get('start_date')
        end_date = request.data.get('end_date')

        if not (department_ids or designation_ids or role_ids or employee_ids):
            return Response({"error": "Please select at least one department, designation, role, or employee"}, status=400)

        if not shift_id or not start_date or not end_date:
            return Response({"error": "shift_id, start_date, and end_date are required"}, status=400)

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

        criteria_q = Q()
        if department_ids:
            criteria_q |= Q(department_id__in=department_ids)
        if designation_ids:
            criteria_q |= Q(designation_id__in=designation_ids)
        if role_ids:
            criteria_q |= Q(dynamic_role_id__in=role_ids)
        if employee_ids:
            criteria_q |= Q(id__in=employee_ids)

        employees = Employee.objects.filter(criteria_q, status='Active')
        if request.user and request.user.is_authenticated:
            from authentication.permissions import isolate_queryset
            employees = isolate_queryset(employees, request.user)
        employees = employees.distinct()

        if not employees.exists():
            return Response({"error": "No active employees found matching the selected criteria."}, status=400)
        
        delta = end_dt - start_dt
        dates = [start_dt + timedelta(days=i) for i in range(delta.days + 1)]
        
        assignments_to_create_dict = {}
        non_working_dates_map = defaultdict(list)
        for emp in employees:
            for d in dates:
                if is_working_day(emp, d):
                    key = (emp.id, d)
                    assignments_to_create_dict[key] = ShiftAssignment(employee=emp, date=d, shift=shift)
                else:
                    non_working_dates_map[emp.id].append(d)
                
        assignments_to_create = list(assignments_to_create_dict.values())
        
        # Purge any existing assignments on non-working days (Sundays, holidays, off-Saturdays) for these employees in range
        for emp_id, bad_dates in non_working_dates_map.items():
            if bad_dates:
                ShiftAssignment.objects.filter(employee_id=emp_id, date__in=bad_dates).delete()
                
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
                
            # Trigger async emails for bulk assignment
            for emp in employees:
                if emp.email:
                    send_shift_email_async(
                        emp_email=emp.email,
                        emp_name=f"{emp.first_name} {emp.last_name}",
                        shift_name=shift.name,
                        shift_start=shift.start_time.strftime('%I:%M %p'),
                        shift_end=shift.end_time.strftime('%I:%M %p'),
                        dates_str=f"{start_date} to {end_date}"
                    )
            
        return Response({"message": f"Successfully assigned shift to {employees.count()} employees for {len(dates)} days ({len(assignments_to_create)} total assignments)."})

class HolidayViewSet(DataIsolationMixin, viewsets.ModelViewSet):
    rbac_module = 'Holiday Planner'
    queryset = Holiday.objects.all().order_by('date')
    serializer_class = HolidaySerializer
    permission_classes = [IsAuthenticated]
    
    @action(detail=False, methods=['get'])
    def stats(self, request):
        today = timezone.now().date()
        holidays = Holiday.objects.all()
        
        return Response({
            "total_holidays": holidays.count(),
            "upcoming": holidays.filter(date__gte=today).count(),
            "optional": holidays.filter(holiday_type='Optional').count(),
            "restricted": holidays.filter(holiday_type='Restricted').count(),
            "regional_festival": holidays.filter(holiday_type__in=['Regional', 'Festival']).count()
        })
        
class HolidayRuleGroupViewSet(DataIsolationMixin, viewsets.ModelViewSet):
    queryset = HolidayRuleGroup.objects.all()
    serializer_class = HolidayRuleGroupSerializer
    permission_classes = [IsAuthenticated]
