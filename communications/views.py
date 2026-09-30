from django.shortcuts import (render, redirect, get_object_or_404)
from complaints.models import Complaint
from .models import Message
from .forms import MessageForm

def complaint_chat(request, complaint_id):
    complaint = get_object_or_404(Complaint, id=complaint_id)

    messages = complaint.messages.all().order_by('created_at')

    form = MessageForm()

    if request.method == 'POST':
        form = MessageForm(request.POST)
        if form.is_valid():
            message = form.save(commit=False)
            message.sender = request.user
            message.complaint = complaint
            message.save()
            return redirect('complaint_chat', complaint_id=complaint.id)
    return render(request, 'communications/chat.html', {
        'complaint': complaint,
        'messages': messages,
        'form': form
    })
