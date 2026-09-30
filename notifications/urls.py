from django.urls import path
from .views import ( notification_list, mark_read)

urlpatterns = [
    path('', notification_list, name='notification_list'),
    path('read/<int:pk>/', mark_read, name='mark_read'),
]