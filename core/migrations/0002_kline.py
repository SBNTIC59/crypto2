# Generated by Django 5.1.5 on 2025-02-02 08:08

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0001_initial'),
    ]

    operations = [
        migrations.CreateModel(
            name='Kline',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('symbole', models.CharField(max_length=20)),
                ('intervalle', models.CharField(max_length=5)),
                ('timestamp', models.BigIntegerField()),
                ('open_price', models.FloatField()),
                ('high_price', models.FloatField()),
                ('low_price', models.FloatField()),
                ('close_price', models.FloatField()),
                ('volume', models.FloatField()),
            ],
            options={
                'unique_together': {('symbole', 'intervalle', 'timestamp')},
            },
        ),
    ]
