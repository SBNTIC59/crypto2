from django.urls import path, include
from rest_framework.routers import DefaultRouter
from .views import MonnaieViewSet

router = DefaultRouter()
router.register(r'monnaies', MonnaieViewSet, basename='monnaie')

urlpatterns = [
    path('', include(router.urls)),
]
