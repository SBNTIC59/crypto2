from django.contrib import admin
from .models import Monnaie, Strategy, SymbolStrategy, TradeLog

@admin.register(Monnaie)
class MonnaieAdmin(admin.ModelAdmin):
    list_display = ('symbole', 'nom')
    search_fields = ('symbole',)

@admin.register(Strategy)
class StrategyAdmin(admin.ModelAdmin):
    list_display = ("name",)
    search_fields = ("name",)
    list_filter = ("name",)

@admin.register(SymbolStrategy)
class SymbolStrategyAdmin(admin.ModelAdmin):
    list_display = ("symbole", "strategy", "entry_price", "active")
    search_fields = ("symbole",)
    list_filter = ("strategy", "active")

@admin.register(TradeLog)
class TradeAdmin(admin.ModelAdmin):
    list_display = ("symbole", "prix_achat", "prix_actuel", "status", "strategy_json")
    list_filter = ("status", "symbole")
    search_fields = ("symbole",)