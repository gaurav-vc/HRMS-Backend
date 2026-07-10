from employees.models import Employee
from organisation.models import Entity

def run():
    lotus = Entity.objects.filter(name__icontains='Lotus').first()
    
    # The exact first names of the people to keep in Lotus
    lotus_names = [
        "Mukund", "Vishal", "Hetal", "Dinesh", 
        "Rajnikant", "Naresh", "Jasmin"
    ]
    
    kept_in_lotus = 0
    removed_from_lotus = 0
    
    for emp in Employee.objects.all():
        is_lotus = False
        # Check if the employee's name matches any of the approved Lotus employees
        for name in lotus_names:
            if name.lower() in emp.first_name.lower() or (emp.last_name and name.lower() in emp.last_name.lower()):
                is_lotus = True
                break
                
        if is_lotus:
            if lotus:
                emp.entity = lotus
                emp.save()
                kept_in_lotus += 1
        else:
            # Remove them from the entity completely so they don't show up in Lotus
            emp.entity = None
            emp.save()
            removed_from_lotus += 1
            
    print(f"Successfully kept {kept_in_lotus} specific employees in Lotus Developers.")
    print(f"Removed the remaining {removed_from_lotus} employees from Lotus.")

if __name__ == '__main__':
    run()
