from django.core.management.base import BaseCommand
from django.core.mail import EmailMultiAlternatives
from email.mime.image import MIMEImage
from django.template.loader import render_to_string
from django.conf import settings

class Command(BaseCommand):
    help = 'Send a test birthday email to a specific email address'

    def add_arguments(self, parser):
        parser.add_argument('email', type=str, help='Email address to send the test email to')

    def handle(self, *args, **options):
        email = options['email']
        
        # We use dummy data to test the HTML template rendering
        context = {
            'employee_name': "Test Employee",
            'entity_name': "LOTUS Developers",
            'photo_url': None, # We leave this None to test the fallback design. If an employee had a photo, it would render here.
            'use_fallback_cake': True,
        }

        self.stdout.write(f'Rendering email template for {email}...')
        html_message = render_to_string('emails/birthday_email.html', context)
        
        self.stdout.write(f'Attempting to send email via configured SMTP...')
        try:
            msg = EmailMultiAlternatives(
                subject='Happy Birthday!',
                body='Wishing you a fantastic birthday filled with joy, success, and wonderful moments!',
                from_email=settings.DEFAULT_FROM_EMAIL if hasattr(settings, 'DEFAULT_FROM_EMAIL') else 'noreply@hrms.com',
                to=[email]
            )
            msg.attach_alternative(html_message, "text/html")
            
            # Attach the fallback image inline
            try:
                import os
                candidate_paths = [
                    os.path.join(settings.BASE_DIR, 'static', 'cake.jpg'),
                    os.path.join(settings.BASE_DIR, '..', 'HRMS-frontend', 'cake.jpg'),
                    os.path.join(settings.BASE_DIR, 'media', 'cake.jpg'),
                ]
                cake_path = next((p for p in candidate_paths if os.path.exists(p)), None)
                if cake_path:
                    with open(cake_path, "rb") as img_file:
                        cake_img = MIMEImage(img_file.read())
                        cake_img.add_header('Content-ID', '<fallback_cake>')
                        cake_img.add_header('Content-Disposition', 'inline', filename='cake.jpg')
                        msg.attach(cake_img)
            except Exception as e:
                self.stdout.write(self.style.WARNING(f"Could not attach cake image: {e}"))

            msg.send(fail_silently=False)
            self.stdout.write(self.style.SUCCESS(f'Successfully sent test birthday email to {email}! Check your inbox (or spam folder).'))
        except Exception as e:
            self.stdout.write(self.style.ERROR(f'Failed to send email: {e}'))
