from django.db.models.signals import post_save
from django.dispatch import receiver
from .models import Loan, Reimbursement
from employees.models import Notification, Employee

def get_authorizers(employee):
    # Returns a list of Employees who are authorized to approve requests for this employee
    authorizers = []
    if employee and employee.manager:
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

@receiver(post_save, sender=Loan)
def loan_notification(sender, instance, created, **kwargs):
    if created:
        authorizers = get_authorizers(instance.employee)
        for auth in authorizers:
            Notification.objects.create(
                recipient=auth,
                title="New Loan Request",
                message=f"Loan request of ₹{instance.amount} from {instance.employee.first_name} {instance.employee.last_name} requires your approval.",
                related_employee_id=instance.employee.id
            )
    else:
        # Notify the employee if the status changes to Active or Closed
        if instance.status in ['Active', 'Closed', 'Rejected']:
            action = 'approved' if instance.status == 'Active' else 'rejected/closed'
            Notification.objects.create(
                recipient=instance.employee,
                title=f"Loan Request {instance.status}",
                message=f"Your loan request of ₹{instance.amount} has been {action}.",
                related_employee_id=instance.employee.id
            )

@receiver(post_save, sender=Reimbursement)
def reimbursement_notification(sender, instance, created, **kwargs):
    if created:
        authorizers = get_authorizers(instance.employee)
        for auth in authorizers:
            Notification.objects.create(
                recipient=auth,
                title="New Reimbursement Request",
                message=f"Reimbursement request of ₹{instance.amount} from {instance.employee.first_name} {instance.employee.last_name} requires your approval.",
                related_employee_id=instance.employee.id
            )
    else:
        # Notify the employee if the status changes
        if instance.status in ['Approved', 'Rejected', 'Paid']:
            Notification.objects.create(
                recipient=instance.employee,
                title=f"Reimbursement {instance.status}",
                message=f"Your reimbursement request of ₹{instance.amount} is now {instance.status}.",
                related_employee_id=instance.employee.id
            )
