from django.db import migrations, models

class Migration(migrations.Migration):

    dependencies = [
        ('attendance', '0011_livenesslockout_strictlivenessauditlog'),
    ]

    operations = [
        migrations.AddField(
            model_name='shiftdefinition',
            name='is_ot_enabled',
            field=models.BooleanField(default=True, help_text='Master toggle to enable or disable OT computation for this shift'),
        ),
        migrations.AddField(
            model_name='shiftdefinition',
            name='min_hours_for_ot',
            field=models.DecimalField(decimal_places=2, default=0.0, help_text='Minimum work hours required to qualify for OT (e.g. 10.00). If worked hours < this, OT is 0', max_digits=4),
        ),
        migrations.AddField(
            model_name='shiftdefinition',
            name='ot_calculation_base_hours',
            field=models.DecimalField(decimal_places=2, default=8.0, help_text='Base shift hours subtracted from total work hours once threshold is met (e.g. 8.00)', max_digits=4),
        ),
    ]
