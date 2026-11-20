import base64
import logging
from datetime import timedelta
import numpy as np
from django.utils import timezone
from django.db.models import Q
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework import status
from rest_framework.permissions import AllowAny

from organisation.models import Site
from employees.models import Employee
from attendance.models import DailyAttendance, PunchLog, FaceProfile
from attendance.crypto_utils import CryptoService
from attendance.utils import get_face_encoding, compare_faces

logger = logging.getLogger('hrms.kiosk')

# Fast in-memory photo encoding cache: (emp_id, photo_name) -> list of 128 floats
_PHOTO_ENCODING_CACHE = {}


class KioskConfigAPIView(APIView):
    """
    Public API for the physical tablet kiosk to fetch its dynamic site configuration.
    Security: Authenticated via the unique site kiosk_token.
    """
    permission_classes = [AllowAny]

    def get(self, request):
        token = request.query_params.get('token')
        if not token:
            return Response({"error": "Kiosk terminal token is required."}, status=status.HTTP_400_BAD_REQUEST)

        site = Site.objects.filter(kiosk_token=token).first()
        if not site:
            return Response({"error": "Invalid or expired kiosk terminal token."}, status=status.HTTP_404_NOT_FOUND)

        logo_url = None
        if site.logo:
            logo_url = request.build_absolute_uri(site.logo.url)

        return Response({
            "site_id": site.id,
            "site_name": site.name,
            "kiosk_enabled": site.kiosk_enabled,
            "similarity_threshold": site.kiosk_similarity_threshold,
            "cooldown_seconds": site.kiosk_cooldown_seconds,
            "auto_punch": site.kiosk_auto_punch,
            "branding_text": site.branding_text,
            "logo_url": logo_url
        })


class KioskVerifyPinAPIView(APIView):
    """
    Validates the 4-digit Site Admin PIN on the physical tablet to safely exit kiosk mode.
    """
    permission_classes = [AllowAny]

    def post(self, request):
        token = request.data.get('token')
        pin = str(request.data.get('pin', '')).strip()

        if not token or not pin:
            return Response({"error": "Token and PIN are required."}, status=status.HTTP_400_BAD_REQUEST)

        site = Site.objects.filter(kiosk_token=token).first()
        if not site:
            return Response({"error": "Invalid kiosk token."}, status=status.HTTP_404_NOT_FOUND)

        if site.kiosk_pin and site.kiosk_pin.strip() == pin:
            return Response({"valid": True, "message": "PIN verified successfully."})
        
        return Response({"valid": False, "error": "Incorrect PIN."}, status=status.HTTP_403_FORBIDDEN)


class KioskPunchAPIView(APIView):
    """
    Real-time 1:N Facial Identification and Attendance Punching for Tablet Kiosks.
    Strictly isolated: Only matches faces against active employees assigned to this site.
    """
    permission_classes = [AllowAny]

    def post(self, request):
        token = request.data.get('token')
        frame_data = request.data.get('frame') # Base64 data URL or raw base64 string
        requested_type = request.data.get('punch_type', 'AUTO') # IDENTIFY, PROMPT, AUTO, IN, OUT
        employee_id = request.data.get('employee_id')

        if not token:
            return Response({"error": "Kiosk terminal token is required."}, status=status.HTTP_400_BAD_REQUEST)
        if not employee_id and not frame_data:
            return Response({"error": "Camera frame or employee_id is required."}, status=status.HTTP_400_BAD_REQUEST)

        # 1. Validate Site & Kiosk Status
        site = Site.objects.filter(kiosk_token=token).first()
        if not site:
            return Response({"error": "Invalid kiosk terminal token."}, status=status.HTTP_404_NOT_FOUND)
        if not site.kiosk_enabled:
            return Response({
                "error": f"Kiosk attendance is currently disabled for {site.name}. Please contact Site Admin."
            }, status=status.HTTP_403_FORBIDDEN)

        matched_employee = None
        best_distance = float('inf')
        encoding_res = {}

        if employee_id:
            # Confirmed punch for an already identified employee
            matched_employee = Employee.objects.filter(
                id=employee_id,
                status='Active'
            ).select_related('face_profile', 'department', 'designation').first()
            if not matched_employee:
                return Response({"error": "Employee not found or inactive."}, status=status.HTTP_404_NOT_FOUND)
            best_distance = 0.05
        else:
            # 2. Decode Frame
            try:
                if ',' in frame_data:
                    frame_data = frame_data.split(',', 1)[1]
                image_bytes = base64.b64decode(frame_data)
            except Exception as e:
                return Response({"error": f"Invalid base64 image data: {str(e)}"}, status=status.HTTP_400_BAD_REQUEST)

            # 3. Extract Face Encoding
            encoding_res = get_face_encoding(image_bytes)
            if not encoding_res.get('success'):
                return Response({
                    "error": encoding_res.get('error', 'Face detection failed. Please align your face inside the guide.')
                }, status=status.HTTP_400_BAD_REQUEST)

            live_encoding = encoding_res.get('encoding')
            threshold = max(float(site.kiosk_similarity_threshold or 0.50), 0.50)

            # 4. Site-Scoped 1:N Face Search
            # Candidate pool: employees assigned to this site, enrolled in site, parent site, sub-sites, or site organization
            candidate_q = Q(site=site) | Q(enrolled_sites=site)
            if site.parent_site:
                candidate_q |= Q(site=site.parent_site) | Q(enrolled_sites=site.parent_site)
            candidate_q |= Q(site__parent_site=site)
            if site.organization:
                candidate_q |= Q(organization=site.organization)

            site_employees = Employee.objects.filter(
                candidate_q,
                status='Active'
            ).select_related('face_profile', 'department', 'designation').distinct()

            matching_candidates = []

            for emp in site_employees:
                known_encodings = []

                # Check enrolled FaceProfile vectors
                if hasattr(emp, 'face_profile') and emp.face_profile and emp.face_profile.encrypted_face_encodings:
                    try:
                        payload = CryptoService.decrypt_json(
                            emp.face_profile.encrypted_face_encodings,
                            emp.face_profile.encrypted_dek
                        )
                        encs = payload.get('encodings', [])
                        if encs and len(encs[0]) == 128:
                            known_encodings = encs
                    except Exception:
                        pass

                # Fallback to computing on-the-fly from employee.photo with memory cache
                if not known_encodings and emp.photo and emp.photo.name:
                    cache_key = (emp.id, emp.photo.name)
                    cached = _PHOTO_ENCODING_CACHE.get(cache_key)
                    if cached:
                        known_encodings = cached
                    else:
                        try:
                            with emp.photo.open('rb') as f:
                                photo_bytes = f.read()
                            p_res = get_face_encoding(photo_bytes)
                            if p_res.get('success'):
                                known_encodings = [p_res.get('encoding')]
                                _PHOTO_ENCODING_CACHE[cache_key] = known_encodings
                        except Exception:
                            pass

                if known_encodings:
                    comp = compare_faces(known_encodings, live_encoding, tolerance=threshold)
                    if comp.get('success') and comp.get('match'):
                        distance = comp.get('distance', 1.0)
                        matching_candidates.append({
                            'employee': emp,
                            'distance': distance,
                            'similarity': comp.get('similarity', 1.0 - distance),
                            'photo_name': emp.photo.name if emp.photo else None,
                            'encodings': known_encodings
                        })
                        if distance < best_distance:
                            best_distance = distance
                            matched_employee = emp

            # Check if 2 or more employees match and share the same common profile photo / face
            if len(matching_candidates) >= 2:
                matching_candidates.sort(key=lambda x: x['distance'])
                c1 = matching_candidates[0]
                c2 = matching_candidates[1]
                e1 = c1['employee']
                e2 = c2['employee']

                same_photo_file = bool(c1['photo_name'] and c1['photo_name'] == c2['photo_name'])
                comp_between = compare_faces(c1['encodings'], c2['encodings'], tolerance=0.50)
                same_face = bool(comp_between.get('match'))

                if same_photo_file or same_face:
                    alert_msg = f"2 employees have the same photo: {e1.first_name} {e1.last_name} ({e1.code}) and {e2.first_name} {e2.last_name} ({e2.code})."
                    logger.warning(f"Kiosk Duplicate Photo Conflict: {alert_msg}")
                    return Response({
                        "status": "DUPLICATE_PHOTO_ALERT",
                        "error": alert_msg,
                        "message": alert_msg,
                        "conflict_employees": [
                            {
                                "id": e1.id,
                                "code": e1.code,
                                "name": f"{e1.first_name} {e1.last_name}".strip(),
                                "photo_url": request.build_absolute_uri(e1.photo.url) if e1.photo else None,
                                "department": e1.department.name if e1.department else "",
                            },
                            {
                                "id": e2.id,
                                "code": e2.code,
                                "name": f"{e2.first_name} {e2.last_name}".strip(),
                                "photo_url": request.build_absolute_uri(e2.photo.url) if e2.photo else None,
                                "department": e2.department.name if e2.department else "",
                            }
                        ],
                        "facial_area": encoding_res.get('facial_area'),
                        "frame_dims": encoding_res.get('frame_dims')
                    }, status=status.HTTP_200_OK)

        if not matched_employee:
            return Response({
                "error": "Face not recognized. Please ensure your profile photo is registered for this site."
            }, status=status.HTTP_404_NOT_FOUND)

        now = timezone.now()
        today = now.date()
        cooldown_sec = site.kiosk_cooldown_seconds or 30

        # Query today's punch activity for smart status resolution
        today_punches = PunchLog.objects.filter(
            employee=matched_employee,
            punch_time__date=today
        ).order_by('punch_time')
        last_punch = today_punches.last()

        # Step 4b. When in IDENTIFY / PROMPT mode: Return identified employee info and ask for Punch IN or Punch OUT
        if requested_type in ['IDENTIFY', 'PROMPT']:
            recommended_type = 'OUT' if (last_punch and last_punch.punch_type == 'IN') else 'IN'
            photo_url = None
            if matched_employee.photo:
                photo_url = request.build_absolute_uri(matched_employee.photo.url)
            dept_name = matched_employee.department.name if matched_employee.department else 'General'
            desig_title = matched_employee.designation.title if matched_employee.designation else ''

            return Response({
                "status": "IDENTIFIED",
                "employee": {
                    "id": matched_employee.id,
                    "code": matched_employee.code,
                    "employee_id": matched_employee.code,
                    "first_name": matched_employee.first_name,
                    "last_name": matched_employee.last_name,
                    "name": f"{matched_employee.first_name} {matched_employee.last_name}".strip(),
                    "department": dept_name,
                    "designation": desig_title,
                    "photo_url": photo_url
                },
                "recommended_type": recommended_type,
                "last_punch": {
                    "punch_type": last_punch.punch_type,
                    "punch_time": last_punch.punch_time.strftime("%I:%M %p")
                } if last_punch else None,
                "facial_area": encoding_res.get('facial_area'),
                "frame_dims": encoding_res.get('frame_dims'),
                "similarity_score": round(float(1.0 - best_distance), 2) if best_distance != float('inf') else 1.0,
            }, status=status.HTTP_200_OK)

        # 5. Debounce / Anti-Spam Check (only for auto scans when employee_id was not explicitly confirmed)
        if not employee_id and last_punch:
            elapsed = (now - last_punch.punch_time).total_seconds()
            if elapsed < cooldown_sec:
                remaining = int(cooldown_sec - elapsed)
                return Response({
                    "status": "COOLDOWN",
                    "message": f"Already punched {last_punch.punch_type} at {last_punch.punch_time.strftime('%I:%M %p')}.",
                    "remaining_seconds": remaining,
                    "facial_area": encoding_res.get('facial_area'),
                    "frame_dims": encoding_res.get('frame_dims'),
                    "employee": {
                        "name": f"{matched_employee.first_name} {matched_employee.last_name}",
                        "code": matched_employee.code,
                    }
                }, status=status.HTTP_200_OK)

        # 6. Smart IN / OUT Resolution
        if requested_type in ['IN', 'OUT']:
            punch_type = requested_type
        else: # AUTO
            if not today_punches.exists():
                punch_type = 'IN'
            else:
                last_type = today_punches.last().punch_type
                punch_type = 'OUT' if last_type == 'IN' else 'IN'

        # 7. Record Daily Attendance & Punch Log
        org = matched_employee.organization or (site.organization if site else None)
        daily_att, _ = DailyAttendance.objects.get_or_create(
            employee=matched_employee,
            attendance_date=today,
            defaults={
                'site': site,
                'entity': matched_employee.entity,
                'organization': org
            }
        )

        if punch_type == 'IN':
            if not daily_att.first_check_in:
                daily_att.first_check_in = now
                from attendance.models import ShiftAssignment
                import datetime
                shift_assignment = ShiftAssignment.objects.filter(employee=matched_employee, date=today).first()
                if shift_assignment and shift_assignment.shift:
                    shift = shift_assignment.shift
                    cutoff_dt = datetime.datetime.combine(today, shift.start_time) + datetime.timedelta(minutes=shift.grace_minutes)
                    if timezone.is_naive(cutoff_dt):
                        cutoff_dt = timezone.make_aware(cutoff_dt)
                    if now > cutoff_dt:
                        daily_att.attendance_status = 'Late'
                    else:
                        daily_att.attendance_status = 'Present'
                else:
                    shift_start = now.replace(hour=9, minute=30, second=0, microsecond=0)
                    if now > shift_start:
                        daily_att.attendance_status = 'Late'
                    else:
                        daily_att.attendance_status = 'Present'
        else:
            daily_att.last_check_out = now

        if daily_att.first_check_in and daily_att.last_check_out:
            duration = (daily_att.last_check_out - daily_att.first_check_in).total_seconds() / 3600.0
            daily_att.total_work_hours = round(max(0.0, duration), 2)
            if daily_att.total_work_hours >= 8.0:
                if daily_att.attendance_status not in ['Late']:
                    daily_att.attendance_status = 'Present'
            elif daily_att.total_work_hours >= 4.0:
                daily_att.attendance_status = 'Half Day'
            else:
                daily_att.attendance_status = 'Absent'

        daily_att.save()

        PunchLog.objects.create(
            employee=matched_employee,
            daily_attendance=daily_att,
            punch_time=now,
            punch_type=punch_type,
            source='TABLET_KIOSK',
            verification_status='VERIFIED',
            device_info=f"Tablet Kiosk - {site.name}",
            ip_address=request.META.get('REMOTE_ADDR')
        )

        photo_url = None
        if matched_employee.photo:
            photo_url = request.build_absolute_uri(matched_employee.photo.url)

        dept_name = matched_employee.department.name if matched_employee.department else 'General'

        return Response({
            "status": "SUCCESS",
            "punch_type": punch_type,
            "punch_time": now.strftime("%I:%M %p"),
            "attendance_date": today.strftime("%d %b %Y"),
            "similarity_score": round(float(1.0 - best_distance), 2) if best_distance != float('inf') else 1.0,
            "facial_area": encoding_res.get('facial_area'),
            "frame_dims": encoding_res.get('frame_dims'),
            "employee": {
                "id": matched_employee.id,
                "code": matched_employee.code,
                "first_name": matched_employee.first_name,
                "last_name": matched_employee.last_name,
                "department": dept_name,
                "photo_url": photo_url
            }
        }, status=status.HTTP_200_OK)
