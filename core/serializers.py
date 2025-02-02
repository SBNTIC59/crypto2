from rest_framework import serializers
from .models import Monnaie

class MonnaieSerializer(serializers.ModelSerializer):
    class Meta:
        model = Monnaie
        fields = '__all__'