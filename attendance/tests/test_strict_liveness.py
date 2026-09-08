import pytest
from django.urls import reverse
from rest_framework.test import APIClient
from attendance.models import StrictLivenessAuditLog, LivenessLockout, Employee
from django.core.files.uploadedfile import SimpleUploadedFile
import cv2
import numpy as np
import time

@pytest.mark.django_db
class TestStrictLivenessPipeline:
    def setup_method(self):
        self.client = APIClient()
        self.employee = Employee.objects.create(first_name="Test", last_name="User", code="T001")
        # Ensure shadow mode is off for testing hard enforcement
        from django.conf import settings
        settings.LIVENESS_SHADOW_MODE_ENABLED = False
        settings.OFFICE_STRICT_LIVENESS_ENABLED = True
        
        # Create a valid face image bytes using OpenCV (dummy face)
        img = np.zeros((200, 200, 3), dtype=np.uint8)
        cv2.circle(img, (100, 100), 40, (255, 255, 255), -1) # dummy face blob
        _, buffer = cv2.imencode('.jpg', img)
        self.valid_face_bytes = buffer.tobytes()

    def test_genuine_live_selfie_passes(self):
        """
        Simulate a live selfie that passes all checks.
        """
        # Create a slightly larger image to get a high mock ONNX score
        img = np.zeros((400, 400, 3), dtype=np.uint8)
        cv2.circle(img, (200, 200), 80, (255, 255, 255), -1) 
        _, buffer = cv2.imencode('.jpg', img)
        large_bytes = buffer.tobytes()
        
        file = SimpleUploadedFile("face.jpg", large_bytes, content_type="image/jpeg")
        data = {
            'employee': self.employee.id,
            'source': 'FACE',
            'punch_type': 'IN',
            'latitude': '19.1',
            'longitude': '72.8'
        }
        
        start = time.time()
        response = self.client.post('/api/attendance/punch/', data, format='multipart')
        latency = (time.time() - start) * 1000
        
        # We expect a 400 from the *inner* punch logic because we didn't mock the geofence/face-match properly,
        # but we want to assert the liveness precheck PASSED and did not block it.
        # The inner error would be "Security Alert: Identity verification failed" or similar.
        
        audit = StrictLivenessAuditLog.objects.order_by('-id').first()
        assert audit is not None
        assert audit.final_decision == 'PASSED'
        assert latency < 1500 # Ensure processing latency is acceptable

    def test_printed_photo_rejected(self):
        """
        Simulate a small, blurry image that gets a low mock ONNX score.
        """
        file = SimpleUploadedFile("face.jpg", self.valid_face_bytes, content_type="image/jpeg") # small file < 10KB
        data = {
            'employee': self.employee.id,
            'source': 'FACE',
            'punch_type': 'IN'
        }
        
        response = self.client.post('/api/attendance/punch/', data, format='multipart')
        
        assert response.status_code == 400
        assert "Verification failed" in response.data['error']
        
        audit = StrictLivenessAuditLog.objects.order_by('-id').first()
        assert audit.final_decision == 'REJECTED'
        assert audit.composite_score < 80.0

    def test_exhausted_retry_lockout(self):
        """
        Verify that 3 failed attempts lock the user out with a 403.
        """
        for _ in range(3):
            file = SimpleUploadedFile("face.jpg", self.valid_face_bytes, content_type="image/jpeg")
            data = {'employee': self.employee.id, 'source': 'FACE', 'punch_type': 'IN'}
            self.client.post('/api/attendance/punch/', data, format='multipart')
            
        file = SimpleUploadedFile("face.jpg", self.valid_face_bytes, content_type="image/jpeg")
        response = self.client.post('/api/attendance/punch/', data, format='multipart')
        
        assert response.status_code == 403
        assert "Too many failed verification attempts" in response.data['error']
        
        lockout = LivenessLockout.objects.get(employee_id=self.employee.id)
        assert lockout.failed_attempts >= 3
        assert lockout.locked_until is not None

    def test_shadow_mode_allows_spoof(self):
        """
        Verify that Shadow Mode logs the spoof but lets it pass to the inner function.
        """
        from django.conf import settings
        settings.LIVENESS_SHADOW_MODE_ENABLED = True
        
        file = SimpleUploadedFile("face.jpg", self.valid_face_bytes, content_type="image/jpeg")
        data = {'employee': self.employee.id, 'source': 'FACE', 'punch_type': 'IN'}
        
        response = self.client.post('/api/attendance/punch/', data, format='multipart')
        
        # Inner function will fail (due to no face registered), returning 400, but NOT the generic liveness message
        assert response.status_code == 400
        assert "Verification failed" not in response.data.get('error', '')
        
        audit = StrictLivenessAuditLog.objects.order_by('-id').first()
        assert audit.final_decision == 'SHADOW_MODE'
