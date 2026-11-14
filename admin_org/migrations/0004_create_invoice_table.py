from django.db import migrations, models
import django.db.models.deletion

class Migration(migrations.Migration):

    dependencies = [
        ('admin_org', '0003_organization_require_full_attendance_for_al'),
    ]

    operations = [
        migrations.SeparateDatabaseAndState(
            state_operations=[],
            database_operations=[
                migrations.CreateModel(
                    name='Invoice',
                    fields=[
                        ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                        ('invoice_number', models.CharField(max_length=50, unique=True)),
                        ('billing_date', models.DateField()),
                        ('due_date', models.DateField()),
                        ('amount', models.DecimalField(decimal_places=2, max_digits=12)),
                        ('status', models.CharField(default='Paid', max_length=20)),
                        ('created_at', models.DateTimeField(auto_now_add=True)),
                        ('organization', models.ForeignKey(on_delete=django.db.models.deletion.CASCADE, related_name='invoices', to='admin_org.organization')),
                    ],
                    options={
                        'db_table': 'organisation_invoice',
                    },
                ),
            ]
        )
    ]

