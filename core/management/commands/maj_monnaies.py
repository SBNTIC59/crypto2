import requests
from django.core.management.base import BaseCommand
from core.models import Monnaie

class Command(BaseCommand):
    help = "Récupère la liste des paires USDT sur Binance et les enregistre en base"

    def handle(self, *args, **kwargs):
        url = "https://api.binance.com/api/v3/exchangeInfo"
        response = requests.get(url)

        if response.status_code == 200:
            data = response.json()
            symbols = data.get("symbols", [])

            monnaies_usdt = [
                s["symbol"] for s in symbols if s["symbol"].endswith("USDT")
            ]

            for symbole in monnaies_usdt:
                monnaie, created = Monnaie.objects.get_or_create(symbole=symbole)
                if created:
                    self.stdout.write(self.style.SUCCESS(f"Ajouté: {symbole}"))
                else:
                    self.stdout.write(self.style.WARNING(f"Déjà existant: {symbole}"))

            self.stdout.write(self.style.SUCCESS("Mise à jour des monnaies terminée !"))
        else:
            self.stderr.write(self.style.ERROR("Erreur lors de la récupération des données Binance"))
