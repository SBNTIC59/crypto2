from rest_framework import viewsets
from django.shortcuts import render
from django.template.loader import render_to_string
from django.http import JsonResponse
from .models import Monnaie, Kline, Indicator, TradeLog
from .serializers import MonnaieSerializer
from .utils import get_trade_statistics
from django.shortcuts import render, get_object_or_404
from datetime import datetime
from .utils import INTERVALS
from django.db.models import Sum, Avg, Min, Max, Count, Q


def monnaie_detail(request, symbole):
    monnaie = get_object_or_404(Monnaie, symbole=symbole)

    # Charger les dernières Klines par intervalle
    klines_par_interval = {}
    for interval in INTERVALS:
        klines_par_interval[interval] = Kline.objects.filter(
            symbole=monnaie.symbole,
            intervalle=interval
        ).order_by('-timestamp')[:5]

    # Charger les trades associés à cette monnaie
    trades = monnaie.trades.all().order_by('-entry_time')

    # Passer les données à la vue
    return render(
        request,
        'monnaie_detail.html',
        {
            'monnaie': monnaie,
            'intervals': INTERVALS,
            'klines_par_interval': klines_par_interval,
            'trades': trades,
        }
    )

def stats_view(request):
    stats = get_trade_statistics()
    return render(request, 'stats.html', {'stats': stats})

def stats_partial(request):
    stats = get_trade_statistics()
    return render(request, 'partials/stats_partial.html', {'stats': stats})

class MonnaieViewSet(viewsets.ModelViewSet):
    queryset = Monnaie.objects.all()
    serializer_class = MonnaieSerializer

def dashboard(request):
    """ Page principale du dashboard """
    return render(request, "dashboard.html")

def get_monnaies(request):
    monnaies = Monnaie.objects.annotate(
        nb_trades=Count('trades'),
        nb_trades_win=Count('trades', filter=Q(trades__status='closed', trades__trade_result__gt=0)),
        nb_trades_loss=Count('trades', filter=Q(trades__status='closed', trades__trade_result__lt=0)),
        nb_trades_en_cours=Count('trades', filter=Q(trades__status='open'))
    )

    return render(request, 'monnaies.html', {'monnaies': monnaies, 'intervals': INTERVALS})









from django.http import JsonResponse
from core.models import Monnaie, Kline, Indicator

def get_dashboard_data(request):
    monnaies_data = []

    monnaies = Monnaie.objects.prefetch_related('trades').all()

    for monnaie in monnaies:
        # Comptage des Klines par intervalle
        klines_count = {
            interval: Kline.objects.filter(symbole=monnaie.symbole, intervalle=interval).count()
            for interval in INTERVALS
        }

        # Récupérer les trades liés à la monnaie
        trades = monnaie.trades.all()

        # Calcul des stats sur les trades
        nb_trades = trades.count()
        nb_trades_win = trades.filter(trade_result__gt=0).count()
        nb_trades_loss = trades.filter(trade_result__lt=0).count()

        # Si pas de trades, éviter les erreurs sur les agrégations
        if nb_trades > 0:
            min_gain = trades.aggregate(min_gain=Min('trade_result'))['min_gain']
            max_gain = trades.aggregate(max_gain=Max('trade_result'))['max_gain']
            avg_gain = trades.aggregate(avg_gain=Avg('trade_result'))['avg_gain']
            cumulative_gain = trades.aggregate(cumulative_gain=Sum('trade_result'))['cumulative_gain']
        else:
            min_gain = max_gain = avg_gain = cumulative_gain = None

        monnaies_data.append({
            "symbole": monnaie.symbole,
            "prix_actuel": monnaie.prix_actuel,
            "stoch_rsi_1m": monnaie.stoch_rsi_1m,
            "stoch_rsi_3m": monnaie.stoch_rsi_3m,
            "stoch_rsi_5m": monnaie.stoch_rsi_5m,
            "stoch_rsi_15m": monnaie.stoch_rsi_15m,
            "stoch_rsi_1h": monnaie.stoch_rsi_1h,
            "stoch_rsi_4h": monnaie.stoch_rsi_4h,
            "stoch_rsi_1d": monnaie.stoch_rsi_1d,
            "rsi_1m": monnaie.rsi_1m,
            "rsi_3m": monnaie.rsi_3m,
            "rsi_5m": monnaie.rsi_5m,
            "rsi_15m": monnaie.rsi_15m,
            "rsi_1h": monnaie.rsi_1h,
            "rsi_4h": monnaie.rsi_4h,
            "rsi_1d": monnaie.rsi_1d,
            "macd_1m": monnaie.macd_1m,
            "macd_3m": monnaie.macd_3m,
            "macd_5m": monnaie.macd_5m,
            "macd_15m": monnaie.macd_15m,
            "macd_1h": monnaie.macd_1h,
            "macd_4h": monnaie.macd_4h,
            "macd_1d": monnaie.macd_1d,
            "bollinger_m_1m": monnaie.bollinger_middle_1m,
            "bollinger_m_3m": monnaie.bollinger_middle_3m,
            "bollinger_m_5m": monnaie.bollinger_middle_5m,
            "bollinger_m_15m": monnaie.bollinger_middle_15m,
            "bollinger_m_1h": monnaie.bollinger_middle_1h,
            "bollinger_m_4h": monnaie.bollinger_middle_4h,
            "bollinger_m_1d": monnaie.bollinger_middle_1d,
            "nb_klines": klines_count,
            "nb_trades": nb_trades,
            "nb_trades_win": nb_trades_win,
            "nb_trades_loss": nb_trades_loss,
            "min_gain": min_gain,
            "max_gain": max_gain,
            "avg_gain": avg_gain,
            "cumulative_gain": cumulative_gain,
        })

    return JsonResponse(monnaies_data, safe=False)


















































































    
