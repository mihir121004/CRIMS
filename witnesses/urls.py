from django.urls import path
from .views import(
    witness_list,
    witness_detail,
    witness_create
)

urlpatterns = [
    path('', witness_list, name='witness_list'),
    path('add/', witness_create, name='witness_create'),
    path('<int:pk>/', witness_detail, name='witness_detail'),
]