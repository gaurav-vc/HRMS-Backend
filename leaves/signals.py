from django.db.models.signals import pre_save, post_save
from django.dispatch import receiver
from .models import LeaveRequest
from employees.models import Notification

@receiver(post_save, sender=LeaveRequest)
def leave_request_created_notification(sender, instance, created, **kwargs):
    if created:
        # Notify the manager
        employee = instance.employee
        manager = employee.manager
        if manager:
            Notification.objects.create(
                recipient=manager,
                title="New Leave Request",
                message=f"{employee.first_name} {employee.last_name} has requested {instance.leave_type.name} from {instance.start_date} to {instance.end_date}."
            )

@receiver(pre_save, sender=LeaveRequest)
def leave_request_status_notification(sender, instance, **kwargs):
    if instance.pk:
        try:
            old_instance = LeaveRequest.objects.get(pk=instance.pk)
            if old_instance.status == 'Pending' and instance.status in ['Approved', 'Rejected']:
                # Notify the employee
                Notification.objects.create(
                    recipient=instance.employee,
                    title=f"Leave Request {instance.status}",
                    message=f"Your {instance.leave_type.name} request from {instance.start_date} to {instance.end_date} has been {instance.status.lower()}."
                )
        except LeaveRequest.DoesNotExist:
            pass
