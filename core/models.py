from django.db import models


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