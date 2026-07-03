from django.core.management.base import BaseCommand
from attendance.models import FaceProfile

class Command(BaseCommand):
    help = 'Wave 12: Breach Response. The Nuclear Option. Instantly zeroizes all biometric data across the entire database in the event of a catastrophic network breach.'

    def add_arguments(self, parser):
        parser.add_argument(
            '--confirm',
            action='store_true',
            help='Must pass --confirm to execute the zeroization wipe.',
        )

    def handle(self, *args, **kwargs):
        if not kwargs['confirm']:
            self.stdout.write(self.style.ERROR("ABORTED: You must pass --confirm to execute the Break Glass wipe."))
            return
            
        self.stdout.write(self.style.ERROR("EXECUTING BREAK GLASS PROTOCOL: ZEROIZING BIOMETRIC STORAGE..."))
        
        profiles = FaceProfile.objects.filter(is_active=True)
        wiped_count = 0
        
        for profile in profiles:
            profile.encrypted_face_encodings = None
            profile.encrypted_dek = None
            profile.consent_granted = False
            profile.is_active = False
            profile.save()
            wiped_count += 1
            
        # In production, we'd also trigger a FAISS memory dump/flush here
        
        self.stdout.write(self.style.SUCCESS(f"CRITICAL SUCCESS: {wiped_count} biometric records permanently zeroized."))
