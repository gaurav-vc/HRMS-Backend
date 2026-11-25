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
        login_url = getattr(settings, 'HRMS_PORTAL_URL', 'http://127.0.0.1:8000')

        send_email_active = False
        send_sms_active = False

        if delivery_method == 'both':
            send_email_active = bool(email)
            send_sms_active = bool(phone)
        elif delivery_method == 'sms':
            send_sms_active = bool(phone)
        elif delivery_method == 'email':
            send_email_active = bool(email)
        else: # 'auto' - trigger on both email and phone when available
            if email:
                send_email_active = True
            if phone:
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
                from_email = getattr(settings, 'DEFAULT_FROM_EMAIL', None) or getattr(settings, 'EMAIL_HOST_USER', None) or 'HRMS Admin <noreply@hrms.local>'
                send_mail(
                    subject,
                    message,
                    from_email,
                    [email],
                    fail_silently=True
                )
                logger.info(f"[EMAIL DISPATCH SUCCESS] Credentials sent to {email}")
            except Exception as e:
                logger.error(f"[EMAIL DISPATCH FAILED] Error sending to {email}: {e}")

        threading.Thread(target=_send, daemon=True).start()

    @classmethod
    def _dispatch_sms_async(cls, first_name, phone, login_id, password, login_url):
        def _send():
            try:
                from core.jio_sms import JioSMSService
                JioSMSService.send_credentials_sms(
                    phone=phone,
                    first_name=first_name,
                    login_id=login_id,
                    password=password,
                    login_url=login_url
                )
            except Exception as e:
                logger.error(f"[SMS DISPATCH ERROR] Failed to send credentials to {phone}: {e}")

        threading.Thread(target=_send, daemon=True).start()
