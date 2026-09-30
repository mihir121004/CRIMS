from django.shortcuts import render, redirect, get_object_or_404
from django.contrib.auth.decorators import login_required
from django.views.decorators.http import require_POST
from .models import Notification
from reports.models import ActivityLog

@login_required
def notification_list(request):

    notifications = Notification.objects.filter(user=request.user)

    activities = ActivityLog.objects.filter(
        user=request.user
    ).order_by('-created_at')[:10]

    return render(request, 'notifications/list.html',
                  {
                      'notifications': notifications,
                      'total_notifications': notifications.count(),
                      'unread_count': notifications.filter(is_read=False).count(),
                      'read_notifications': notifications.filter(is_read=True).count(),
                      'priority_alerts': notifications.filter(is_read=False)[:5],
                      'activities': activities
                  })

@login_required
@require_POST
def mark_read(request, pk):

    notification = get_object_or_404(Notification, pk=pk, user=request.user)

    notification.is_read = True
    notification.save()

    return redirect('notification_list')