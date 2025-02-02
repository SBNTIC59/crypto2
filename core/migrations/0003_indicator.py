# Generated by Django 5.1.5 on 2025-02-02 15:18

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0002_kline'),
    ]

    operations = [
        migrations.CreateModel(
            name='Indicator',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('symbole', models.CharField(max_length=20)),
                ('intervalle', models.CharField(max_length=5)),
                ('timestamp', models.BigIntegerField()),
                ('macd', models.FloatField(blank=True, null=True)),
                ('macd_signal', models.FloatField(blank=True, null=True)),
                ('rsi', models.FloatField(blank=True, null=True)),
                ('bollinger_upper', models.FloatField(blank=True, null=True)),
                ('bollinger_lower', models.FloatField(blank=True, null=True)),
            ],
            options={
                'unique_together': {('symbole', 'intervalle', 'timestamp')},
            },
        ),
    ]
