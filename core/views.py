from rest_framework import viewsets
from django.shortcuts import render
from django.template.loader import render_to_string
from django.http import JsonResponse
from .models import Monnaie, Kline, Indicator
from .serializers import MonnaieSerializer


class MonnaieViewSet(viewsets.ModelViewSet):
    queryset = Monnaie.objects.all()
    serializer_class = MonnaieSerializer

def dashboard(request):
    """ Page principale du dashboard """
    return render(request, "dashboard.html")

def get_monnaies(request):
    """ Retourne la liste des monnaies sous forme HTML pour HTMX """
    symbols = Monnaie.objects.all()
    print("🔍 Monnaies envoyées au template:", symbols.nom)
    return render(request, "partials/monnaies.html", {"monnaies": symbols.nom})

from django.http import JsonResponse
from core.models import Monnaie, Kline, Indicator

def get_dashboard_data(request):
    """
    Retourne les informations des monnaies avec indicateurs organisés par intervalle,
    triées par init=True en premier puis par stoch_rsi sur 1m.
    """
    monnaies_data = []

    for monnaie in Monnaie.objects.all():
        last_kline = Kline.objects.filter(symbole=monnaie.symbole, intervalle="1m").order_by("-timestamp").first()
        prix_actuel = float(last_kline.close_price) if last_kline else None

        klines_count = {
            interval: Kline.objects.filter(symbole=monnaie.symbole, intervalle=interval).count()
            for interval in ["1m", "3m", "5m", "15m", "1h", "4h", "1d"]
        }

        indicateurs_par_intervalle = {}
        stoch_rsi_1m = None

        for interval in ["1m", "3m", "5m", "15m", "1h", "4h", "1d"]:
            last_indicator = Indicator.objects.filter(symbole=monnaie.symbole, intervalle=interval).order_by("-timestamp").first()
            if last_indicator:
                indicateurs_par_intervalle[interval] = {
                    "macd": getattr(last_indicator, "macd", None),
                    "rsi": getattr(last_indicator, "rsi", None),
                    "stoch_rsi": getattr(last_indicator, "stoch_rsi", None),
                    "bollinger_middle": getattr(last_indicator, "bollinger_middle", None),
                }
                # On récupère le stoch_rsi de l'intervalle 1m pour le tri
                if interval == "1m":
                    stoch_rsi_1m = last_indicator.stoch_rsi

        monnaies_data.append({
            "symbole": monnaie.symbole,
            "init": monnaie.init,
            "prix_actuel": prix_actuel,
            "klines_count": klines_count,
            "indicateurs": indicateurs_par_intervalle,
            "stoch_rsi_1m": stoch_rsi_1m if stoch_rsi_1m is not None else float('inf')  # Pour que None soit en dernier au tri
        })

    # Tri : d'abord sur init=True, puis par stoch_rsi_1m croissant
    monnaies_data = sorted(
        monnaies_data,
        key=lambda x: (not x["init"], x["stoch_rsi_1m"])
    )

    return render(request, "monnaies.html", {"monnaies": monnaies_data})

