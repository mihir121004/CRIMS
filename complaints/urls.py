from django.urls import path
from .views import *

urlpatterns = [
    path('create/', create_complaint, name='create_complaint'),
    path('my/', my_complaints, name='my_complaints'),
    path('<int:pk>/', complaint_detail, name='complaint_detail'),
    path('officer/', officer_complaints, name='officer_complaints'),
    path('status/<int:pk>/', update_status, name='update_status'),
    path('citizen-dashboard/', citizen_dashboard, name='citizen_dashboard'),
    path('officer-dashboard/', officer_dashboard, name='officer_dashboard'),
]