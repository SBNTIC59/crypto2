from rest_framework import viewsets
from django.shortcuts import render
from django.template.loader import render_to_string
from django.http import JsonResponse
from .models import Monnaie, SymbolStrategy
from .serializers import MonnaieSerializer

class MonnaieViewSet(viewsets.ModelViewSet):
    queryset = Monnaie.objects.all()
    serializer_class = MonnaieSerializer

def dashboard(request):
    """ Page principale du dashboard """
    return render(request, "dashboard.html")

def get_monnaies(request):
    """ Retourne la liste des monnaies sous forme HTML pour HTMX """
    symbols = SymbolStrategy.objects.all()
    print("🔍 Monnaies envoyées au template:", symbols)
    return render(request, "partials/monnaies.html", {"monnaies": symbols})




