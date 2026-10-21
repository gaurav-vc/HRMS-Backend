from django.db import migrations, models

class Migration(migrations.Migration):

    dependencies = [
        ('organisation', '0001_initial'),
        ('announcements', '0001_initial'),
    ]

    operations = [
        migrations.AlterField(
            model_name='announcement',
            name='audience_type',
            field=models.CharField(choices=[('EVERYONE', 'Everyone'), ('ROLE', 'Specific Role(s)'), ('DEPARTMENT', 'Department'), ('INDIVIDUAL', 'Individual Employee')], default='EVERYONE', max_length=20),
        ),
        migrations.AddField(
            model_name='announcement',
            name='target_roles',
            field=models.ManyToManyField(blank=True, related_name='announcements', to='organisation.role'),
        ),
    ]
