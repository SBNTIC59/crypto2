# Generated by Django 5.1.5 on 2025-02-16 08:05

import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0020_remove_strategy_combined_test_strategy_buy_test_and_more'),
    ]

    operations = [
        migrations.RemoveField(
            model_name='tradelog',
            name='strategy_json',
        ),
        migrations.AddField(
            model_name='tradelog',
            name='strategy',
            field=models.ForeignKey(blank=True, null=True, on_delete=django.db.models.deletion.SET_NULL, to='core.strategy'),
        ),
    ]
