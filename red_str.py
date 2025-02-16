from core.models import SymbolStrategy

# Rechercher toutes les stratégies avec l'erreur de frappe
strategies = SymbolStrategy.objects.filter(strategy__sell_conditions__icontains='prix_mmax')

for strategy in strategies:
    sell_conditions = strategy.strategy.sell_conditions
    updated = False

    # Parcours des conditions pour correction
    for condition in sell_conditions.get('conditions', []):
        if 'rules' in condition:
            for rule in condition['rules']:
                if rule.get('metric') == 'prix_mmax / prix_achat':
                    rule['metric'] = 'prix_max / prix_achat'  # Correction de la faute de frappe
                    updated = True

    # Sauvegarder les modifications si nécessaire
    if updated:
        strategy.strategy.sell_conditions = sell_conditions
        strategy.strategy.save()
        print(f"✅ Correction appliquée pour la stratégie de {strategy.symbole}")
