import json
from django.core.serializers import serialize
from django.conf import settings
import sys
import django
from core.models import Strategy, APIKey

# Initialisation de Django
import os
sys.path.append(os.path.dirname(os.path.abspath(__file__)))
os.environ.setdefault("DJANGO_SETTINGS_MODULE", "trade_binanace.settings")
django.setup()



# Export des stratégies
strategies_json = serialize('json', Strategy.objects.all())

# Export des clés API
api_keys_json = serialize('json', APIKey.objects.all())

# Sauvegarde dans des fichiers JSON
with open('strategies_backup.json', 'w') as f:
    f.write(strategies_json)

with open('api_keys_backup.json', 'w') as f:
    f.write(str(api_keys_json))

print("Export terminé avec succès.")
