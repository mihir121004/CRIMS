from unittest import mock

from django.core.files.uploadedfile import SimpleUploadedFile
from django.urls import reverse

from crims.test_support import RoleTestCase
from evidence.models import Evidence

UPLOAD_URL = '/complaints/{}/evidence/'


class EvidenceStorageTests(RoleTestCase):
    """Evidence writes hit the same read-only bundle as the ID upload.

    MEDIA_ROOT is inside the deployed function bundle, so on Vercel every file
    save raises OSError until MEDIA_STORAGE points at an object store. This
    used to surface as a bare 500 rather than a message the uploader can act
    on.
    """

    def upload(self, complaint=None):
        return self.client.post(
            reverse(
                'upload_evidence',
                args=[(complaint or self.citizen_complaint).id],
            ),
            {
                'file': SimpleUploadedFile(
                    'photo.png', b'\x89PNG\r\n\x1a\n fake',
                    content_type='image/png',
                ),
            },
        )

    def test_storage_failure_is_a_message_not_a_500(self):
        self.login_as(self.officer)
        with mock.patch(
            'django.core.files.storage.base.Storage.save',
            side_effect=OSError(30, 'Read-only file system'),
        ):
            response = self.upload()

        self.assertEqual(response.status_code, 200)
        self.assertContains(response, 'could not store that file')

    def test_storage_failure_leaves_no_dangling_evidence_row(self):
        """A row pointing at a file that was never written is worse than none."""
        self.login_as(self.officer)
        before = Evidence.objects.count()
        with mock.patch(
            'django.core.files.storage.base.Storage.save',
            side_effect=OSError(30, 'Read-only file system'),
        ):
            self.upload()

        self.assertEqual(Evidence.objects.count(), before)

    def test_storage_failure_writes_no_activity_log(self):
        from reports.models import ActivityLog

        self.login_as(self.officer)
        before = ActivityLog.objects.count()
        with mock.patch(
            'django.core.files.storage.base.Storage.save',
            side_effect=OSError(30, 'Read-only file system'),
        ):
            self.upload()

        self.assertEqual(ActivityLog.objects.count(), before)

    def test_upload_succeeds_when_storage_works(self):
        """Guards against the handler swallowing every upload."""
        import tempfile

        self.login_as(self.officer)
        before = Evidence.objects.count()
        with tempfile.TemporaryDirectory() as tmp:
            with self.settings(MEDIA_ROOT=tmp):
                response = self.upload()

        self.assertEqual(response.status_code, 302)
        self.assertEqual(Evidence.objects.count(), before + 1)
        self.assertEqual(
            Evidence.objects.order_by('-id').first().uploaded_by_id,
            self.officer.id,
        )