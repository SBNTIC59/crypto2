import json
import os
import django

# Initialisation de Django
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "trade_binanace.settings")
django.setup()

from core.models import Strategy, Monnaie, SymbolStrategy

# Chargement du fichier JSON de sauvegarde
with open('strategies_backup.json', 'r') as f:
    strategies_data = json.load(f)

# Import des stratégies en base de données
for item in strategies_data:
    strategy, created = Strategy.objects.get_or_create(
        name=item['name'],
        defaults={
            'buy_conditions': item['buy_conditions'],
            'sell_conditions': item['sell_conditions']
        }
    )

    if created:
        print(f"Stratégie '{strategy.name}' importée avec succès.")
    else:
        # Mise à jour des conditions si la stratégie existe déjà
        strategy.buy_conditions = item['buy_conditions']
        strategy.sell_conditions = item['sell_conditions']
        strategy.save()
        print(f"Stratégie '{strategy.name}' mise à jour.")

    # Application de la stratégie à toutes les monnaies via SymbolStrategy
    monnaies = Monnaie.objects.all()
    for monnaie in monnaies:
        symbol_strategy, ss_created = SymbolStrategy.objects.get_or_create(
            symbole=monnaie.symbole,
            strategy=strategy,
            defaults={
                'investment_amount': 100.0,
                'active': True
            }
        )

        if ss_created:
            print(f"Stratégie '{strategy.name}' associée à la monnaie {monnaie.symbole}.")
        else:
            print(f"Stratégie '{strategy.name}' déjà associée à {monnaie.symbole}.")
