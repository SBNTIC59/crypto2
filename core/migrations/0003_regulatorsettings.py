# Generated by Django 5.1.5 on 2025-02-24 04:09

from django.db import migrations, models


class Migration(migrations.Migration):

    dependencies = [
        ('core', '0002_strategy_intervals_strategy_use_bollinger_and_more'),
    ]

    operations = [
        migrations.CreateModel(
            name='RegulatorSettings',
            fields=[
                ('id', models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name='ID')),
                ('seuil_min_traitement', models.FloatField(default=0.5, help_text='Seuil minimum de traitement en secondes')),
                ('duree_surveillance_min', models.IntegerField(default=30, help_text='Durée de surveillance pour le seuil min')),
                ('seuil_max_traitement', models.FloatField(default=3.0, help_text='Seuil maximum de traitement en secondes')),
                ('duree_surveillance_max', models.IntegerField(default=60, help_text='Durée de surveillance pour le seuil max')),
                ('seuil_critique', models.FloatField(default=5.0, help_text='Seuil critique de surcharge')),
                ('duree_surveillance_critique', models.IntegerField(default=30, help_text='Durée de surveillance pour le seuil critique')),
                ('nb_monnaies_max', models.IntegerField(default=50, help_text='Nombre maximum de monnaies actives')),
                ('nb_monnaies_min', models.IntegerField(default=5, help_text='Nombre minimum de monnaies actives')),
                ('reduction_nb_monnaies', models.IntegerField(default=3, help_text='Nombre de monnaies retirées en cas de surcharge')),
                ('max_queue', models.IntegerField(default=10, help_text='Nombre max de threads pour les traitements')),
                ('max_stream_per_ws', models.IntegerField(default=5, help_text='Nombre max de flux WebSocket par connexion')),
                ('duree_limite_ordre', models.FloatField(default=2, help_text='Temps max en secondes pour un ordre')),
                ('nb_messages_flush', models.IntegerField(default=25, help_text='Nombre de messages pour lancer un flush')),
                ('duree_max_flush', models.FloatField(default=5, help_text='Temps max avant flush')),
                ('nb_klines_historique', models.IntegerField(default=100, help_text='Nombre de Klines à charger par intervalle')),
            ],
            options={
                'verbose_name': 'Paramètre de régulation',
                'verbose_name_plural': 'Paramètres de régulation',
            },
        ),
    ]
