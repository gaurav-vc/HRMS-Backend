import uuid
from django.conf import settings
from django.db import migrations, models
import django.db.models.deletion

class Migration(migrations.Migration):

    initial = True

    dependencies = [
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
        ('organisation', '0001_initial'),
        ('employees', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='Announcement',
            fields=[
                ('id', models.UUIDField(default=uuid.uuid4, editable=False, primary_key=True, serialize=False)),
                ('title', models.CharField(max_length=255)),
                ('content', models.TextField()),
                ('priority', models.CharField(choices=[('Normal', 'Normal'), ('Important', 'Important'), ('Urgent', 'Urgent')], default='Normal', max_length=20)),
                ('attachment', models.FileField(blank=True, null=True, upload_to='announcements/%Y/%m/')),
                ('attachment_name', models.CharField(blank=True, max_length=255, null=True)),
                ('audience_type', models.CharField(choices=[('EVERYONE', 'Everyone'), ('DEPARTMENT', 'Department'), ('INDIVIDUAL', 'Individual Employee')], default='EVERYONE', max_length=20)),
                ('is_active', models.BooleanField(default=True)),
                ('created_at', models.DateTimeField(auto_now_add=True)),
                ('updated_at', models.DateTimeField(auto_now=True)),
                ('created_by', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to=settings.AUTH_USER_MODEL)),
                ('entity', models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.CASCADE, related_name='announcements', to='organisation.entity')),
                ('target_departments', models.ManyToManyField(blank=True, related_name='announcements', to='organisation.department')),
                ('target_employees', models.ManyToManyField(blank=True, related_name='direct_announcements', to='employees.employee')),
            ],
            options={
                'ordering': ['-created_at'],
            },
        ),
        migrations.CreateModel(
            name='AnnouncementReceipt',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('read_at', models.DateTimeField(auto_now_add=True)),
                ('announcement', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='receipts', to='announcements.announcement')),
                ('employee', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='announcement_receipts', to='employees.employee')),
            ],
            options={
                'unique_together': {('announcement', 'employee')},
            },
        ),
    ]
