from django.core.management.base import BaseCommand
from attendance.models import FaceProfile
from attendance.crypto_utils import CryptoService, AWSKMSMock
import json

class Command(BaseCommand):
    help = 'Wave 12: Breach Response. Rotates the KEK and provisions new DEKs for all biometric records.'

    def handle(self, *args, **kwargs):
        self.stdout.write(self.style.WARNING("INITIATING EMERGENCY KEK ROTATION..."))
        
        profiles = FaceProfile.objects.filter(is_active=True)
        rotated_count = 0
        
        for profile in profiles:
            if profile.encrypted_face_encodings and profile.encrypted_dek:
                # 1. Decrypt with old KEK
                decrypted_payload = CryptoService.decrypt_json(profile.encrypted_face_encodings, profile.encrypted_dek)
                
                # 2. Provision new DEK using the "new" KEK configuration
                new_dek, new_encrypted_dek = AWSKMSMock.generate_data_key()
                
                # 3. Re-encrypt with new DEK
                new_encrypted_payload = CryptoService.encrypt_json(decrypted_payload, new_dek)
                
                profile.encrypted_face_encodings = new_encrypted_payload
                profile.encrypted_dek = new_encrypted_dek
                profile.save()
                rotated_count += 1
                
        self.stdout.write(self.style.SUCCESS(f"SUCCESS: {rotated_count} biometric records cryptographically rotated."))
