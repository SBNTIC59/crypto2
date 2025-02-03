from django.db import models
from django.utils.timezone import now


class Monnaie(models.Model):
    symbole = models.CharField(max_length=20, unique=True)
    nom = models.CharField(max_length=50, blank=True, null=True)

    def __str__(self):
        return self.symbole
    
class Kline(models.Model):
    symbole = models.CharField(max_length=20)
    intervalle = models.CharField(max_length=5)
    timestamp = models.BigIntegerField()
    open_price = models.FloatField()
    high_price = models.FloatField()
    low_price = models.FloatField()
    close_price = models.FloatField()
    volume = models.FloatField()

    class Meta:
        unique_together = ("symbole", "intervalle", "timestamp")

    def __str__(self):
        return f"{self.symbole} {self.intervalle} {self.timestamp}"
    
class Indicator(models.Model):
    symbole = models.CharField(max_length=20)
    intervalle = models.CharField(max_length=5)
    timestamp = models.BigIntegerField()
    
    macd = models.FloatField(null=True, blank=True)
    macd_signal = models.FloatField(null=True, blank=True)
    rsi = models.FloatField(null=True, blank=True)
    stoch_rsi = models.FloatField(null=True, blank=True) 
    bollinger_upper = models.FloatField(null=True, blank=True)
    bollinger_middle = models.FloatField(null=True, blank=True)
    bollinger_lower = models.FloatField(null=True, blank=True)

    class Meta:
        unique_together = ("symbole", "intervalle", "timestamp")

    def __str__(self):
        return f"{self.symbole} - {self.intervalle} - {self.timestamp}"
    
class Strategy(models.Model):
    """
    Définit une stratégie d'achat ou de vente.
    """
    name = models.CharField(max_length=50, unique=True)
    buy_conditions = models.JSONField(default=dict)  # Conditions d'achat (ex: {"stoch_rsi_1m": "<5", "rsi_1m": "<20"})
    sell_conditions = models.JSONField(default=dict)  # Conditions de vente (ex: {"price": "<= entry_price * 0.999"})

    def __str__(self):
        return self.name

class SymbolStrategy(models.Model):
    """
    Associe une stratégie à une monnaie spécifique.
    """
    symbole = models.CharField(max_length=20)
    strategy = models.ForeignKey(Strategy, on_delete=models.CASCADE)
    entry_price = models.FloatField(null=True, blank=True)  # Prix d'achat
    max_price = models.FloatField(default=0.0)  # Prix max après achat
    investment_amount = models.FloatField(default=100.0)  # Montant investi par trade
    close_price = models.FloatField(null=True, blank=True)
    active = models.BooleanField(default=True)  # Si la stratégie est en cours

    def __str__(self):
        return f"{self.symbole} - {self.strategy.name}"
    
class TradeLog(models.Model):
    symbole = models.CharField(max_length=20)
    prix_achat = models.DecimalField(max_digits=10, decimal_places=2, default=0.00) 
    prix_actuel = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)
    prix_max = models.DecimalField(max_digits=10, decimal_places=2, null=True, blank=True)

    entry_time = models.DateTimeField(auto_now_add=True)  # Date d'entrée
    exit_time = models.DateTimeField(null=True, blank=True)  # Date de sortie (fermeture du trade)
    duration = models.FloatField(null=True, blank=True)  # Durée du trade en minutes
    trade_result = models.FloatField(null=True, blank=True)  # % de gain/perte

    investment_amount = models.DecimalField(max_digits=15, decimal_places=2, default=0)  # Montant investi
    quantity = models.DecimalField(max_digits=20, decimal_places=8, default=0)  # Quantité achetée

    status = models.CharField(max_length=10, choices=[("open", "Open"), ("closed", "Closed")], default="open")
    strategy_json = models.JSONField(default=dict)  # Stocke la stratégie utilisée

    def close_trade(self, prix_actuel):
        """
        Ferme le trade et enregistre le gain/perte.
        """
        self.prix_actuel = prix_actuel
        self.exit_time = now()
        self.duration = (self.exit_time - self.entry_time).total_seconds() / 60  # Convertir en minutes
        self.trade_result = ((prix_actuel - self.prix_achat) / self.prix_achat) * 100  # % de gain/perte
        self.status = "closed"
        self.save()

    def __str__(self):
        trade_result_str = f"{self.trade_result:.2f}%" if self.trade_result is not None else "N/A"
        return f"{self.symbole} | {trade_result_str} ({self.status})"