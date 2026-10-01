from django.http import Http404
from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST

from accounts.permissions import can_access_message_thread, visible_complaints
from complaints.models import Complaint
from .models import Message
from .forms import MessageForm


@login_required
def complaint_chat(request, complaint_id):
    """Root cause of the audit findings
    ---------------------------------
    1. **No authentication at all.** There was no ``@login_required``, so an
       anonymous visitor could read a case's message thread and - because
       ``message.sender = request.user`` was assigned unconditionally - an
       anonymous POST raised an IntegrityError (``AnonymousUser`` into a
       non-null FK) and returned HTTP 500.
    2. **IDOR.** The complaint was fetched unfiltered, so any user could open
       any case's thread by iterating ids.
    3. **Context shadowing.** The view passed ``{'messages': messages}``, which
       shadowed ``django.contrib.messages``; a ``messages.success()`` flash on
       this page would be swallowed and iterate chat messages instead. Django's
       framework messages are no longer shadowed.
    """

    complaint = get_object_or_404(visible_complaints(request.user),
                                  id=complaint_id)

    if not can_access_message_thread(request.user, complaint):
        raise Http404()

    if request.method == 'POST':
        form = MessageForm(request.POST)
        if form.is_valid():
            message = form.save(commit=False)
            message.sender = request.user
            message.complaint = complaint
            message.save()
            return redirect('complaint_chat', complaint_id=complaint.id)
    else:
        form = MessageForm()

    return render(
        request,
        'communications/chat.html',
        {
            'complaint': complaint,
            # Renamed from 'messages' so it no longer shadows the messages
            # context processor.
            'chat_messages': complaint.messages.select_related(
                'sender'
            ).order_by('created_at'),
            'form': form,
        },
    )
