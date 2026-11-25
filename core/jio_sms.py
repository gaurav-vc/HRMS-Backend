import logging
import os
import re
import requests
from django.conf import settings

logger = logging.getLogger('hrms.sms.jio')


class JioSMSService:
    """
    Jio DLT / Jio SMS Gateway Integration Service for HRMS.
    Handles DLT-compliant SMS delivery for:
    1. Welcome & Login Credentials Dispatch
    2. Forgot Password OTP Verification
    3. Attendance & General System Notifications
    """

    @staticmethod
    def clean_phone_number(phone: str) -> str:
        """
        Formats phone number into a standard 10-digit or 12-digit format (91XXXXXXXXXX).
        """
        if not phone:
            return ""
        # Remove non-digits
        digits = re.sub(r'\D', '', str(phone))
        # Strip leading 0
        if digits.startswith('0') and len(digits) == 11:
            digits = digits[1:]
        # Add 91 country code if standard 10 digits
        if len(digits) == 10:
            digits = '91' + digits
        return digits

    @classmethod
    def send_sms(cls, phone: str, message: str, template_id: str = None) -> dict:
        """
        Sends an SMS via Jio SMS Gateway / DLT Partner API.
        If credentials are not yet configured or SMS_PROVIDER is 'CONSOLE', logs to console safely.
        """
        cleaned_phone = cls.clean_phone_number(phone)
        if not cleaned_phone:
            logger.warning("[JIO SMS] No valid phone number provided.")
            return {"success": False, "error": "Invalid phone number"}

        sms_provider = getattr(settings, 'SMS_PROVIDER', 'CONSOLE').upper()
        entity_id = getattr(settings, 'JIO_ENTITY_ID', None) or os.getenv('JIO_ENTITY_ID', '')
        sender_id = getattr(settings, 'JIO_SENDER_ID', None) or os.getenv('JIO_SENDER_ID', 'PPULSE')
        api_key = getattr(settings, 'JIO_API_KEY', None) or os.getenv('JIO_API_KEY', '')
        endpoint = getattr(settings, 'JIO_SMS_ENDPOINT', None) or os.getenv('JIO_SMS_ENDPOINT', 'https://api.jio.com/sms/v1/send')

        # If in CONSOLE mode or missing API key, simulate delivery
        if sms_provider != 'JIO' or not api_key:
            masked_phone = cleaned_phone[:4] + '****' + cleaned_phone[-4:] if len(cleaned_phone) >= 8 else cleaned_phone
            logger.info(
                f"[JIO DLT SMS SIMULATED] To: {cleaned_phone} ({masked_phone}) | "
                f"Entity ID: {entity_id or 'NOT_SET'} | Sender: {sender_id} | "
                f"Template ID: {template_id or 'NOT_SET'} | Content: {message}"
            )
            print(f"\n==================== [JIO SMS DISPATCH] ====================")
            print(f"To: {cleaned_phone}")
            print(f"Sender ID (DLT Header): {sender_id}")
            print(f"Entity ID (DLT PE ID): {entity_id or 'Pending in settings'}")
            print(f"Template ID: {template_id or 'Pending in settings'}")
            print(f"Message: {message}")
            print(f"=============================================================\n")
            return {
                "success": True,
                "simulated": True,
                "phone": cleaned_phone,
                "message": message,
            }

        # Real HTTP dispatch to Jio SMS Gateway
        try:
            headers = {
                "Content-Type": "application/json",
                "Authorization": f"Bearer {api_key}" if not api_key.startswith("Bearer") else api_key,
            }
            payload = {
                "entity_id": entity_id,
                "sender_id": sender_id,
                "template_id": template_id or getattr(settings, 'JIO_OTP_TEMPLATE_ID', ''),
                "mobile": cleaned_phone,
                "message": message,
            }

            resp = requests.post(endpoint, json=payload, headers=headers, timeout=8)
            if resp.status_code in (200, 201, 202):
                logger.info(f"[JIO SMS SUCCESS] Sent to {cleaned_phone}: {resp.text}")
                return {"success": True, "response": resp.json() if resp.text.startswith('{') else resp.text}
            else:
                logger.error(f"[JIO SMS FAILED] HTTP {resp.status_code}: {resp.text}")
                return {"success": False, "status_code": resp.status_code, "error": resp.text}
        except Exception as e:
            logger.error(f"[JIO SMS EXCEPTION] Error connecting to Jio SMS Gateway: {e}")
            return {"success": False, "error": str(e)}

    @classmethod
    def send_credentials_sms(cls, phone: str, first_name: str, login_id: str, password: str, login_url: str) -> dict:
        """
        DLT-compliant template dispatch for Employee Credentials.
        """
        template_id = getattr(settings, 'JIO_CREDENTIALS_TEMPLATE_ID', None) or os.getenv('JIO_CREDENTIALS_TEMPLATE_ID', '')
        message = (
            f"Welcome {first_name}! Your HRMS Account has been activated. "
            f"Login ID: {login_id} | Temporary Password: {password} | "
            f"Portal: {login_url} - Please log in and change your password."
        )
        return cls.send_sms(phone=phone, message=message, template_id=template_id)

    @classmethod
    def send_otp_sms(cls, phone: str, otp: str) -> dict:
        """
        DLT-compliant template dispatch for Password Reset OTP.
        """
        template_id = getattr(settings, 'JIO_OTP_TEMPLATE_ID', None) or os.getenv('JIO_OTP_TEMPLATE_ID', '')
        message = (
            f"Your OTP for PeoplePulse HRMS password reset is {otp}. "
            f"Valid for 10 minutes. Do not share this OTP with anyone."
        )
        return cls.send_sms(phone=phone, message=message, template_id=template_id)
