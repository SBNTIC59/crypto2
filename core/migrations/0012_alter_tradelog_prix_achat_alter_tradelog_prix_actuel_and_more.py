# Generated by Django 5.1.5 on 2025-02-08 07:17

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0011_apikey'),
    ]

    operations = [
        migrations.AlterField(
            model_name='tradelog',
            name='prix_achat',
            field=models.DecimalField(decimal_places=20, default=0.0, max_digits=30),
        ),
        migrations.AlterField(
            model_name='tradelog',
            name='prix_actuel',
            field=models.DecimalField(blank=True, decimal_places=20, max_digits=30, null=True),
        ),
        migrations.AlterField(
            model_name='tradelog',
            name='prix_max',
            field=models.DecimalField(blank=True, decimal_places=20, max_digits=30, null=True),
        ),
    ]
