import datetime
import logging
from django.core.mail import EmailMultiAlternatives
from email.mime.image import MIMEImage
from django.template.loader import render_to_string
from django.utils import timezone
from django.conf import settings
from .models import Employee

logger = logging.getLogger(__name__)

def trigger_birthday_emails():
    """
    Checks for employees whose birthday is today and sends them a birthday email.
    """
    today = timezone.now().date()
    
    # Find employees whose birthday is today
    # Note: SQLite doesn't support dob__day/month out of the box in some older django versions without extract, 
    # but in modern Django it works. If it fails, we can filter in python.
    try:
        birthday_employees = Employee.objects.filter(
            dob__day=today.day,
            dob__month=today.month,
            status='Active'
        )
    except Exception as e:
        logger.error(f"Error querying birthdays: {e}")
        # Fallback for SQLite date extraction issues
        birthday_employees = [
            emp for emp in Employee.objects.filter(status='Active') 
            if emp.dob and emp.dob.day == today.day and emp.dob.month == today.month
        ]

    if not birthday_employees:
        logger.info(f"No birthdays found for {today}")
        return 0

    emails_sent = 0
    for employee in birthday_employees:
        if not employee.email:
            continue
            
        # Get entity name
        entity_name = employee.entity.name if employee.entity else "Our Company"
        
        # Get photo URL
        photo_url = None
        if employee.photo:
            # Construct absolute URL for the email
            # Assumes SITE_URL is defined, otherwise uses a placeholder or just media url if relative works (many email clients block relative)
            # In local dev, we just use the MEDIA_URL
            photo_url = f"{settings.MEDIA_URL}{employee.photo}"

        # Context for the template
        context = {
            'employee_name': f"{employee.first_name} {employee.last_name}",
            'entity_name': entity_name,
            'photo_url': photo_url,
            'use_fallback_cake': not bool(photo_url),
        }

        # Render HTML
        html_message = render_to_string('emails/birthday_email.html', context)
        
        # Send Email
        try:
            msg = EmailMultiAlternatives(
                subject='Happy Birthday!',
                body='Wishing you a fantastic birthday filled with joy, success, and wonderful moments!',
                from_email=settings.DEFAULT_FROM_EMAIL if hasattr(settings, 'DEFAULT_FROM_EMAIL') else 'noreply@hrms.com',
                to=[employee.email]
            )
            msg.attach_alternative(html_message, "text/html")
            
            if not photo_url:
                try:
                    with open(r"c:\Users\MC VIP\OneDrive\Desktop\HRMS\frontend\cake.jpg", "rb") as img_file:
                        cake_img = MIMEImage(img_file.read())
                        cake_img.add_header('Content-ID', '<fallback_cake>')
                        cake_img.add_header('Content-Disposition', 'inline', filename='cake.jpg')
                        msg.attach(cake_img)
                except Exception as e:
                    logger.warning(f"Could not attach cake image: {e}")

            msg.send(fail_silently=False)
            emails_sent += 1
            logger.info(f"Sent birthday email to {employee.email}")
        except Exception as e:
            logger.error(f"Failed to send birthday email to {employee.email}: {e}")

    return emails_sent
