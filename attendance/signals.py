from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import RegularizationRequest
from employees.models import Notification, Employee

def get_authorizers(employee):
    # Returns a list of Employees who are authorized to approve requests for this employee
    from authentication.permissions import get_reporting_persons
    reporters = get_reporting_persons(employee)
    if reporters:
        return reporters
    
    # Fallback only if no manager and no reporting role configured
    admins = Employee.objects.filter(dynamic_role__name__in=['HR Admin', 'Site Admin'], status='Active')
    if employee and employee.site_id:
        admins = admins.filter(site_id=employee.site_id)
    if not admins.exists():
        admins = Employee.objects.filter(role__in=['admin', 'org_admin', 'site_admin'], status='Active')
        if employee and employee.site_id:
            admins = admins.filter(site_id=employee.site_id)
    return list(set(admins))

@receiver(post_save, sender=RegularizationRequest)
def regularization_notification(sender, instance, created, **kwargs):
    if kwargs.get('raw', False):
        return
        
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
