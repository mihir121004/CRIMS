from django.urls import path
from .views import *


urlpatterns = [
    path('', admin_dashboard, name='admin_dashboard'),
    path('crime-map/',crime_map, name='crime_map'),
    path('ai-dashboard/', ai_dashboard, name='ai_dashboard'),
    path('ai-command-center/', ai_command_center, name='ai_command_center'),
]