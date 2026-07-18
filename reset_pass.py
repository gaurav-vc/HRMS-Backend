import os
import django
import sys

sys.path.append(os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

from django.contrib.auth.models import User

def reset():
    email = "gauravkokane05@gmail.com"
    try:
        u = User.objects.get(username=email)
        u.set_password('Lotus@123')
        u.is_superuser = False
        u.is_active = True
        u.save()
        print("SUCCESS! Password forcibly reset to Lotus@123.")
    except Exception as e:
        print(e)

if __name__ == '__main__':
    reset()
