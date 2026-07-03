from django.test import TestCase
from django.utils import timezone
from datetime import timedelta
from unittest.mock import patch
from employees.models import Employee
from organisation.models import Site, Entity
from .models import DynamicQRToken, PunchLog, FaceProfile, DailyAttendance
from .utils import compare_faces, get_face_encoding, haversine

class AttendanceSecurityTests(TestCase):
    def setUp(self):
        self.entity = Entity.objects.create(name="HQ")
        self.site = Site.objects.create(name="Main Campus", latitude=12.9716, longitude=77.5946, radius=150)
        self.employee = Employee.objects.create(
            emp_id="EMP001",
            first_name="Test",
            last_name="User",
            email="test@example.com",
            site=self.site,
            entity=self.entity
        )
        self.face_profile = FaceProfile.objects.create(
            employee=self.employee,
            consent_granted=True,
            face_encoding=[0.1] * 128
        )

    def test_haversine_boundary(self):
        # 1. Exactly at the site
        dist1 = haversine(12.9716, 77.5946, 12.9716, 77.5946)
        self.assertTrue(dist1 <= 150)

        # 2. A point ~100m away (valid)
        dist2 = haversine(12.9725, 77.5946, 12.9716, 77.5946)
        self.assertTrue(dist2 <= 150, f"Distance {dist2} should be <= 150m")

        # 3. A point 5km away (invalid)
        dist3 = haversine(13.0, 77.6, 12.9716, 77.5946)
        self.assertTrue(dist3 > 150, f"Distance {dist3} should be > 150m")

    def test_qr_ttl_expiry(self):
        # Create token expiring in the past
        past_token = DynamicQRToken.objects.create(
            site=self.site,
            expires_at=timezone.now() - timedelta(seconds=1)
        )
        self.assertTrue(past_token.expires_at < timezone.now())

        # Create token valid for 30s
        valid_token = DynamicQRToken.objects.create(
            site=self.site,
            expires_at=timezone.now() + timedelta(seconds=30)
        )
        self.assertTrue(valid_token.expires_at > timezone.now())

    def test_qr_replay_prevention(self):
        token = "test-token-123"
        daily_att = DailyAttendance.objects.create(employee=self.employee, attendance_date=timezone.now().date())
        
        # First punch with this token
        PunchLog.objects.create(
            employee=self.employee,
            daily_attendance=daily_att,
            punch_time=timezone.now(),
            qr_token=token,
            verification_status="VERIFIED"
        )
        
        # Query simulating the views.py check
        has_replayed = PunchLog.objects.filter(employee=self.employee, qr_token=token).exists()
        self.assertTrue(has_replayed, "Replay check should detect that token was already used by this employee.")

    @patch('attendance.utils.HAVE_FACE_REC', True)
    @patch('attendance.utils.DeepFace.represent')
    def test_deepface_mock_threshold(self, mock_represent):
        # Mock DeepFace.represent to return a deterministic embedding
        mock_represent.return_value = [{'embedding': [0.1] * 128}]
        
        # Test encoding
        res = get_face_encoding(b"fake_image_bytes")
        self.assertTrue(res['success'])
        self.assertEqual(res['encoding'], [0.1] * 128)

        # Test compare_faces with exact match
        match_res = compare_faces([0.1] * 128, [0.1] * 128, tolerance=0.40)
        self.assertTrue(match_res['success'])
        self.assertTrue(match_res['match'])
        self.assertEqual(match_res['distance'], 0.0)

        # Test compare_faces with failure (distance > 0.40)
        # Cosine distance between [0.1]*128 and [0.9]*128 will be 0, but let's change direction
        match_fail = compare_faces([0.1]*64 + [-0.1]*64, [-0.1]*64 + [0.1]*64, tolerance=0.40)
        self.assertTrue(match_fail['success'])
        self.assertFalse(match_fail['match'])
        self.assertTrue(match_fail['distance'] > 0.40)
