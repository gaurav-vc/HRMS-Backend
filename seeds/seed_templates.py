import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'core.settings')
django.setup()

from employees.models import OfferLetter, OfferTemplate

OfferLetter.objects.all().delete()
OfferTemplate.objects.all().delete()

t1 = OfferTemplate.objects.create(
    name='Standard Engineer Offer',
    category='Engineering',
    body_html='<div style="font-family: Arial, sans-serif;"><h1 style="color: #0b646c;">Employment Offer</h1><p>Dear <strong>{{candidate_name}}</strong>,</p><p>We are thrilled to offer you the position of <strong>{{designation}}</strong>.</p><p>Your scheduled joining date is <strong>{{joining_date}}</strong>.</p><p>Your annual CTC will be <strong>{{ctc}}</strong>.</p></div>',
    placeholders=['candidate_name', 'designation', 'joining_date', 'ctc']
)

t2 = OfferTemplate.objects.create(
    name='Executive Offer',
    category='Leadership',
    body_html='<div style="font-family: Arial, sans-serif;"><h1 style="color: #1e293b;">Executive Agreement</h1><p>Dear <strong>{{candidate_name}}</strong>,</p><p>It is our pleasure to extend this offer for the role of <strong>{{designation}}</strong>.</p><p>Your compensation is <strong>{{ctc}}</strong>.</p><p>Your start date is <strong>{{joining_date}}</strong>.</p></div>',
    placeholders=['candidate_name', 'designation', 'joining_date', 'ctc']
)

t3 = OfferTemplate.objects.create(
    name='Internship Offer',
    category='Internship',
    body_html='<div style="font-family: Arial, sans-serif;"><h1 style="color: #0f766e;">Internship Offer</h1><p>Hi <strong>{{candidate_name}}</strong>,</p><p>Congratulations! We are offering you an internship as a <strong>{{designation}}</strong>.</p><p>You will start on <strong>{{joining_date}}</strong> with a stipend of <strong>{{ctc}}</strong>.</p></div>',
    placeholders=['candidate_name', 'designation', 'joining_date', 'ctc']
)

print('Successfully created 3 real templates and deleted dummy offers!')
