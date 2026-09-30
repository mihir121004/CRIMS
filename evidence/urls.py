from django.urls import path
from .views import *

urlpatterns = [

    path(
        'upload/<int:complaint_id>/',
        upload_evidence,
        name='upload_evidence'
    ),
    path('<int:pk>/', evidence_detail, name='evidence_detail'),
    path('<int:pk>/transfer/', transfer_evidence, name='transfer_evidence'),
]