from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import RegularizationRequest
from employees.models import Notification, Employee

def get_authorizers(employee):
    # Returns a list of Employees who are authorized to approve requests for this employee
    authorizers = []
    if employee and getattr(employee, 'manager', None):
        authorizers.append(employee.manager)
    else:
        # Fallback to HR Admin or Site Admin
        admins = Employee.objects.filter(user__role__in=['HR Admin', 'Site Admin'])
        if admins.exists():
            authorizers.extend(list(admins))
        else:
            # Fallback to superusers
            superusers = Employee.objects.filter(user__is_superuser=True)
            authorizers.extend(list(superusers))
    return list(set(authorizers))  # Unique authorized employees

@receiver(post_save, sender=RegularizationRequest)
def regularization_notification(sender, instance, created, **kwargs):
    if created:
        authorizers = get_authorizers(instance.employee)
        for auth in authorizers:
            Notification.objects.create(
                recipient=auth,
                title="New Regularization Request",
                message=f"Regularization request for {instance.attendance_date} from {instance.employee.first_name} {instance.employee.last_name} requires your approval.",
                related_employee_id=instance.employee.id
            )
    else:
        # Notify the employee if the status changes
        if instance.status in ['Approved', 'Rejected']:
            Notification.objects.create(
                recipient=instance.employee,
                title=f"Regularization {instance.status}",
                message=f"Your regularization request for {instance.attendance_date} has been {instance.status.lower()}.",
                related_employee_id=instance.employee.id
            )
