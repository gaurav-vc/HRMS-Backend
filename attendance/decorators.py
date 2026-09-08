from functools import wraps
from django.conf import settings
from rest_framework.response import Response
from django.utils import timezone
from datetime import timedelta
from attendance.models import StrictLivenessAuditLog, LivenessLockout, Employee

def strict_liveness_precheck(view_func):
    """
    Decorator to wrap the punch API with a single-frame anti-spoofing pipeline.
    Executes BEFORE the existing face-match logic.
    """
    @wraps(view_func)
    def _wrapped_view(viewset_instance, request, *args, **kwargs):
        source = request.data.get('source', 'WEB')
        punch_type = request.data.get('punch_type', 'IN')
        
        # Only apply strict liveness to FACE punches (mobile)
        if source != 'FACE':
            return view_func(viewset_instance, request, *args, **kwargs)
            
        file_obj = request.FILES.get('face_image')
        if not file_obj:
            return view_func(viewset_instance, request, *args, **kwargs)
            
        emp_id = request.data.get('employee')
        if not emp_id and hasattr(request, 'user') and request.user.is_authenticated:
            try:
                emp_id = request.user.employee_profile.id
            except Exception:
                pass
                
        # Handle Retry Exhaustion Lockout
        if emp_id:
            try:
                lockout = LivenessLockout.objects.get(employee_id=emp_id)
                if lockout.locked_until and timezone.now() < lockout.locked_until:
                    # Return 403 Forbidden with exact message
                    return Response({"error": "Too many failed verification attempts. Please contact your manager or try again in 15 minutes."}, status=403)
            except LivenessLockout.DoesNotExist:
                pass
                
        # Determine if WFH or Office (Requires querying the Employee/Policy)
        is_wfh = False
        employee = None
        if emp_id:
            try:
                employee = Employee.objects.get(id=emp_id)
                from organisation.models import AttendancePolicy
                policy = None
                if hasattr(employee, 'attendance_policy') and employee.attendance_policy:
                    policy = employee.attendance_policy
                elif employee.site and hasattr(employee.site, 'attendance_policy'):
                    policy = employee.site.attendance_policy
                    
                if policy and policy.wfh_employees.filter(id=employee.id).exists():
                    is_wfh = True
            except Exception:
                pass
                
        # Feature Flags
        shadow_mode = getattr(settings, 'LIVENESS_SHADOW_MODE_ENABLED', True)
        office_enabled = getattr(settings, 'OFFICE_STRICT_LIVENESS_ENABLED', True)
        wfh_enabled = getattr(settings, 'WFH_STRICT_LIVENESS_ENABLED', True)
        
        # Check if enabled for this flow
        if (is_wfh and not wfh_enabled) or (not is_wfh and not office_enabled):
            return view_func(viewset_instance, request, *args, **kwargs)
            
        try:
            image_bytes = file_obj.read()
            # Reset file pointer for the actual punch method
            file_obj.seek(0)
            
            lat_str = request.data.get('latitude')
            lng_str = request.data.get('longitude')
            
            lat = float(lat_str) if lat_str else 0.0
            lng = float(lng_str) if lng_str else 0.0
            
            # Execute Pipeline
            from attendance.services.strict_liveness_engine import StrictLivenessEngine
            result = StrictLivenessEngine.execute_pipeline(emp_id, image_bytes, lat, lng, request.data)
            
            # Log to Audit Table
            audit = StrictLivenessAuditLog.objects.create(
                employee_id=emp_id,
                punch_type=punch_type,
                source=source,
                is_wfh=is_wfh,
                face_count=result['face_count'],
                laplacian_score=result['laplacian_score'],
                moire_score=result['moire_score'],
                specular_score=result['specular_score'],
                onnx_liveness_score=result['onnx_liveness_score'],
                composite_score=result['composite_score'],
                exif_edited_flag=result['exif_edited_flag'],
                jpeg_double_compression=result['jpeg_double_compression'],
                velocity_kmh=result['velocity_kmh'],
                integrity_valid=result['integrity_valid'],
                final_decision='PASSED' if result['passed'] else ('SHADOW_MODE' if shadow_mode else 'REJECTED'),
                rejection_reason=result['reason'] if not result['passed'] else None
            )
            
            if not result['passed']:
                if not shadow_mode:
                    # Update Lockout
                    if emp_id:
                        lockout, _ = LivenessLockout.objects.get_or_create(employee_id=emp_id)
                        lockout.failed_attempts += 1
                        max_retries = getattr(settings, 'LIVENESS_MAX_RETRY_COUNT', 3)
                        if lockout.failed_attempts >= max_retries:
                            lockout.locked_until = timezone.now() + timedelta(minutes=getattr(settings, 'LIVENESS_COOLDOWN_MINUTES', 15))
                        lockout.save()
                    
                    return Response({"error": "Verification failed, please try again"}, status=400)
                    
            # If passed, reset lockout
            if result['passed'] and emp_id:
                try:
                    lockout = LivenessLockout.objects.get(employee_id=emp_id)
                    lockout.failed_attempts = 0
                    lockout.locked_until = None
                    lockout.save()
                except LivenessLockout.DoesNotExist:
                    pass
                    
        except Exception as e:
            # On exception during precheck, allow punch to proceed (fail-open) to avoid blocking users due to bugs
            import traceback
            traceback.print_exc()
            pass
            
        return view_func(viewset_instance, request, *args, **kwargs)

    return _wrapped_view
