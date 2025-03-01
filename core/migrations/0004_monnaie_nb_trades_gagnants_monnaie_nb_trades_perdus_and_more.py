# Generated by Django 5.1.5 on 2025-02-28 04:38

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0003_regulatorsettings'),
    ]

    operations = [
        migrations.AddField(
            model_name='monnaie',
            name='nb_trades_gagnants',
            field=models.IntegerField(default=0),
        ),
        migrations.AddField(
            model_name='monnaie',
            name='nb_trades_perdus',
            field=models.IntegerField(default=0),
        ),
        migrations.AddField(
            model_name='monnaie',
            name='total_profit',
            field=models.FloatField(default=0.0),
        ),
        migrations.AddField(
            model_name='monnaie',
            name='win_rate',
            field=models.FloatField(default=0.0),
        ),
    ]
