"""Template comments must never reach the rendered page.

Django tokenises with::

    tag_re = re.compile(r"({%.*?%}|{{.*?}}|{#.*?#})")

without ``re.DOTALL``, so ``.`` does not match a newline. A ``{# ... #}``
block written across several lines is therefore not recognised as a comment
at all and is emitted into the HTML verbatim. Four of these were shipped and
rendered "Root cause of the audit finding ..." as visible body text on the
sidebar (for every logged-in user), the officer dashboard, the complaint
detail page and the pending-officers table.

``{% comment %}`` spans lines correctly, so that is what multi-line notes must
use. These tests render the real templates so a regression is caught here
rather than by a user reporting it.
"""
import pathlib

from django.template import Context, Template
from django.test import SimpleTestCase

TEMPLATES_DIR = pathlib.Path(__file__).resolve().parent.parent / 'templates'


class NoMultiLineBraceCommentsTests(SimpleTestCase):
    """Lints the template source rather than any one rendered page."""

    def offenders(self):
        found = []
        for path in sorted(TEMPLATES_DIR.rglob('*.html')):
            for number, line in enumerate(
                path.read_text().splitlines(), start=1
            ):
                if '{#' in line and '#}' not in line:
                    found.append('{}:{}'.format(
                        path.relative_to(TEMPLATES_DIR), number))
        return found

    def test_no_brace_comment_spans_multiple_lines(self):
        offenders = self.offenders()
        self.assertEqual(
            offenders, [],
            'These {# comments span lines, so Django does not treat them as '
            'comments and renders them to users. Use a multi-line '
            'comment tag instead: ' + ', '.join(offenders),
        )


class BraceCommentRenderingTests(SimpleTestCase):
    """Demonstrates the underlying engine behaviour, so the fix has a cause."""

    def test_single_line_comment_is_stripped(self):
        self.assertEqual(
            Template('A{# note #}B').render(Context({})), 'AB'
        )

    def test_multi_line_brace_comment_leaks(self):
        """Documents why the lint above exists. Do not 'fix' this test."""
        rendered = Template('A{# one\ntwo #}B').render(Context({}))
        self.assertIn('{# one', rendered)

    def test_multi_line_comment_tag_is_stripped(self):
        self.assertEqual(
            Template('A{% comment %}\none\ntwo{% endcomment %}B').render(
                Context({})),
            'AB',
        )


class SidebarCommentTests(SimpleTestCase):
    """The specific page a user reported."""

    def sidebar_source(self):
        return (TEMPLATES_DIR / 'components' / 'sidebar.html').read_text()

    def test_source_keeps_the_note_but_inside_a_comment_tag(self):
        """The rationale stays in the file; it just must not be output."""
        source = self.sidebar_source()
        self.assertIn('Root cause of the audit finding', source)
        self.assertIn('{% comment %}', source)
        self.assertNotIn('{#', source)

    def test_rendered_sidebar_carries_no_audit_commentary(self):
        """Rendered as a citizen - the case that was reported."""
        class FakeUser:
            role = 'citizen'

        class FakeRequest:
            user = FakeUser()
            resolver_match = type('M', (), {'url_name': 'dashboard'})()

        source = self.sidebar_source()
        # Stand in for {% url %} / {% static %} so the partial can render
        # without a full request cycle.
        source = source.replace('{% url ', '{{ "/stub" }} ').replace(
            '{% url ', '{{ "/stub" }} ')
        rendered = Template(source).render(Context({'request': FakeRequest()}))

        self.assertNotIn('Root cause of the audit finding', rendered)
        self.assertNotIn('{#', rendered)
