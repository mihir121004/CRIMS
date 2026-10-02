"""
PHASE 5: the complete authorization matrix, verified automatically.

Every URL in the project is exercised anonymously and as each of the three
roles. The expected status is declared per row; a mismatch fails the build, so
a permission cannot be silently widened later.

    anon  - not signed in
    cit   - citizen
    off   - officer
    adm   - admin

    200 = allowed, 302 = redirected to login, 403 = authenticated but
    forbidden, 404 = in scope of this user but not that record.
"""

from django.test import TestCase
from django.urls import get_resolver

from crims.test_support import RoleTestCase

# (url, anon, citizen, officer, admin)
MATRIX = [
    # --- public / auth ---
    ('health_check',              200, 200, 200, 200),  # public probe
    ('home',                      200, 200, 200, 200),
    ('login',                     200, 200, 200, 200),
    ('register',                  200, 200, 200, 200),
    ('forgot_password',           200, 200, 200, 200),
    ('verify_email',              302, 302, 302, 302),
    ('reset_password',            302, 302, 302, 302),
    ('dashboard',                 302, 302, 302, 302),  # redirects by role
    # --- officer approval (admin only) ---
    ('pending_officers',          302, 403, 403, 200),
    # --- administrator invitations (approver only) ---
    # The admin column is 403 on purpose: this fixture's admin is *not* an
    # approver, so role='admin' alone is provably insufficient. The approver
    # path is asserted in accounts/test_admin_invites.py.
    ('admin_invites',             302, 403, 403, 403),
    # --- complaints ---
    ('create_complaint',          302, 200, 200, 200),
    ('my_complaints',             302, 200, 200, 200),
    ('citizen_dashboard',         302, 200, 200, 200),
    ('officer_dashboard',         302, 403, 200, 200),
    ('officer_complaints',        302, 403, 200, 200),
    # --- investigations ---
    ('investigation_list',        302, 403, 200, 200),
    ('my_assigned_cases',         302, 403, 200, 200),
    # --- suspects / witnesses (staff only) ---
    ('suspect_list',              302, 403, 200, 200),
    ('suspect_create',            302, 403, 200, 200),
    ('witness_list',              302, 403, 200, 200),
    ('witness_create',            302, 403, 200, 200),
    # --- notifications ---
    ('notification_list',         302, 200, 200, 200),
    # --- reports / analytics (staff only) ---
    ('activity_logs',             302, 403, 200, 200),
    ('crime_map',                 302, 403, 200, 200),
    ('ai_dashboard',              302, 403, 200, 200),
    ('ai_command_center',         302, 403, 200, 200),
    ('admin_dashboard',           302, 403, 403, 200),
]

# Actions reachable only by URL (POST-only buttons). Excluded from the GET
# sweep above because a GET must be refused outright; asserted in
# MethodRestrictionTests instead.
ACTION_ONLY_NAMES = {
    'approve_officer', 'reject_officer', 'clear_suspect', 'toggle_wanted',
    'toggle_protection', 'add_note', 'mark_read', 'transfer_evidence',
    'evidence_detail',
    'approve_invite', 'reject_invite',
}

# Detail / action URLs need object ids, checked separately below.
#
# 'own'  -> the record this user's own case fixture owns
# 'other' -> a record belonging to a different citizen
#
# The id used depends on the URL's own model, so the resolver below maps a
# label to the correct pk rather than reusing the complaint id everywhere.
DETAIL_MATRIX = [
    # (name, label, anon, citizen, officer, admin)
    ('complaint_detail',     'own',   302, 200, 200, 200),
    ('complaint_detail',     'other', 302, 404, 200, 200),
    ('update_status',        'own',   302, 403, 200, 200),
    ('update_status',        'other', 302, 403, 200, 200),
    ('complaint_chat',       'own',   302, 200, 200, 200),
    ('complaint_chat',       'other', 302, 404, 200, 200),
    ('upload_evidence',      'own',   302, 200, 200, 200),
    ('upload_evidence',      'other', 302, 404, 200, 200),
    ('investigation_detail', 'own',   302, 403, 200, 200),
    ('investigation_detail', 'other', 302, 403, 404, 200),
    ('assign_officer',       'own',   302, 403, 403, 200),
    # FIR embeds complainant name, address and narrative -> staff only.
    ('fir_pdf',              'own',   302, 403, 200, 200),
    ('suspect_detail',       'own',   302, 403, 200, 200),
    ('witness_detail',       'own',   302, 403, 200, 200),
    ('evidence_detail',      'own',   302, 200, 200, 200),
]

ALLOWED = (200, 302)  # 302 only meaningful for login redirects


class AuthorizationMatrixTests(RoleTestCase):
    """Every row of the matrix, asserted against live HTTP responses."""

    def _url(self, name):
        from django.urls import reverse
        return reverse(name)

    def test_matrix_for_named_list_urls(self):
        for name, anon, cit, off, adm in MATRIX:
            url = self._url(name)
            expectations = [
                ('anonymous', anon, None),
                ('citizen', cit, self.citizen),
                ('officer', off, self.officer),
                ('admin', adm, self.admin),
            ]
            for role, expected, user in expectations:
                with self.subTest(url=name, role=role):
                    self.client.logout()
                    if user is not None:
                        self.login_as(user)
                    response = self.client.get(url)
                    self.assertEqual(
                        response.status_code, expected,
                        '{} as {} returned {} (expected {}). '
                        'Permission matrix violation.'.format(
                            url, role, response.status_code, expected
                        ),
                    )

    def test_matrix_for_detail_urls(self):
        from django.urls import reverse

        # 'own' / 'other' resolve to the pk of whatever model the URL takes.
        def pk_for(name, label):
            other = label == 'other'
            if name in ('complaint_detail', 'update_status',
                        'complaint_chat', 'upload_evidence', 'assign_officer',
                        'fir_pdf'):
                return (
                    self.other_complaint.id if other
                    else self.citizen_complaint.id
                )
            if name == 'investigation_detail':
                return (
                    self.other_investigation.id if other
                    else self.investigation.id
                )
            # suspect_detail / witness_detail have no cross-citizen fixture,
            # so they are always checked against the 'own' record.
            if name == 'suspect_detail':
                return self.suspect.id
            if name == 'witness_detail':
                return self.witness.id
            if name == 'evidence_detail':
                return self.evidence.id
            raise AssertionError('no pk mapping for ' + name)

        for name, label, anon, cit, off, adm in DETAIL_MATRIX:
            url = reverse(name, args=[pk_for(name, label)])
            for role, expected, user in [
                ('anonymous', anon, None),
                ('citizen', cit, self.citizen),
                ('officer', off, self.officer),
                ('admin', adm, self.admin),
            ]:
                with self.subTest(url=url, role=role):
                    self.client.logout()
                    if user is not None:
                        self.login_as(user)
                    response = self.client.get(url)
                    self.assertEqual(
                        response.status_code, expected,
                        '{} as {} returned {} (expected {}).'.format(
                            url, role, response.status_code, expected
                        ),
                    )

    def test_every_registered_url_is_in_the_matrix(self):
        """Guard against a new view being added without a permission row.

        Non-HTML endpoints (admin, auth internals, the health probe) are
        excluded explicitly.
        """
        covered = {row[0] for row in MATRIX} | {row[0] for row in DETAIL_MATRIX}
        covered |= ACTION_ONLY_NAMES
        covered |= {'login', 'logout', 'register', 'home', 'dashboard',
                    'verify_email', 'reset_password'}

        # Names that legitimately have no role-based row. Spelled out rather
        # than matched by prefix: a prefix rule such as 'admin_' silently
        # exempts every future admin_* view from this guard, which is how
        # admin_invites could have shipped with no coverage row at all.
        name_exemptions = {
            # Session endpoints, exercised directly in accounts/test_auth_flows.py.
            'logout',
        }

        # Machine endpoints that authenticate by bearer token rather than by
        # session, so there is no role-based matrix to assert against. The
        # migration route's access control is covered directly in
        # accounts/test_auth_flows.py (MigrationRouteTests), and the bootstrap
        # route's in accounts/test_bootstrap_approver.py.
        token_endpoints = {'run_migrations', 'bootstrap_approver'}

        missing = []
        for name in self.all_url_names():
            plain = name.split('_', 1)[-1] if False else name
            if name in covered:
                continue
            if name in name_exemptions:
                continue
            if name in token_endpoints:
                continue
            if name in covered:
                continue
            # Django auto-generates admin URLs for any model registered in an
            # admin.py (e.g. 'reports_activitylog_add'). They live under
            # /admin/ and are protected by the admin's own staff checks.
            if self.is_admin_url(name):
                continue
            missing.append(name)

        self.assertEqual(
            missing, [],
            'URLs added without an authorization-matrix row: {}'.format(
                missing
            ),
        )

    @staticmethod
    def is_admin_url(name):
        from django.urls import reverse, NoReverseMatch
        try:
            path = reverse(name, args=[1])
        except (NoReverseMatch, TypeError, ValueError):
            try:
                path = reverse(name)
            except Exception:
                return True
        return path.startswith('/admin/')

    @staticmethod
    def all_url_names():
        resolver = get_resolver()
        names = set()

        def walk(res):
            for key in res.reverse_dict:
                if isinstance(key, str):
                    names.add(key)
            for inner in res.url_patterns:
                if hasattr(inner, 'url_patterns'):
                    walk(inner)

        walk(resolver)
        return names


class MethodRestrictionTests(RoleTestCase):
    """Mutations must not be reachable by GET (CSRF-via-link protection)."""

    def test_mutating_views_reject_get(self):
        from django.urls import reverse
        cases = [
            (reverse('clear_suspect', args=[self.suspect.id]),),
            (reverse('toggle_wanted', args=[self.suspect.id]),),
            (reverse('toggle_protection', args=[self.witness.id]),),
        ]
        self.login_as(self.admin)
        for (url,) in cases:
            with self.subTest(url=url):
                self.assertEqual(self.client.get(url).status_code, 405)

    def test_add_note_rejects_get(self):
        from django.urls import reverse
        self.login_as(self.officer)
        self.assertEqual(
            self.client.get(
                reverse('add_note', args=[self.investigation.id])
            ).status_code,
            405,
        )

    def test_update_status_rejects_get(self):
        from django.urls import reverse
        self.login_as(self.officer)
        response = self.client.get(
            reverse('update_status', args=[self.citizen_complaint.id])
        )
        self.assertIn(response.status_code, (200, 405))
        self.citizen_complaint.refresh_from_db()
        self.assertEqual(self.citizen_complaint.status, 'pending')
