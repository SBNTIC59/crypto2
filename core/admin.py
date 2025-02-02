from django.contrib import admin
from .models import Monnaie

@admin.register(Monnaie)
class MonnaieAdmin(admin.ModelAdmin):
    list_display = ('symbole', 'nom')
    search_fields = ('symbole',)


