from .models import Notification

def notification_count(request):
    if request.user.is_authenticated:
        unread = Notification.objects.filter(user=request.user, is_read=False).count()

        return {
            'unread_notifications': unread,
            'unread_notifications_count': unread
        }
    return {
        'unread_notifications': 0,
        'unread_notifications_count': 0
    }