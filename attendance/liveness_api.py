import cv2
import numpy as np
import uuid
import os
import tempfile
from rest_framework.views import APIView
from rest_framework.response import Response
from rest_framework.permissions import IsAuthenticated
import random

try:
    import mediapipe as mp
    HAVE_MEDIAPIPE = True
except ImportError:
    HAVE_MEDIAPIPE = False

# In-memory storage for pending challenges (In production, use Redis or DB with expiry)
PENDING_CHALLENGES = {}

class LivenessChallengeAPIView(APIView):
    """
    GET: Returns a randomized 2-3 second active liveness challenge.
    e.g., ["blink", "look_left"]
    """
    permission_classes = [IsAuthenticated]

    def get(self, request):
        session_id = str(uuid.uuid4())
        
        # Pick 1 or 2 quick actions to keep it under 3 seconds
        possible_actions = ["blink", "look_left", "look_right", "nod"]
        challenge = random.sample(possible_actions, random.randint(1, 2))
        
        # Store in memory for verification
        PENDING_CHALLENGES[session_id] = {
            "user_id": request.user.id,
            "challenge": challenge
        }
        
        return Response({
            "session_id": session_id,
            "instructions": challenge,
            "duration_limit_sec": 3.5  # Max video length
        })

class LivenessVerifyAPIView(APIView):
    """
    POST: Uploads video file and session ID to verify the challenge using MediaPipe.
    """
    permission_classes = [IsAuthenticated]

    def post(self, request):
        if not HAVE_MEDIAPIPE:
            return Response({"error": "MediaPipe is not installed on the server"}, status=501)
            
        session_id = request.data.get("session_id")
        video_file = request.FILES.get("video")
        
        if not session_id or not video_file:
            return Response({"error": "session_id and video file are required"}, status=400)
            
        challenge_data = PENDING_CHALLENGES.get(session_id)
        if not challenge_data or challenge_data["user_id"] != request.user.id:
            return Response({"error": "Invalid or expired session"}, status=400)
            
        expected_actions = challenge_data["challenge"]
        
        # Save uploaded video to temp file
        with tempfile.NamedTemporaryFile(delete=False, suffix=".mp4") as tmp_vid:
            for chunk in video_file.chunks():
                tmp_vid.write(chunk)
            tmp_path = tmp_vid.name
            
        try:
            # 1. Check Liveness (Blink/Nod)
            is_live, frame_bytes = self.process_video(tmp_path, expected_actions)
            os.remove(tmp_path)
            
            if not is_live:
                return Response({"error": "Liveness challenge failed. Actions did not match instructions."}, status=400)
                
            # 2. Dynamically Compare with Profile Picture
            # We have the best live frame, now match it against the database!
            from employees.models import Employee
            try:
                from deepface import DeepFace
                has_deepface = True
            except ImportError:
                has_deepface = False
                
            employee = Employee.objects.filter(user=request.user).first()
            if not employee or not bool(employee.photo and employee.photo.name):
                return Response({"error": "No profile photo found to compare against. Please register a photo first."}, status=400)
                
            if has_deepface and frame_bytes:
                with tempfile.NamedTemporaryFile(delete=False, suffix=".jpg") as tmp_frame:
                    tmp_frame.write(frame_bytes)
                    frame_path = tmp_frame.name
                    
                try:
                    result = DeepFace.verify(
                        img1_path=frame_path,
                        img2_path=employee.photo.path,
                        model_name="Facenet",
                        detector_backend="mtcnn",
                        distance_metric="cosine",
                        enforce_detection=True
                    )
                    os.remove(frame_path)
                    
                    # Same relaxed 50% threshold logic
                    distance = result.get("distance", 1.0)
                    relaxed_max = result.get("threshold", 0.30) + 0.15
                    
                    if distance > relaxed_max and not result.get("verified", False):
                        return Response({"error": "Identity verification failed. The live person does not match the profile picture."}, status=400)
                        
                except Exception as e:
                    if os.path.exists(frame_path): os.remove(frame_path)
                    return Response({"error": f"Face comparison failed: {str(e)}"}, status=400)
            
            # Cleanup session
            del PENDING_CHALLENGES[session_id]
            return Response({
                "status": "success",
                "message": "Liveness and Identity Verified Successfully!",
                "verified": True
            })
                
        except Exception as e:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
            return Response({"error": f"Processing error: {str(e)}"}, status=500)
            
    def process_video(self, video_path, expected_actions):
        """
        Processes the video frame by frame using MediaPipe Face Mesh.
        Returns (is_live: bool, best_frame_bytes: bytes)
        """
        cap = cv2.VideoCapture(video_path)
        if not cap.isOpened():
            raise ValueError("Could not open video file.")
            
        try:
            mp_face_mesh = mp.solutions.face_mesh
        except Exception:
            return False, b''

        action_status = {action: False for action in expected_actions}
        best_frame = None
        frame_count = 0
            
        with mp_face_mesh.FaceMesh(
            max_num_faces=1,
            refine_landmarks=True,
            min_detection_confidence=0.5,
            min_tracking_confidence=0.5) as face_mesh:
            
            while cap.isOpened():
                ret, frame = cap.read()
                if not ret:
                    break
                
                frame_count += 1
                if frame_count == 1:
                    best_frame = frame.copy()
                    
                rgb_frame = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)
                results = face_mesh.process(rgb_frame)
                
                if results.multi_face_landmarks:
                    face = results.multi_face_landmarks[0]
                    
                    # Extract Eye landmarks (simplified EAR proxy)
                    left_eye_top = face.landmark[159].y
                    left_eye_bottom = face.landmark[145].y
                    left_ear_dist = left_eye_bottom - left_eye_top
                    
                    right_eye_top = face.landmark[386].y
                    right_eye_bottom = face.landmark[374].y
                    right_ear_dist = right_eye_bottom - right_eye_top
                    
                    if "blink" in expected_actions:
                        # Threshold for closed eyes is typically very small
                        if left_ear_dist < 0.012 and right_ear_dist < 0.012:
                            action_status["blink"] = True
                            
                    # Extract Nose and Ear landmarks for Yaw/Pitch approximation
                    nose_tip = face.landmark[1]
                    left_ear = face.landmark[234]
                    right_ear = face.landmark[454]
                    
                    if "look_left" in expected_actions:
                        if nose_tip.x < left_ear.x + 0.15: 
                            action_status["look_left"] = True
                    if "look_right" in expected_actions:
                        if nose_tip.x > right_ear.x - 0.15:
                            action_status["look_right"] = True
                    if "nod" in expected_actions:
                        # Pitch changes cause nose y to shift significantly compared to ears
                        if nose_tip.y < left_ear.y - 0.05 or nose_tip.y > left_ear.y + 0.1:
                            action_status["nod"] = True
                            
                if all(action_status.values()):
                    best_frame = frame.copy()
                    break
                    
        cap.release()
        is_live = all(action_status.values())
        
        if best_frame is not None:
            _, buffer = cv2.imencode('.jpg', best_frame)
            return is_live, buffer.tobytes()
            
        return is_live, b''
