# Generated by Django 5.1.5 on 2025-02-15 17:44

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0015_calculation_name_calculation_sub_calculations'),
    ]

    operations = [
        migrations.AddField(
            model_name='monnaie',
            name='strategy',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to='core.strategy'),
        ),
    ]
