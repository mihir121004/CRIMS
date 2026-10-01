"""
URL configuration for crims project.

The `urlpatterns` list routes URLs to views. For more information please see:
    https://docs.djangoproject.com/en/6.1/topics/http/urls/
Examples:
Function views
    1. Add an import:  from my_app import views
    2. Add a URL to urlpatterns:  path('', views.home, name='home')
Class-based views
    1. Add an import:  from other_app.views import Home
    2. Add a URL to urlpatterns:  path('', Home.as_view(), name='home')
Including another URLconf
    1. Import the include() function: from django.urls import include, path
    2. Add a URL to urlpatterns:  path('blog/', include('blog.urls'))
"""
from django.contrib import admin
from django.urls import path, include
from django.conf import settings
from django.conf.urls.static import static

from . import error_views

urlpatterns = [
    path('', include('accounts.urls')),
    path('complaints/', include('complaints.urls')),
    path('evidence/', include('evidence.urls')),
    path('reports/', include('reports.urls')),
    path('analytics/', include('analytics_dashboard.urls')),
    path('notifications/', include('notifications.urls')),
    path('suspects/', include('suspects.urls')),
    path('witnesses/', include('witnesses.urls')),
    path('investigations/', include('investigations.urls')),
    path('chat/', include('communications.urls')),

    # Kept last: Django's admin must only be reachable by staff accounts.
    path('admin/', admin.site.urls),
]

# Root cause of the audit finding
# -------------------------------
# The admin site was registered FIRST, before the app includes. Django's admin
# has its own staff-only checks so this was not directly exploitable, but a
# login-required page should never be shadowed by another route pattern.

handler403 = 'crims.error_views.permission_denied'
handler404 = 'crims.error_views.page_not_found'
handler500 = 'crims.error_views.server_error'

if settings.DEBUG:
    urlpatterns += static(
        settings.MEDIA_URL, document_root=settings.MEDIA_ROOT
    )
