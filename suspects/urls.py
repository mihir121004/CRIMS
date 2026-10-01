from django.urls import path
from .views import (
    clear_suspect,
    suspect_create,
    suspect_detail,
    suspect_list,
    toggle_wanted,
)

urlpatterns = [
    path('', suspect_list, name='suspect_list'),
    path('add/', suspect_create, name='suspect_create'),
    path('<int:pk>/', suspect_detail, name='suspect_detail'),
    path('<int:pk>/clear/', clear_suspect, name='clear_suspect'),
    path('<int:pk>/wanted/', toggle_wanted, name='toggle_wanted'),
]