from django.urls import path
from .views import (
    toggle_protection,
    witness_create,
    witness_detail,
    witness_list,
)

urlpatterns = [
    path('', witness_list, name='witness_list'),
    path('add/', witness_create, name='witness_create'),
    path('<int:pk>/', witness_detail, name='witness_detail'),
    path('<int:pk>/protection/', toggle_protection, name='toggle_protection'),
]