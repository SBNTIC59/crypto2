from django.db import models
from django.utils.timezone import now
import operator
from django.db.models.signals import pre_save
from django.dispatch import receiver
from django.db.models import Count, Sum, Q


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
        """
        Évalue la condition de cet indicateur sur la monnaie ou le trade associé.
        """
        monnaie = Monnaie.objects.get(symbole=symbole)
        # Obtenir la valeur de l'indicateur ou d'un champ spécifique du trade
        if self.indicator in ["prix_achat", "prix_actuel", "prix_max"]:
            if not trade:
                raise ValueError(f"Le trade est requis pour évaluer l'indicateur '{self.indicator}'")
            indicator_value = getattr(trade, self.indicator)

        else:
            indicator_field = f"{self.indicator}_{self.interval}"
            if not hasattr(monnaie, indicator_field):
                raise AttributeError(f"La monnaie n'a pas d'attribut {indicator_field}")

            indicator_value = getattr(monnaie, indicator_field)

        # Si la valeur est None, la condition est considérée comme non valide
        if indicator_value is None:
            return False

        # Obtenir la valeur du seuil
        if self.threshold_value is not None:
            threshold = self.threshold_value

        elif self.threshold_indicator_test:
            if self.threshold_indicator_test.indicator in ["prix_achat", "prix_actuel", "prix_max"]:
                if not trade:
                    raise ValueError(f"Le trade est requis pour évaluer le seuil '{self.threshold_indicator_test.indicator}'")
                threshold = getattr(trade, self.threshold_indicator_test.indicator)
            else:
                threshold_field = f"{self.threshold_indicator_test.indicator}_{self.threshold_indicator_test.interval}"
                if not hasattr(monnaie, threshold_field):
                    raise AttributeError(f"La monnaie n'a pas d'attribut {threshold_field}")

                threshold = getattr(monnaie, threshold_field)

        elif self.threshold_calculation:
            threshold = self.threshold_calculation.evaluate(monnaie, trade)
        else:
            raise ValueError("Aucun seuil défini pour l'indicateur.")

        # Si la valeur seuil est None, la condition est considérée comme non valide
        if threshold is None:
            return False

        # Comparaison en fonction de l'opérateur
        if self.operator == ">":
            return indicator_value > threshold
        elif self.operator == "<":
            return indicator_value < threshold
        elif self.operator == ">=":
            return indicator_value >= threshold
        elif self.operator == "<=":
            return indicator_value <= threshold
        else:
            raise ValueError(f"Opérateur non supporté : {self.operator}")
    
    def update_related_strategies(self):
        """
        Met à jour toutes les stratégies liées aux tests et calculs.
        """
        for strategy in Strategy.objects.all():
            strategy.update_strategy_requirements()    

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        self.update_related_strategies()

    def delete(self, *args, **kwargs):
        super().delete(*args, **kwargs)
        self.update_related_strategies()

class Calculation(models.Model):
    name = models.CharField(max_length=100, unique=True)
    expression = models.CharField(max_length=255)
    sub_calculations = models.ManyToManyField('self', blank=True, symmetrical=False)

    def __str__(self):
        return self.name

    def evaluate(self, symbole=None, trade=None, interval=None):
        """
        Évalue l'expression de la calculatrice en utilisant les valeurs de la monnaie et des trades.
        """
        sub_results = {}
        for calc in self.sub_calculations.all():
            sub_results[calc.name] = calc.evaluate(trade, symbole, interval)

        variables = {
            "prix_achat": float(trade.prix_achat or 0) if trade else 0,
            "prix_actuel": float(trade.prix_actuel or trade.prix_achat or 0) if trade else 0,
            "prix_max": float(trade.prix_max or trade.prix_achat or 0) if trade else 0,
        }

        if symbole and interval:
            from core.models import Monnaie
            try:
                monnaie = Monnaie.objects.get(symbole=symbole)
                for field in ['macd', 'macd_signal', 'rsi', 'stoch_rsi', 'bollinger_upper', 'bollinger_middle', 'bollinger_lower', 'rsiComb', 'stochrsiComb']:
                    monnaie_field = f"{field}_{interval}"
                    variables[field] = getattr(monnaie, monnaie_field, None)
            except Monnaie.DoesNotExist:
                print(f"⚠️ [Calculation] Monnaie {symbole} introuvable pour interval {interval}.")
                return None

        try:
            result = eval(self.expression, {}, {**variables, **sub_results})
            #print(f"🧮 [{symbole}] Calcul {self.name} : {self.expression} -> {result} | Variables: {variables}")
            return result
        except Exception as e:
            print(f"❌ [{symbole}] Erreur dans le calcul {self.name} : {e}")
            return None

    def update_related_strategies(self):
        """
        Met à jour toutes les stratégies liées aux tests et calculs.
        """
        for strategy in Strategy.objects.all():
            strategy.update_strategy_requirements() 

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        self.update_related_strategies()

    def delete(self, *args, **kwargs):
        super().delete(*args, **kwargs)
        self.update_related_strategies()    

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

        #print(f"🧪 [{symbole}] CombinedTest {self.name} ({self.condition_type}) -> {final_result} | Détails: {results}")
        return final_result
    
    def update_related_strategies(self):
        """
        Met à jour toutes les stratégies liées aux tests et calculs.
        """
        for strategy in Strategy.objects.all():
            strategy.update_strategy_requirements()

    def save(self, *args, **kwargs):
        super().save(*args, **kwargs)
        self.update_related_strategies()

    def delete(self, *args, **kwargs):
        super().delete(*args, **kwargs)
        self.update_related_strategies()    
class Strategy(models.Model):
    name = models.CharField(max_length=100)
    buy_test = models.ForeignKey(CombinedTest, null=True, blank=True, related_name='buy_strategies', on_delete=models.SET_NULL)
    sell_test = models.ForeignKey(CombinedTest, null=True, blank=True, related_name='sell_strategies', on_delete=models.SET_NULL)
    # Liste des indicateurs à calculer
    use_rsi = models.BooleanField(default=False)
    use_stoch_rsi = models.BooleanField(default=False)
    use_macd = models.BooleanField(default=False)
    use_bollinger = models.BooleanField(default=False)

    # Intervalles de calcul nécessaires
    intervals = models.JSONField(default=list)  # Ex: ["1m", "3m", "5m"]

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
    
    def update_strategy_requirements(self):
        """
        Met à jour les indicateurs et intervalles nécessaires pour cette stratégie
        en fonction des tests d'achat et de vente.
        """
        used_intervals = set()
        used_indicators = set()

        def extract_requirements(combined_test):
            if not combined_test:
                return

            for test in combined_test.tests.all():
                used_intervals.add(test.interval)
                used_indicators.add(test.indicator)

            for sub_combined in combined_test.sub_combined_tests.all():
                extract_requirements(sub_combined)

        extract_requirements(self.buy_test)
        extract_requirements(self.sell_test)

        # Mise à jour des intervalles et indicateurs
        self.intervals = list(used_intervals)
        self.use_rsi = "rsi" in used_indicators
        self.use_stoch_rsi = "stoch_rsi" in used_indicators
        self.use_macd = "macd" in used_indicators
        self.use_bollinger = "bollinger_middle" in used_indicators

        self.save()

@receiver(pre_save, sender=Strategy)
def update_monnaies_on_interval_change(sender, instance, **kwargs):
    """
    Vérifie si de nouveaux intervalles sont ajoutés à une stratégie et met à jour les monnaies actives associées.
    """
    if not instance.pk:  # Si la stratégie est nouvelle, pas besoin de mise à jour
        return

    # Récupération de l'ancienne version de la stratégie en base
    ancienne_instance = Strategy.objects.get(pk=instance.pk)

    # Détection des nouveaux intervalles ajoutés
    nouveaux_intervals = set(instance.intervals) - set(ancienne_instance.intervals)
    
    if nouveaux_intervals:
        from .utils import load_historical_klines, set_loaded_symbol
        print(f"⚠️ [DEBUG] Nouveaux intervalles ajoutés à {instance.name}: {nouveaux_intervals}")

        # Récupération des monnaies actives utilisant cette stratégie
        monnaies_a_reinitialiser = Monnaie.objects.filter(strategy=instance, init=True)

        for monnaie in monnaies_a_reinitialiser:
            print(f"🔄 [REGULATION] Mise à jour requise pour {monnaie.symbole} (nouveaux intervalles détectés).")
            
            # 1. Désactiver temporairement la monnaie
            monnaie.init = False
            monnaie.save()

            # 2. Supprimer des monnaies chargées en mémoire
            set_loaded_symbol(monnaie.symbole, False)

        # 3. Lancer la réinitialisation
        for monnaie in monnaies_a_reinitialiser:
            print(f"🔄 [INIT] Rechargement des Klines pour {monnaie.symbole}")
            load_historical_klines([monnaie.symbole])  # Recharge l'historique pour cette monnaie
class Monnaie(models.Model):
    symbole = models.CharField(max_length=20, unique=True, primary_key=True)
    nom = models.CharField(max_length=50, blank=True, null=True)
    init = models.BooleanField(default=False)
    strategy = models.ForeignKey(Strategy, null=True, blank=True, on_delete=models.SET_NULL)
    prix_actuel = models.FloatField(null=True, blank=True)
    prix_max = models.FloatField(null=True, blank=True)
    prix_min = models.FloatField(null=True, blank=True)
     # 📌 Ajout des champs de suivi des performances
    nb_trades_gagnants = models.IntegerField(default=0)
    nb_trades_perdus = models.IntegerField(default=0)
    total_profit = models.FloatField(default=0.0)
    win_rate = models.FloatField(default=0.0)  
     # 📌 Ajout des champs de suivi des indicateurs
    stoch_rsi_1m = models.FloatField(null=True, blank=True)
    rsi_1m = models.FloatField(null=True, blank=True)
    macd_1m = models.FloatField(null=True, blank=True)
    macd_signal_1m = models.FloatField(null=True, blank=True)
    stoch_rsi_3m = models.FloatField(null=True, blank=True)
    rsi_3m = models.FloatField(null=True, blank=True)
    macd_3m = models.FloatField(null=True, blank=True)
    macd_signal_3m = models.FloatField(null=True, blank=True)
    stoch_rsi_5m = models.FloatField(null=True, blank=True)
    rsi_5m = models.FloatField(null=True, blank=True)
    macd_5m = models.FloatField(null=True, blank=True)
    macd_signal_5m = models.FloatField(null=True, blank=True)
    stoch_rsi_15m = models.FloatField(null=True, blank=True)
    rsi_15m = models.FloatField(null=True, blank=True)
    macd_15m = models.FloatField(null=True, blank=True)
    macd_signal_15m = models.FloatField(null=True, blank=True)
    stoch_rsi_1h = models.FloatField(null=True, blank=True)
    rsi_1h = models.FloatField(null=True, blank=True)
    macd_1h = models.FloatField(null=True, blank=True)
    macd_signal_1h = models.FloatField(null=True, blank=True)
    stoch_rsi_4h = models.FloatField(null=True, blank=True)
    rsi_4h = models.FloatField(null=True, blank=True)
    macd_4h = models.FloatField(null=True, blank=True)
    macd_signal_4h = models.FloatField(null=True, blank=True)
    stoch_rsi_1d = models.FloatField(null=True, blank=True)
    rsi_1d = models.FloatField(null=True, blank=True)
    macd_1d = models.FloatField(null=True, blank=True)
    macd_signal_1d = models.FloatField(null=True, blank=True)
    # Bollinger Bands
    bollinger_middle_1m = models.FloatField(null=True, blank=True)
    bollinger_upper_1m = models.FloatField(null=True, blank=True)
    bollinger_lower_1m = models.FloatField(null=True, blank=True)

    bollinger_middle_3m = models.FloatField(null=True, blank=True)
    bollinger_upper_3m = models.FloatField(null=True, blank=True)
    bollinger_lower_3m = models.FloatField(null=True, blank=True)

    bollinger_middle_5m = models.FloatField(null=True, blank=True)
    bollinger_upper_5m = models.FloatField(null=True, blank=True)
    bollinger_lower_5m = models.FloatField(null=True, blank=True)

    bollinger_middle_15m = models.FloatField(null=True, blank=True)
    bollinger_upper_15m = models.FloatField(null=True, blank=True)
    bollinger_lower_15m = models.FloatField(null=True, blank=True)

    bollinger_middle_1h = models.FloatField(null=True, blank=True)
    bollinger_upper_1h = models.FloatField(null=True, blank=True)
    bollinger_lower_1h = models.FloatField(null=True, blank=True)

    bollinger_middle_4h = models.FloatField(null=True, blank=True)
    bollinger_upper_4h = models.FloatField(null=True, blank=True)
    bollinger_lower_4h = models.FloatField(null=True, blank=True)

    bollinger_middle_1d = models.FloatField(null=True, blank=True)
    bollinger_upper_1d = models.FloatField(null=True, blank=True)
    bollinger_lower_1d = models.FloatField(null=True, blank=True)

    def update_performance(self):
        """
        Met à jour les performances de la monnaie en fonction des trades.
        """
        stats = self.trades.aggregate(
            nb_gagnants=Count("id", filter=Q(status="closed", trade_result__gt=0)),
            nb_perdus=Count("id", filter=Q(status="closed", trade_result__lt=0)),
            profit_total=Sum("trade_result", filter=Q(status="closed")),
        )

        self.nb_trades_gagnants = stats["nb_gagnants"] or 0
        self.nb_trades_perdus = stats["nb_perdus"] or 0
        self.total_profit = stats["profit_total"] or 0.0
        self.win_rate = (
            self.nb_trades_gagnants / (self.nb_trades_gagnants + self.nb_trades_perdus)
            if (self.nb_trades_gagnants + self.nb_trades_perdus) > 0
            else 0.0
        )
        self.save()

    def __str__(self):
        return f"{self.symbole} (WinRate: {self.win_rate:.2f}, Profit: {self.total_profit})"
    

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
    symbole = models.ForeignKey(Monnaie, on_delete=models.CASCADE, to_field='symbole', related_name='trades')
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
    
class RegulatorSettings(models.Model):
    """Stocke les paramètres de régulation des monnaies et des performances."""
    
    # Seuils de régulation
    seuil_min_traitement = models.FloatField(default=0.5, help_text="Seuil minimum de traitement en secondes")
    duree_surveillance_min = models.IntegerField(default=30, help_text="Durée de surveillance pour le seuil min")

    seuil_max_traitement = models.FloatField(default=3.0, help_text="Seuil maximum de traitement en secondes")
    duree_surveillance_max = models.IntegerField(default=60, help_text="Durée de surveillance pour le seuil max")

    seuil_critique = models.FloatField(default=5.0, help_text="Seuil critique de surcharge")
    duree_surveillance_critique = models.IntegerField(default=30, help_text="Durée de surveillance pour le seuil critique")

    # Nombre de monnaies actives
    nb_monnaies_max = models.IntegerField(default=50, help_text="Nombre maximum de monnaies actives")
    nb_monnaies_min = models.IntegerField(default=5, help_text="Nombre minimum de monnaies actives")
    reduction_nb_monnaies = models.IntegerField(default=3, help_text="Nombre de monnaies retirées en cas de surcharge")

    # Gestion des WebSockets et traitements
    max_queue = models.IntegerField(default=10, help_text="Nombre max de threads pour les traitements")
    max_stream_per_ws = models.IntegerField(default=5, help_text="Nombre max de flux WebSocket par connexion")
    duree_limite_ordre = models.FloatField(default=2, help_text="Temps max en secondes pour un ordre")

    # Gestion du Flush des Klines
    nb_messages_flush = models.IntegerField(default=25, help_text="Nombre de messages pour lancer un flush")
    duree_max_flush = models.FloatField(default=5, help_text="Temps max avant flush")

    # Récupération de l'historique
    nb_klines_historique = models.IntegerField(default=100, help_text="Nombre de Klines à charger par intervalle")

    def __str__(self):
        return "Paramètres de régulation du trading"

    class Meta:
        verbose_name = "Paramètre de régulation"
        verbose_name_plural = "Paramètres de régulation"