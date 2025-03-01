from django.contrib import admin
from .models import Monnaie, Strategy, TradeLog, APIKey, IndicatorTest, Calculation, CombinedTest, RegulatorSettings
from .utils import update_monnaie_strategy
from django import forms
from django.conf import settings

@admin.register(Monnaie)
class MonnaieAdmin(admin.ModelAdmin):
    list_display = ('symbole', 'nom', 'init', 'strategy', 'prix_actuel', 'prix_max', 'prix_min')
    list_editable = ('strategy',)
    list_filter = ('init', 'strategy')
    search_fields = ('symbole', 'nom')
    actions = ['assign_strategy']

    def assign_strategy(self, request, queryset):
        from django.shortcuts import render, redirect
        from django import forms
        from core.models import Strategy

        class StrategyForm(forms.Form):
            strategy = forms.ModelChoiceField(queryset=Strategy.objects.all(), required=True)

        if 'apply' in request.POST:
            form = StrategyForm(request.POST)
            if form.is_valid():
                strategy = form.cleaned_data['strategy']
                count = 0
                for monnaie in queryset:
                    monnaie.strategy = strategy
                    monnaie.save()
                    count += 1
                self.message_user(request, f'{count} monnaies ont été mises à jour avec la stratégie {strategy.name}.')
                return redirect(request.get_full_path())  # Retourne sur la page des monnaies

        else:
            form = StrategyForm()

        return render(request, 'admin/assign_strategy.html', {
            'monnaies': queryset,
            'form': form,
            'action_name': 'assign_strategy',
        })

    assign_strategy.short_description = "Attribuer une stratégie aux monnaies sélectionnées"

    def save_model(self, request, obj, form, change):
        """
        Intercepte la sauvegarde pour gérer les changements de stratégie.
        Si la stratégie est modifiée, elle met à jour la monnaie correctement.
        """
        if "strategy" in form.changed_data:
            update_monnaie_strategy(obj, obj.strategy)
        super().save_model(request, obj, form, change)



@admin.register(Strategy)
class StrategyAdmin(admin.ModelAdmin):
    list_display = ('name', 'buy_test', 'sell_test')

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name in ('buy_test', 'sell_test'):
            kwargs['queryset'] = CombinedTest.objects.all().order_by('name')
        return super().formfield_for_foreignkey(db_field, request, **kwargs)
    
    def save_model(self, request, obj, form, change):
        """
        Intercepte la sauvegarde pour vérifier si la stratégie est modifiée.
        Si elle l’est, met à jour toutes les monnaies utilisant cette stratégie.
        """
        super().save_model(request, obj, form, change)

        if change:
            monnaies_associees = Monnaie.objects.filter(strategy=obj)
            for monnaie in monnaies_associees:
                update_monnaie_strategy(monnaie, obj)
            print(f"🔄 [UPDATE] Mise à jour des monnaies utilisant {obj.nom}")



@admin.register(TradeLog)
class TradeLogAdmin(admin.ModelAdmin):
    list_display = ('symbole', 'prix_achat', 'prix_max', 'prix_actuel', 'status')
    list_filter = ('status',)

@admin.register(APIKey)
class APIKeyAdmin(admin.ModelAdmin):
    list_display = ('name', 'api_key', 'secret_key')

@admin.register(IndicatorTest)
class IndicatorTestAdmin(admin.ModelAdmin):
    list_display = ('name', 'indicator', 'interval', 'operator', 'threshold_value', 'threshold_indicator_test', 'threshold_calculation')

@admin.register(Calculation)
class CalculationAdmin(admin.ModelAdmin):
    list_display = ('name', 'expression')
    filter_horizontal = ('sub_calculations',)

@admin.register(CombinedTest)
class CombinedTestAdmin(admin.ModelAdmin):
    list_display = ('name', 'condition_type')
    filter_horizontal = ('tests', 'sub_combined_tests')

@admin.register(RegulatorSettings)
class RegulatorSettingsAdmin(admin.ModelAdmin):
    """Permet de gérer les paramètres de régulation directement depuis l'admin Django"""
    
    list_display = (
        "seuil_min_traitement", "seuil_max_traitement", "seuil_critique",
        "nb_monnaies_max", "nb_monnaies_min", "reduction_nb_monnaies"
    )

    fieldsets = (
        ("Seuils de Régulation", {
            "fields": ("seuil_min_traitement", "duree_surveillance_min",
                       "seuil_max_traitement", "duree_surveillance_max",
                       "seuil_critique", "duree_surveillance_critique")
        }),
        ("Nombre de Monnaies", {
            "fields": ("nb_monnaies_max", "nb_monnaies_min", "reduction_nb_monnaies")
        }),
        ("Gestion des WebSockets et Queue", {
            "fields": ("max_queue", "max_stream_per_ws", "duree_limite_ordre")
        }),
        ("Gestion du Flush des Klines", {
            "fields": ("nb_messages_flush", "duree_max_flush")
        }),
        ("Récupération de l'historique", {
            "fields": ("nb_klines_historique",)
        }),
    )













