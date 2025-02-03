# Generated by Django 5.1.5 on 2025-02-02 18:15

import django.db.models.deletion
import django.utils.timezone
from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0005_strategy_symbolstrategy'),
    ]

    operations = [
        migrations.CreateModel(
            name='TradeLog',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('symbole', models.CharField(max_length=20)),
                ('entry_price', models.FloatField()),
                ('exit_price', models.FloatField(blank=True, null=True)),
                ('trade_result', models.FloatField(blank=True, null=True)),
                ('entry_time', models.DateTimeField(default=django.utils.timezone.now)),
                ('exit_time', models.DateTimeField(blank=True, null=True)),
                ('duration', models.FloatField(blank=True, null=True)),
                ('status', models.CharField(choices=[('open', 'En cours'), ('closed', 'Fermé')], default='open', max_length=10)),
                ('strategy', models.ForeignKey(null=True, on_delete=django.db.models.deletion.SET_NULL, to='core.strategy')),
            ],
        ),
    ]
