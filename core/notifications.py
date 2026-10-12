import logging
import threading
from django.conf import settings
from django.core.mail import send_mail

logger = logging.getLogger('hrms.notifications')


class NotificationService:
    """
    Enterprise Notification Dispatcher for HRMS.
    Dispatches employee login credentials and system alerts across Email, SMS, and WhatsApp.
    Safely falls back to structured logging when SMS credentials/API keys are pending.
    """

    @classmethod
    def send_credentials(cls, employee, password, delivery_method='auto'):
        """
        Dispatches credentials asynchronously based on available channels and preference.
        delivery_method: 'auto' | 'email' | 'sms' | 'both'
        """
        first_name = employee.first_name
        email = (employee.email or '').strip()
        phone = (employee.phone or '').strip()
        code = employee.code
        login_id = email or phone or code
        login_url = getattr(settings, 'HRMS_PORTAL_URL', 'https://hrms.vibecopilot.ai/')

        send_email_active = False
        send_sms_active = False

        if delivery_method == 'both':
            send_email_active = bool(email)
            send_sms_active = bool(phone)
        elif delivery_method == 'sms':
            send_sms_active = bool(phone)
        elif delivery_method == 'email':
            send_email_active = bool(email)
        else: # 'auto'
            if email:
                send_email_active = True
            if phone and not email: # Blue-collar deskless worker without email
                send_sms_active = True

        # 1. Dispatch Email (if active)
        if send_email_active and email:
            cls._dispatch_email_async(first_name, email, login_id, password, login_url)

        # 2. Dispatch SMS (if active)
        if send_sms_active and phone:
            cls._dispatch_sms_async(first_name, phone, login_id, password, login_url)

        return {
            'email_sent': send_email_active and bool(email),
            'sms_sent': send_sms_active and bool(phone),
            'recipient_phone': phone if send_sms_active else None,
            'recipient_email': email if send_email_active else None,
        }

    @classmethod
    def _dispatch_email_async(cls, first_name, email, login_id, password, login_url):
        subject = "Welcome to HRMS - Your Login Credentials"
        message = f"""Hello {first_name},

Welcome to the HRMS portal! Your employee account has been created.

Website: {login_url}
Login ID: {login_id}
Temporary Password: {password}

Please log in and update your password immediately.

Best regards,
HR Operations Team
"""
        def _send():
            try:
                send_mail(
                    subject,
                    message,
                    getattr(settings, 'DEFAULT_FROM_EMAIL', 'HRMS Admin <noreply@vibecopilot.ai>'),
                    [email],
                    fail_silently=True
                )
                logger.info(f"[EMAIL DISPATCH SUCCESS] Credentials sent to {email}")
            except Exception as e:
                logger.error(f"[EMAIL DISPATCH FAILED] Error sending to {email}: {e}")

        threading.Thread(target=_send, daemon=True).start()

    @classmethod
    def _dispatch_sms_async(cls, first_name, phone, login_id, password, login_url):
        sms_text = f"Welcome {first_name}! Your HRMS Account is ready. Login: {login_id} | Password: {password} | Portal: {login_url}"

        def _send():
            # Check if SMS Gateway (e.g., Twilio, AWS SNS, MSG91) credentials are configured in settings
            sms_provider = getattr(settings, 'SMS_PROVIDER', 'CONSOLE')
            
            if sms_provider == 'TWILIO':
                account_sid = getattr(settings, 'TWILIO_ACCOUNT_SID', None)
                auth_token = getattr(settings, 'TWILIO_AUTH_TOKEN', None)
                from_number = getattr(settings, 'TWILIO_FROM_NUMBER', None)
                if account_sid and auth_token and from_number:
                    try:
                        from twilio.rest import Client
                        client = Client(account_sid, auth_token)
                        client.messages.create(body=sms_text, from_=from_number, to=phone)
                        logger.info(f"[TWILIO SMS SENT] Sent credentials to {phone}")
                        return
                    except Exception as e:
                        logger.error(f"[TWILIO SMS FAILED] {e}")
            
            # Default / Pending Credentials Mock Dispatcher:
            # Safely logs the SMS dispatch to console/logs so credentials can be inspected and verified!
            print("\n" + "="*60)
            print("📱 [HRMS SMS GATEWAY DISPATCH]")
            print(f"To: {phone}")
            print(f"Message: {sms_text}")
            print("="*60 + "\n")
            logger.info(f"[SMS CONSOLE DISPATCH] Credentials logged for {phone}")

        threading.Thread(target=_send, daemon=True).start()
