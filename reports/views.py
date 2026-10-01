from django.shortcuts import render, get_object_or_404
from django.http import HttpResponse

from accounts.permissions import staff_required, visible_complaints
from .models import ActivityLog
from .pdf_generator import generate_fir_pdf


@staff_required
def activity_logs(request):
    """Root cause of the audit finding: this view had no authentication at all.
    It exposed the full audit trail - every action and every username - to
    anonymous visitors. Verified live on production before the fix.
    """
    logs = ActivityLog.objects.select_related('user').order_by('-created_at')

    return render(request, 'reports/activity_logs.html', {'logs': logs})


@staff_required
def fir_pdf(request, pk):
    """Root cause of the audit finding: no authentication. An anonymous visitor
    could download the FIR - which embeds the complainant's name, address and
    the full crime narrative - for any complaint id.

    Scope is resolved through ``visible_complaints`` so an officer cannot pull
    a document for a case outside their remit, and the response is served as an
    attachment so the PDF is never rendered inline on the app origin.
    """
    complaint = get_object_or_404(visible_complaints(request.user), id=pk)

    response = HttpResponse(content_type='application/pdf')
    response['Content-Disposition'] = (
        'attachment; filename="FIR-{}.pdf"'.format(complaint.tracking_id)
    )
    # Defence in depth: never render untrusted content inline.
    response['X-Content-Type-Options'] = 'nosniff'

    generate_fir_pdf(response, complaint)
    return response
