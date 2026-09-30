from django.urls import path
from .views import (
    suspect_create,
    suspect_detail, 
    suspect_list
)

urlpatterns = [
    path('', suspect_list, name='suspect_list'),
    path('add/', suspect_create, name='suspect_create'),
    path('<int:pk>/', suspect_detail, name='suspect_detail'),
]