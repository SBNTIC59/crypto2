from django.db import models
from django.utils.timezone import now
import operator

# Opérateurs supportés
OPERATORS = {
    ">": operator.gt,
    "<": operator.lt,
    ">=": operator.ge,
    "<=": operator.le,
    "==": operator.eq,
    "!=": operator.ne
}

OPERATORS_CHOICES = [
    ('>', '>'),
    ('<', '<'),
    ('>=', '>='),
    ('<=', '<='),
    ('==', '=='),
    ('!=', '!='),
]

class IndicatorTest(models.Model):
    name = models.CharField(max_length=100, unique=True)
    indicator = models.CharField(max_length=50)
    interval = models.CharField(max_length=5, choices=[('1m', '1m'), ('3m', '3m'), ('5m', '5m'), ('15m', '15m'), ('1h', '1h'), ('4h', '4h'), ('1d', '1d')])
    operator = models.CharField(max_length=2, choices=OPERATORS_CHOICES)
    threshold_value = models.FloatField(null=True, blank=True)
    threshold_indicator_test = models.ForeignKey('self', null=True, blank=True, on_delete=models.SET_NULL)
    threshold_calculation = models.ForeignKey('Calculation', null=True, blank=True, on_delete=models.SET_NULL)

    def __str__(self):
        return self.name

    def evaluate(self, symbole, trade=None):
        from core.models import Indicator

        # 🔄 Vérifier si c'est une métrique issue de TradeLog
        if self.indicator in ['prix_achat', 'prix_actuel', 'prix_max', 'gain_actuel']:
            if not trade:
                print(f"⚠️ [{symbole}] Pas de trade fourni pour {self.indicator}")
                return False

            if self.indicator == 'prix_achat':
                indicator_value = trade.prix_achat
            elif self.indicator == 'prix_actuel':
                indicator_value = trade.prix_actuel
            elif self.indicator == 'prix_max':
                indicator_value = trade.prix_max
            elif self.indicator == 'gain_actuel':
                if trade.prix_achat > 0:
                    indicator_value = trade.prix_actuel - trade.prix_achat
                else:
                    indicator_value = 0
        else:
            # Sinon, on va chercher dans les indicateurs
            latest_indicator = Indicator.objects.filter(symbole=symbole, intervalle=self.interval).order_by('-timestamp').first()

            if not latest_indicator:
                print(f"⚠️ [{symbole}] Aucun indicateur pour {self.indicator} ({self.interval})")
                return False

            indicator_value = getattr(latest_indicator, self.indicator, None)
            if indicator_value is None:
                print(f"⚠️ [{symbole}] Valeur manquante pour l'indicateur {self.indicator} ({self.interval})")
                return False

        # Seuil (identique à avant)
        if self.threshold_calculation:
            threshold = self.threshold_calculation.evaluate(trade=trade, symbole=symbole, interval=self.interval)
            threshold_type = 'calculation'
            print(f"🔢 [{symbole}] Threshold calculation utilisé pour {self.name} -> {self.threshold_calculation.name} = {threshold}")
        elif self.threshold_indicator_test:
            threshold = self.threshold_indicator_test.evaluate(symbole, trade=trade)
            threshold_type = 'indicator_test'
        else:
            threshold = self.threshold_value
            threshold_type = 'fixed'

        if threshold is None:
            print(f"❌ [{symbole}] Seuil invalide pour {self.name}")
            return False

        result = OPERATORS[self.operator](indicator_value, threshold)
        print(f"🔎 [{symbole}] Test {self.name} : {indicator_value} {self.operator} {threshold} ({threshold_type}) -> {result}")
        return result
   

class Calculation(models.Model):
    name = models.CharField(max_length=100, unique=True)
    expression = models.CharField(max_length=255)
    sub_calculations = models.ManyToManyField('self', blank=True, symmetrical=False)

    def __str__(self):
        return self.name

    def evaluate(self, trade=None, symbole=None, interval=None):
        sub_results = {}
        for calc in self.sub_calculations.all():
            sub_results[calc.name] = calc.evaluate(trade, symbole, interval)

        variables = {
            "prix_achat": float(trade.prix_achat or 0) if trade else 0,
            "prix_actuel": float(trade.prix_actuel or trade.prix_achat or 0) if trade else 0,
            "prix_max": float(trade.prix_max or trade.prix_achat or 0) if trade else 0,
        }       

        if symbole and interval:
            from core.models import Indicator
            latest_indicator = Indicator.objects.filter(symbole=symbole, intervalle=interval).order_by('-timestamp').first()
            if latest_indicator:
                for field in ['macd', 'macd_signal', 'rsi', 'stoch_rsi', 'bollinger_upper', 'bollinger_middle', 'bollinger_lower', 'rsiComb', 'stochrsiComb']:
                    variables[field] = getattr(latest_indicator, field, None)

        try:
            result = eval(self.expression, {}, variables)
            print(f"🧮 [{symbole}] Calcul {self.name} : {self.expression} -> {result} | Variables: {variables}")
            return result
        except Exception as e:
            print(f"❌ [{symbole}] Erreur dans le calcul {self.name} : {e}")
            return None

class CombinedTest(models.Model):
    name = models.CharField(max_length=100, unique=True)
    CONDITION_TYPES = [('AND', 'AND'), ('OR', 'OR')]

    condition_type = models.CharField(max_length=3, choices=CONDITION_TYPES)
    tests = models.ManyToManyField(IndicatorTest, blank=True)
    sub_combined_tests = models.ManyToManyField('self', blank=True, symmetrical=False)


    def __str__(self):
        return self.name

    def evaluate(self, symbole, trade=None):
        # Évaluer les IndicatorTests simples
        results = [test.evaluate(symbole, trade=trade) for test in self.tests.all()]

        # Évaluer les CombinedTests imbriqués
        for sub_combined in self.sub_combined_tests.all():
            results.append(sub_combined.evaluate(symbole, trade=trade))

        if self.condition_type == 'AND':
            final_result = all(results)
        elif self.condition_type == 'OR':
            final_result = any(results)
        else:
            final_result = False

        print(f"🧪 [{symbole}] CombinedTest {self.name} ({self.condition_type}) -> {final_result} | Détails: {results}")
        return final_result
    
    
    
    


class Strategy(models.Model):
    name = models.CharField(max_length=100)
    buy_test = models.ForeignKey(CombinedTest, null=True, blank=True, related_name='buy_strategies', on_delete=models.SET_NULL)
    sell_test = models.ForeignKey(CombinedTest, null=True, blank=True, related_name='sell_strategies', on_delete=models.SET_NULL)

    def __str__(self):
        return self.name

    def evaluate_buy(self, symbole):
        if self.buy_test:
            return self.buy_test.evaluate(symbole)
        return False

    def evaluate_sell(self, symbole, trade):
        if self.sell_test:
            return self.sell_test.evaluate(symbole, trade=trade)
        return False

class Monnaie(models.Model):
    symbole = models.CharField(max_length=20, unique=True)
    nom = models.CharField(max_length=50, blank=True, null=True)
    init = models.BooleanField(default=False)
    strategy = models.ForeignKey(Strategy, null=True, blank=True, on_delete=models.SET_NULL)

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
        return f"{self.symbole} - {self.intervalle} - {self.timestamp}"

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
    rsiComb = models.FloatField(null=True, blank=True)
    stochrsiComb = models.FloatField(null=True, blank=True)

    class Meta:
        unique_together = ("symbole", "intervalle", "timestamp")

    def __str__(self):
        return f"{self.symbole} - {self.intervalle} - {self.timestamp}"

class TradeLog(models.Model):
    symbole = models.CharField(max_length=20)
    prix_achat = models.DecimalField(max_digits=30, decimal_places=20, default=0.00) 
    prix_actuel = models.DecimalField(max_digits=30, decimal_places=20, null=True, blank=True)
    prix_max = models.DecimalField(max_digits=30, decimal_places=20, null=True, blank=True)

    entry_time = models.DateTimeField(auto_now_add=True)  # Date d'entrée
    exit_time = models.DateTimeField(null=True, blank=True)  # Date de sortie (fermeture du trade)
    duration = models.FloatField(null=True, blank=True)  # Durée du trade en minutes
    trade_result = models.FloatField(null=True, blank=True)  # % de gain/perte

    investment_amount = models.DecimalField(max_digits=15, decimal_places=2, default=0)  # Montant investi
    quantity = models.DecimalField(max_digits=20, decimal_places=8, default=0)  # Quantité achetée

    status = models.CharField(max_length=10, choices=[("open", "Open"), ("closed", "Closed")], default="open")
    strategy = models.ForeignKey('Strategy', null=True, blank=True, on_delete=models.SET_NULL)

    def close_trade(self, prix_actuel):
        """
        Ferme le trade et enregistre le gain/perte.
        """
        self.prix_actuel = prix_actuel or 0
        self.exit_time = now()
        self.duration = (self.exit_time - self.entry_time).total_seconds() / 60  # Convertir en minutes
        self.trade_result = ((prix_actuel - self.prix_achat) / self.prix_achat) * 100  # % de gain/perte
        self.status = "closed"
        self.save()

    def __str__(self):
        trade_result_str = f"{self.trade_result:.2f}%" if self.trade_result is not None else "N/A"
        return f"{self.symbole} | {trade_result_str} ({self.status})"
    
class APIKey(models.Model):
    name = models.CharField(max_length=50, unique=True, help_text="Nom de l'API (ex: Binance)")
    api_key = models.CharField(max_length=255, help_text="Clé API")
    secret_key = models.CharField(max_length=255, help_text="Clé Secrète")
    created_at = models.DateTimeField(auto_now_add=True)

    def __str__(self):
        return f"{self.name} (Ajouté le {self.created_at.strftime('%Y-%m-%d')})"