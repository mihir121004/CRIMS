from django.shortcuts import render, get_object_or_404
from .models import ActivityLog

from django.http import HttpResponse
from complaints.models import Complaint
from .pdf_generator import generate_fir_pdf

def activity_logs(request):
    logs = ActivityLog.objects.order_by('-created_at')

    return render(request, 'reports/activity_logs.html', {
        'logs': logs
    })

def fir_pdf(request, pk):
    complaint = get_object_or_404(Complaint, id=pk)

    response = HttpResponse(content_type='application/pdf')

    response[
        'Content-Disposition'
    ] = (
        f'attachment; '
        f'filename="FIR-{complaint.tracking_id}.pdf"'
    )

    generate_fir_pdf(response, complaint)
    return response