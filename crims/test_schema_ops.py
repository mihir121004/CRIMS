"""Tests for the TiDB-tolerant schema operations.

The failure these guard against cannot be reproduced on the local MySQL
server, which accepts the inline-FK statement TiDB rejects with error 1072.
So these assert on the SQL that gets generated rather than on an error being
raised.

A throwaway model is used instead of a real CRIMS model so the assertions
depend only on the operation under test.
"""
from contextlib import contextmanager
from unittest import mock

from django.apps import apps
from django.db import connection, models
from django.db.migrations.state import ModelState, ProjectState
from django.test import TransactionTestCase

from crims import schema_ops
from crims.schema_ops import SplitForeignKeyAddField

APP = 'testing'
MODEL = 'Widget'


def state_containing(field, name):
    """A one-model project state carrying ``field`` as ``name``.

    Built on top of the real installed apps so a lazy 'auth.user' reference
    inside the field can be resolved.
    """
    state = ProjectState.from_apps(apps)
    state.add_model(ModelState(
        APP, MODEL,
        [
            ('id', models.AutoField(primary_key=True)),
            (name, field),
        ],
    ))
    return state


@contextmanager
def no_wait():
    """Skip the schema-visibility wait.

    collect_sql means no DDL actually runs, so the column genuinely never
    appears and the real wait would sit there for its full timeout. The wait
    is exercised separately by TestColumnVisibilityWait.
    """
    with mock.patch.object(
        SplitForeignKeyAddField, '_wait_for_column', lambda *a, **k: None
    ):
        yield


class FakeCursor:
    def __init__(self, results, calls):
        self.results = list(results)
        self.calls = calls

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False

    def execute(self, query, params=None):
        self.calls.append((query, params))

    def fetchone(self):
        # Keep returning the final scripted value once exhausted, so a poll
        # loop can run for as long as it likes.
        return (self.results.pop(0) if len(self.results) > 1 else self.results[0],)


class FakeConnection:
    def __init__(self, results, calls):
        self._cursor = FakeCursor(results, calls)

    def cursor(self):
        return self._cursor


class FakeEditor:
    def __init__(self, results):
        self.calls = []
        self.connection = FakeConnection(results, self.calls)


class SplitForeignKeyAddFieldTests(TransactionTestCase):
    """The FK column and its constraint must not share one statement."""

    def collect(self, operation, field, name):
        state = state_containing(field, name)
        with no_wait():
            with connection.schema_editor(collect_sql=True, atomic=False) as ed:
                operation.database_forwards(APP, ed, state, state)
                # deferred_sql holds Statement objects, not plain strings.
                return (
                    list(ed.collected_sql),
                    [str(s) for s in ed.deferred_sql],
                )

    def foreign_key(self):
        return models.ForeignKey(
            'auth.User', models.SET_NULL, null=True, blank=True,
            related_name='+',
        )

    def test_foreign_key_column_and_constraint_are_separate(self):
        field = self.foreign_key()
        operation = SplitForeignKeyAddField(
            model_name=MODEL, name='owner', field=field,
        )
        collected, deferred = self.collect(operation, field, 'owner')

        adds_column = [s for s in collected if 'ADD COLUMN' in s.upper()]
        self.assertTrue(adds_column, 'expected an ADD COLUMN statement')

        for statement in adds_column:
            self.assertNotIn(
                'FOREIGN KEY', statement.upper(),
                'the FK constraint must not be inlined into ADD COLUMN',
            )

        self.assertTrue(
            any('FOREIGN KEY' in s.upper() for s in deferred),
            'expected the FK constraint deferred to a separate statement',
        )

    def test_plain_field_is_unaffected(self):
        field = models.TextField(blank=True, default='')
        operation = SplitForeignKeyAddField(
            model_name=MODEL, name='notes', field=field,
        )
        collected, deferred = self.collect(operation, field, 'notes')

        self.assertTrue(any('notes' in s for s in collected))
        self.assertFalse(
            any('FOREIGN KEY' in s.upper() for s in deferred),
            'a non-FK field must not produce a deferred constraint',
        )

    def test_backend_with_inline_fk_is_detected(self):
        """Guards that the split path is the one actually taken.

        If a future Django dropped sql_create_column_inline_fk the split would
        silently become a no-op and TiDB would break again.
        """
        field = self.foreign_key()
        state = state_containing(field, 'owner')
        # Resolve through the state's registry so the lazy 'auth.User'
        # reference is bound.
        resolved = state.apps.get_model(APP, MODEL)._meta.get_field('owner')
        operation = SplitForeignKeyAddField(
            model_name=MODEL, name='owner', field=field,
        )
        with connection.schema_editor(collect_sql=True, atomic=False) as ed:
            self.assertTrue(
                operation._inlines_foreign_key(ed, resolved),
                'this test no longer exercises the split path on this backend',
            )


class TestColumnVisibilityWait(TransactionTestCase):
    """The wait exists because TiDB publishes schema changes asynchronously."""

    def wait(self, results, timeout, interval=0):
        # Built here rather than at class scope: the lazy 'auth.User'
        # reference needs a ready app registry.
        operation = SplitForeignKeyAddField(
            model_name=MODEL, name='owner',
            field=models.ForeignKey(
                'auth.User', models.SET_NULL, null=True, blank=True,
                related_name='+',
            ),
        )
        editor = FakeEditor(results)
        with mock.patch.object(schema_ops, 'COLUMN_VISIBILITY_TIMEOUT', timeout), \
                mock.patch.object(schema_ops, 'COLUMN_VISIBILITY_INTERVAL', interval):
            operation._wait_for_column(editor, 'testing_widget', 'owner_id')
        return editor

    def test_returns_as_soon_as_column_is_visible(self):
        editor = self.wait([0, 0, 1], timeout=5)
        self.assertEqual(len(editor.calls), 3)

    def test_stops_immediately_when_already_visible(self):
        editor = self.wait([1], timeout=5)
        self.assertEqual(len(editor.calls), 1)

    def test_queries_information_schema_for_this_database(self):
        editor = self.wait([1], timeout=5)
        query, params = editor.calls[0]
        self.assertIn('information_schema', query)
        self.assertIn('DATABASE()', query)
        self.assertEqual(params, ['testing_widget', 'owner_id'])

    def test_gives_up_with_a_clear_error(self):
        with self.assertRaises(RuntimeError) as ctx:
            self.wait([0, 0], timeout=0.05, interval=0.01)
        self.assertIn('testing_widget.owner_id', str(ctx.exception))
