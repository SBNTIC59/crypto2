from django.urls import path, include
from rest_framework.routers import DefaultRouter
from core.views import MonnaieViewSet, dashboard, get_monnaies, get_dashboard_data, monnaie_detail
from . import views

router = DefaultRouter()
router.register(r'monnaies', MonnaieViewSet, basename='monnaie')

urlpatterns = [
    path('', include(router.urls)),
    path("dashboard/", dashboard, name="dashboard"),
    path("dashboard/monnaies/", get_monnaies, name="monnaies"),
    path("api/dashboard/", get_dashboard_data, name="api_dashboard"),
    path('stats/', views.stats_view, name='stats_view'),
    path('stats_partial/', views.stats_partial, name='stats_partial'),
    path('monnaie/<str:symbole>/', monnaie_detail, name='monnaie_detail'),

]
