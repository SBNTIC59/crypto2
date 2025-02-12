# Generated by Django 5.1.5 on 2025-02-03 14:37

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0008_remove_tradelog_duration_remove_tradelog_entry_price_and_more'),
    ]

    operations = [
        migrations.AddField(
            model_name='tradelog',
            name='duration',
            field=models.FloatField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='tradelog',
            name='entry_time',
            field=models.DateTimeField(auto_now_add=True, default='2025-02-03'),
            preserve_default=False,
        ),
        migrations.AddField(
            model_name='tradelog',
            name='exit_time',
            field=models.DateTimeField(blank=True, null=True),
        ),
        migrations.AddField(
            model_name='tradelog',
            name='trade_result',
            field=models.FloatField(blank=True, null=True),
        ),
    ]
