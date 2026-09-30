from django.urls import path
from .views import( complaint_chat)

urlpatterns = [
    path('<int:complaint_id>/', complaint_chat, name='complaint_chat'),
]