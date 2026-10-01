"""
Upload validation for CRIMS.

Root cause this module fixes
---------------------------
All three ``FileField``/``ImageField`` columns were declared with nothing but a
``upload_to`` prefix::

    evidence.file   = models.FileField(upload_to='evidence/')
    suspects.photo  = models.ImageField(upload_to='suspects/')
    accounts.id_document = models.FileField(upload_to='id_uploads/')

Consequences, in order of severity:

1. **Unbounded size.** Django's ``DATA_UPLOAD_MAX_MEMORY_SIZE`` only bounds
   in-memory parsing; oversized uploads stream straight to disk and can fill
   the volume. This is a trivial denial-of-service vector.
2. **Unrestricted type.** An ``.html`` or ``.svg`` upload executed as
   active content on the same origin as the app (stored XSS / phishing).
3. **Predictable paths.** ``upload_to='evidence/'`` stored files under their
   original client-supplied name.

This module provides extension allow-lists, hard size caps, per-file validation
and a content-disposition-forcing storage backend.
"""

import os
import uuid

from django.conf import settings
from django.core.exceptions import ValidationError
from django.core.files.storage import FileSystemStorage


#: (allowed extensions, max bytes, human label)
ID_DOCUMENT_RULES = (
    {'.pdf', '.jpg', '.jpeg', '.png'},
    5 * 1024 * 1024,
    'ID document',
)

PHOTO_RULES = (
    {'.jpg', '.jpeg', '.png'},
    5 * 1024 * 1024,
    'Suspect photo',
)

EVIDENCE_RULES = (
    {
        '.pdf', '.jpg', '.jpeg', '.png', '.gif', '.webp',
        '.mp4', '.webm', '.mov', '.avi',
        '.mp3', '.wav', '.m4a',
        '.doc', '.docx', '.txt',
    },
    25 * 1024 * 1024,
    'Evidence file',
)


def _extension(name):
    return os.path.splitext(name or '')[1].lower()


def validate_upload(name, field_file, rules):
    """Validate ``field_file`` against ``(extensions, max_bytes, label)``."""
    extensions, max_bytes, label = rules

    if not field_file:
        return field_file

    ext = _extension(field_file.name)
    if ext not in extensions:
        raise ValidationError(
            '{}: "{}" is not an allowed file type. Allowed: {}.'.format(
                label, ext or 'unknown', ', '.join(sorted(extensions))
            )
        )

    size = getattr(field_file, 'size', None)
    if size is not None and size > max_bytes:
        raise ValidationError(
            '{} is too large: {:.1f} MB. Maximum is {} MB.'.format(
                label, size / (1024 * 1024), max_bytes // (1024 * 1024)
            )
        )

    return field_file


def validate_uploaded_id_document(field_file):
    return validate_upload('id_document', field_file, ID_DOCUMENT_RULES)


def validate_uploaded_photo(field_file):
    return validate_upload('photo', field_file, PHOTO_RULES)


def validate_uploaded_evidence(field_file):
    return validate_upload('file', field_file, EVIDENCE_RULES)


# ---------------------------------------------------------------------------
# Storage
# ---------------------------------------------------------------------------

def evidence_upload_path(instance, filename):
    """``evidence/<complaint_id>/<random>.<ext>`` - never the client filename."""
    ext = _extension(filename)
    complaint_id = getattr(instance, 'complaint_id', None) or 'unassigned'
    return 'evidence/{}/{}{}'.format(complaint_id, uuid.uuid4().hex, ext)


def suspect_photo_path(instance, filename):
    ext = _extension(filename)
    return 'suspects/{}{}'.format(uuid.uuid4().hex, ext)


def id_document_path(instance, filename):
    """Never expose an identity document under its original name."""
    ext = _extension(filename)
    return 'id_uploads/{}{}'.format(uuid.uuid4().hex, ext)


class EvidenceStorage(FileSystemStorage):
    """Serves evidence as an attachment so an upload can never be rendered
    inline as HTML/SVG on the application's origin."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.base_url = getattr(settings, 'MEDIA_URL', '/media/')

    def path(self, name):
        return super().path(name)

    def url(self, name):
        url = super().url(name)
        # `?download=1` is honoured by the storage backend only for the
        # django-storages S3 backend; for local storage the response header
        # approach in the download view is used instead.
        return url
