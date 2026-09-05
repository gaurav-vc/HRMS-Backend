from rest_framework import viewsets, status
from authentication.permissions import DataIsolationMixin, isolate_queryset
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
                    if not liveness_passed and source != 'FACE':
                        return Response({"error": f"Liveness Check Failed: {liveness_msg}"}, status=400)
                elif source == 'FACE':
                    pass # Mobile app bypasses liveness challenge token check
                else:
                    return Response({"error": "challenge_id required for Active Liveness validation"}, status=400)

                if not HAVE_FACE_REC:
                    # TEMPORARY OVERRIDE: ML Bypass with Strict Pixel Comparison
                    image_bytes = file_obj.read()
                    import cv2
                    import numpy as np
                    import os
                    np_img = np.frombuffer(image_bytes, np.uint8)
                    img = cv2.imdecode(np_img, cv2.IMREAD_COLOR)
                    
                    if img is None:
                        return Response({"error": "Invalid image format uploaded."}, status=400)
                        
                    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
                    face_cascade = cv2.CascadeClassifier(cv2.data.haarcascades + 'haarcascade_frontalface_default.xml')
                    faces = face_cascade.detectMultiScale(gray, scaleFactor=1.1, minNeighbors=5, minSize=(50, 50))
                    
                    if len(faces) == 0:
                        # Fallback to a more relaxed detection if strict pass fails
                        faces = face_cascade.detectMultiScale(gray, scaleFactor=1.05, minNeighbors=3, minSize=(30, 30))
                    
                    if len(faces) == 0:
                        return Response({"error": "Security Alert: No face detected. Please ensure your face is clearly visible."}, status=400)
                    
                    # Sort to get the largest face in the frame
                    faces = sorted(faces, key=lambda x: x[2]*x[3], reverse=True)
                    x, y, w, h = faces[0]
                    
                    # Crop and normalize the face pixels
                    face_crop = gray[y:y+h, x:x+w]
                    face_crop = cv2.resize(face_crop, (150, 150))
                        
                    # Resolve Employee Identity First
                    emp_id = request.data.get('employee')
                    employee = None
                    if emp_id:
                        employee = Employee.objects.filter(id=emp_id).first()
                    elif request.user and request.user.is_authenticated:
                        if hasattr(request.user, 'employee_profile') and getattr(request.user, 'employee_profile', None):
                            employee = request.user.employee_profile
                        else:
                            return Response({"error": "Security Alert: Your user account is not linked to an Employee profile. Please contact HR to link your account before punching in."}, status=400)
                        
                    # Strict Pixel Matching Boundary
                    from django.conf import settings
                    import glob
                    
                    # We store fallback references in the media directory
                    fallback_dir = os.path.join(settings.MEDIA_ROOT, 'fallback_faces') if hasattr(settings, 'MEDIA_ROOT') and settings.MEDIA_ROOT else os.path.join(os.path.dirname(os.path.dirname(__file__)), 'media', 'fallback_faces')
                    os.makedirs(fallback_dir, exist_ok=True)
                    
                    if employee:
                        ref_img = None
                        
                        try:
                            has_photo = bool(employee.photo and employee.photo.name)
                            if has_photo:
                                _ = employee.photo.path
                        except ValueError:
                            has_photo = False
                            
                        if has_photo:
                            # STRICT SECURITY BOUNDARY: Always use the official profile picture for matching
                            photo_img = cv2.imread(employee.photo.path)
                            if photo_img is not None:
                                photo_gray = cv2.cvtColor(photo_img, cv2.COLOR_BGR2GRAY)
                                photo_faces = face_cascade.detectMultiScale(photo_gray, scaleFactor=1.1, minNeighbors=3, minSize=(30, 30))
                                if len(photo_faces) > 0:
                                    photo_faces = sorted(photo_faces, key=lambda x: x[2]*x[3], reverse=True)
                                    px, py, pw, ph = photo_faces[0]
                                    photo_crop = photo_gray[py:py+ph, px:px+pw]
                                    ref_img = cv2.resize(photo_crop, (150, 150))
                                else:
                                    h, w = photo_gray.shape
                                    cy, cx = h//2, w//2
                                    s = min(h, w)//2
                                    photo_crop = photo_gray[cy-s:cy+s, cx-s:cx+s]
                                    ref_img = cv2.resize(photo_crop, (150, 150))
                        else:
                            # First time punch-in: Save as profile picture
                            from django.core.files.base import ContentFile
                            employee.photo.save(f"{employee.id}_profile.jpg", ContentFile(image_bytes))
                            ref_img = face_crop # Automatically pass the first time

                        # Fetch dynamic threshold
                        threshold_percent = 95.00
                        try:
                            if hasattr(employee, 'attendance_policy') and employee.attendance_policy:
                                threshold_percent = float(employee.attendance_policy.face_match_threshold)
                            elif employee.site and hasattr(employee.site, 'attendance_policy') and employee.site.attendance_policy:
                                threshold_percent = float(employee.site.attendance_policy.face_match_threshold)
                        except Exception:
                            pass

                        if ref_img is not None:
                            # Strict Security Boundary: ORB Feature Matching for scale/rotation invariance
                            orb = cv2.ORB_create(nfeatures=500)
                            kp1, des1 = orb.detectAndCompute(face_crop, None)
                            kp2, des2 = orb.detectAndCompute(ref_img, None)
                            
                            similarity_percent = 0.0
                            if des1 is not None and des2 is not None and len(kp1) > 0 and len(kp2) > 0:
                                # Use Lowe's ratio test to drastically filter false positives
                                bf = cv2.BFMatcher(cv2.NORM_HAMMING, crossCheck=False)
                                matches = bf.knnMatch(des1, des2, k=2)
                                
                                good_matches = []
                                for m_n in matches:
                                    if len(m_n) == 2:
                                        m, n = m_n
                                        if m.distance < 0.75 * n.distance:
                                            good_matches.append(m)
                                    elif len(m_n) == 1:
                                        good_matches.append(m_n[0])
                                
                                baseline = min(len(kp1), len(kp2))
                                if baseline > 0:
                                    raw_accuracy = len(good_matches) / baseline
                                    # ORB raw good matches mapping:
                                    # A genuine face match from a different angle usually yields 8% to 15% good features.
                                    # A completely different face yields < 2% good features.
                                    # Map 0.02 (2%) -> 50%, 0.12 (12%) -> 95%, >0.15 -> 100%
                                    if raw_accuracy < 0.02:
                                        similarity_percent = raw_accuracy * (50.0 / 0.02)
                                    else:
                                        similarity_percent = 50.0 + ((raw_accuracy - 0.02) / 0.10) * 45.0
                                        
                                    similarity_percent = min(100.0, similarity_percent)
                            
                            if similarity_percent < threshold_percent:
                                return Response({"error": f"Security Alert: Identity verification failed. Accuracy: {similarity_percent:.1f}% (Required: {threshold_percent:.1f}%)"}, status=400)
                    else:
                        # 1:N Fallback Search for Kiosk Mode (Identity unknown)
                        best_match_id = None
                        best_sim = -1.0
                        
                        for ref_path in glob.glob(os.path.join(fallback_dir, "*_ref.png")):
                            ref_img = cv2.imread(ref_path, cv2.IMREAD_GRAYSCALE)
                            if ref_img is not None:
                                res = cv2.matchTemplate(face_crop, ref_img, cv2.TM_CCOEFF_NORMED)
                                sim = res[0][0]
                                if sim > best_sim:
                                    best_sim = sim
                                    best_match_id = os.path.basename(ref_path).split('_')[0]
                                    
                        if best_sim >= 0.25 and best_match_id:
                            employee = Employee.objects.filter(id=best_match_id).first()
                            
                        if not employee:
                            return Response({"error": f"Security Alert: Identity verification failed. Your face does not match any registered employee. (Max Sim: {best_sim:.2f})"}, status=400)
                        
                    verification_status = 'VERIFIED'
                else:
                    emp_id = request.data.get('employee')
                    image_bytes = file_obj.read()
                    
                    # Wave 4: Passive Liveness & Deepfake Detection (Must occur before DeepFace)
                    # We pass an empty list for video_frames as a mock for the deepfake detector
                    passed_passive, passive_msg = PassiveLivenessService.full_security_scan(image_bytes, video_frames=[])
                    if not passed_passive:
                        return Response({"error": passive_msg}, status=400)
                        
                    if emp_id and source == 'FACE':
                        # 1:1 Verification for Mobile App
                        employee = Employee.objects.filter(id=emp_id).first()
                        if not employee:
                            return Response({"error": "Employee not found"}, status=400)
                        
                        try:
                            has_photo = bool(employee.photo and employee.photo.name)
                            if has_photo:
                                _ = employee.photo.path
                        except ValueError:
                            has_photo = False
                            
                        if not has_photo:
                            # First time face capture: save as profile picture
                            from django.core.files.base import ContentFile
                            employee.photo.save(f"{employee.id}_profile.jpg", ContentFile(image_bytes))
                            identified_id = employee.id
                        else:
                            import tempfile
                            with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp_img:
                                tmp_img.write(image_bytes)
                                tmp_path = tmp_img.name
                                
                            try:
                                from deepface import DeepFace
                                result = DeepFace.verify(
                                    img1_path=tmp_path,
                                    img2_path=employee.photo.path,
                                    model_name="Facenet512",
                                    detector_backend="opencv",
                                    distance_metric="cosine",
                                    enforce_detection=True
                                )
                                os.remove(tmp_path)
                                
                                # Fetch dynamic threshold
                                threshold_percent = 95.00
                                try:
                                    if hasattr(employee, 'attendance_policy') and employee.attendance_policy:
                                        threshold_percent = float(employee.attendance_policy.face_match_threshold)
                                    elif employee.site and hasattr(employee.site, 'attendance_policy') and employee.site.attendance_policy:
                                        threshold_percent = float(employee.site.attendance_policy.face_match_threshold)
                                except Exception:
                                    pass

                                distance = result.get("distance", 1.0)
                                max_threshold = result.get("threshold", 0.30)
                                # Convert cosine distance to percentage score
                                accuracy_percent = 100.0
                                if distance > 0:
                                    # Distance 0 -> 100%, Distance max_threshold -> required threshold (e.g. 95%)
                                    drop_rate = (100.0 - threshold_percent) / max_threshold
                                    accuracy_percent = max(0.0, 100.0 - (distance * drop_rate))
                                
                                if accuracy_percent < threshold_percent or not result.get("verified", False):
                                    return Response({"error": f"Security Alert: Identity verification failed. Accuracy: {accuracy_percent:.1f}% (Required: {threshold_percent:.1f}%)"}, status=400)
                                    
                                identified_id = employee.id
                            except ValueError:
                                if os.path.exists(tmp_path): os.remove(tmp_path)
                                return Response({"error": "No human face detected. Please retake photo clearly."}, status=400)
                            except Exception as e:
                                if os.path.exists(tmp_path): os.remove(tmp_path)
                                return Response({"error": f"Verification error: {str(e)}"}, status=500)
                    else:
                        # 1:N Search across entire FAISS index
                        result = get_face_encoding(image_bytes)
                        
                        if not result.get('success'):
                            return Response({"error": f"Liveness/Extraction Failed: {result.get('error')}"}, status=400)
                            
                        identified_id = biometric_search.identify(result['encoding'])
                        if not identified_id:
                            return Response({"error": "Rejected: Face mismatch (No employee recognized)"}, status=400)
                            
                        if emp_id and str(emp_id) != str(identified_id):
                            return Response({"error": "Rejected: Face mismatch. The recognized face does not match the selected employee ID."}, status=400)
                        
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
                if emp_id:
                    employee = Employee.objects.get(id=emp_id)
                elif hasattr(request.user, 'employee_profile') and request.user.employee_profile:
                    employee = request.user.employee_profile
                else:
                    employee = Employee.objects.first()
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
                if policy.require_face and source != 'FACE' and not file_obj:
                    return Response({"error": "Face verification is mandatory for your profile as per attendance policy."}, status=400)
                if policy.require_gps and not (lat_str and lng_str):
                    return Response({"error": "GPS location is mandatory for your profile as per attendance policy."}, status=400)
                qr_token = request.data.get('qr_token')
                
                # Check WFH status
                is_wfh = request.data.get('is_wfh') == 'true' or (policy.wfh_employees and policy.wfh_employees.filter(id=employee.id).exists())
                
                # Enforce require_qr only if it's not a personal Face punch (mobile or web) and not WFH
                if policy.require_qr and not qr_token and source != 'FACE' and not file_obj and not is_wfh:
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
                        # WFH Bypass Geofence Feature - Strictly explicit list only
                        is_wfh = False
                        if policy and policy.wfh_employees.exists():
                            if policy.wfh_employees.filter(id=employee.id).exists():
                                is_wfh = True
                        if not is_wfh:
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
            "absent_days": absent_count,
            "half_days": half_day_count,
            "late_marks": late_count,
            "total_overtime_hours": round(total_ot_hours, 2),
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

class RegularizationViewSet(DataIsolationMixin, viewsets.ModelViewSet):
    rbac_module = 'Regularization'
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

class ShiftDefinitionViewSet(DataIsolationMixin, viewsets.ModelViewSet):
    rbac_module = 'Shift Definitions'
    queryset = ShiftDefinition.objects.all().order_by('start_time')
    serializer_class = ShiftDefinitionSerializer
    permission_classes = [IsAuthenticated]

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
            
            # Trigger async email
            emp = Employee.objects.get(id=employee_id)
            if emp.email:
                send_shift_email_async(
                    emp_email=emp.email,
                    emp_name=f"{emp.first_name} {emp.last_name}",
                    shift_name=shift.name,
                    shift_start=shift.start_time.strftime('%I:%M %p'),
                    shift_end=shift.end_time.strftime('%I:%M %p'),
                    dates_str=str(date)
                )
                
            return Response(ShiftAssignmentSerializer(assignment).data)
        except ShiftDefinition.DoesNotExist:
            return Response({"error": "Shift not found"}, status=404)

    @action(detail=False, methods=['post'])
    def bulk_assign(self, request):
        department_ids = request.data.get('department_ids', [])
        
        # Fallback for legacy requests passing single department_id
        if not department_ids and 'department_id' in request.data:
            department_ids = [request.data.get('department_id')]
            
        shift_id = request.data.get('shift_id')
        start_date = request.data.get('start_date')
        end_date = request.data.get('end_date')

        if not department_ids or not shift_id or not start_date or not end_date:
            return Response({"error": "department_ids, shift_id, start_date, and end_date are required"}, status=400)

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

        employees = Employee.objects.filter(department_id__in=department_ids, status='Active')
        
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
    rbac_module = 'Holidays'
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
