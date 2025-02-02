from rest_framework import viewsets
from .models import Monnaie
from .serializers import MonnaieSerializer

class MonnaieViewSet(viewsets.ModelViewSet):
    queryset = Monnaie.objects.all()
    serializer_class = MonnaieSerializer

