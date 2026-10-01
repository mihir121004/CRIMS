"""Custom error handlers.

Django renders ``templates/500.html`` directly and ignores context processors
when ``DEBUG=False``, so ``request_id`` is unavailable there. These views keep
a consistent incident reference across 403/404/500 and make sure tracebacks
reach the logs.
"""

import logging
import uuid

from django.http import (
    HttpResponseBadRequest,
    HttpResponseForbidden,
    HttpResponseNotFound,
    HttpResponseServerError,
)
from django.shortcuts import render

logger = logging.getLogger('crims.errors')


def _render(request, template_name, status, context=None):
    ctx = {'request_id': uuid.uuid4().hex[:12].upper()}
    if context:
        ctx.update(context)
    return render(request, template_name, ctx, status=status)


def permission_denied(request, exception=None):
    """Raised by accounts.permissions.role_required for the wrong role.

    Returning a rendered 403 (rather than Django's bare default) avoids
    leaking whether the resource exists and gives the user a way out.
    """
    logger.warning(
        'Permission denied [ref=%s] %s %s by user=%s',
        uuid.uuid4().hex[:12].upper(),
        request.method,
        request.get_full_path(),
        getattr(getattr(request, 'user', None), 'username', 'anonymous'),
    )
    return _render(request, '403.html', 403)


def page_not_found(request, exception=None):
    return _render(request, '404.html', 404)


def bad_request(request, exception=None):
    return _render(request, '404.html', 400)


def server_error(request, template_name='500.html'):
    """500 handler.

    Deliberately generic: no exception text, stack trace, SQL or settings are
    exposed. Before this existed, an unhandled error rendered Django's default
    500 page which leaked diagnostics on some paths.
    """
    request_id = uuid.uuid4().hex[:12].upper()
    logger.exception(
        'Unhandled error [ref=%s] %s %s',
        request_id,
        request.method,
        request.get_full_path(),
    )
    try:
        return render(request, template_name, {'request_id': request_id},
                      status=500)
    except Exception:
        return HttpResponseServerError(
            '<!doctype html><title>Server error</title>'
            '<h1>Something went wrong</h1>'
            '<p>Reference: CRIMS-{ref}</p>'.format(ref=request_id)
        )
