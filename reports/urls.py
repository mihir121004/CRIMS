from django.urls import path
from .views import activity_logs, fir_pdf

urlpatterns = [
    path('activity/', activity_logs, name='activity_logs'),
    path('fir/<int:pk>/', fir_pdf, name='fir_pdf'),
]