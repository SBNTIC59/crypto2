from django.contrib import admin
from .models import Monnaie, Strategy, TradeLog, APIKey, IndicatorTest, Calculation, CombinedTest

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

@admin.register(Strategy)
class StrategyAdmin(admin.ModelAdmin):
    list_display = ('name', 'buy_test', 'sell_test')

    def formfield_for_foreignkey(self, db_field, request, **kwargs):
        if db_field.name in ('buy_test', 'sell_test'):
            kwargs['queryset'] = CombinedTest.objects.all().order_by('name')
        return super().formfield_for_foreignkey(db_field, request, **kwargs)

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
