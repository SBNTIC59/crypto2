# Generated by Django 5.1.5 on 2025-02-03 16:03

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0009_tradelog_duration_tradelog_entry_time_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='tradelog',
            name='investment_amount',
            field=models.DecimalField(decimal_places=2, default=0, max_digits=15),
        ),
        migrations.AddField(
            model_name='tradelog',
            name='quantity',
            field=models.DecimalField(decimal_places=8, default=0, max_digits=20),
        ),
    ]
