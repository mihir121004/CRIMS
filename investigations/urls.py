from django.urls import path
from .views import (
    investigation_list,
    investigation_detail,
    assign_officer,
    add_note,
    my_assigned_cases
)

urlpatterns = [
    path('', investigation_list, name='investigation_list'),
    path('<int:pk>/', investigation_detail, name='investigation_detail'),
    path('assign/<int:complaint_id>/', assign_officer, name='assign_officer'),
    path('add-note/<int:pk>/', add_note, name='add_note'),
    path('my-cases/', my_assigned_cases, name='my_assigned_cases'),
]