from django.db import migrations, models

class Migration(migrations.Migration):

    dependencies = [
        ('employees', '0028_alter_employee_email_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='employee',
            name='group_category',
            field=models.CharField(blank=True, db_index=True, default='General', max_length=100, null=True),
        ),
        migrations.AddField(
            model_name='employee',
            name='grade_category',
            field=models.CharField(blank=True, db_index=True, default='Unassigned', max_length=50, null=True),
        ),
    ]
