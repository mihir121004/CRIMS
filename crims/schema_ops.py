"""Schema operations that tolerate MySQL-family DDL quirks.

TiDB
----
TiDB applies DDL asynchronously, and it rejects the single-statement form
Django's MySQL backend uses to add a foreign key column::

    ALTER TABLE evidence ADD COLUMN uploaded_by_id bigint NULL,
      ADD CONSTRAINT evidence_uploaded_by_fk FOREIGN KEY (uploaded_by_id)
      REFERENCES accounts_user (id)

The constraint cannot reference a column introduced by the very same
statement, so MySQL and TiDB both answer::

    (1072, "Key column 'uploaded_by_id' doesn't exist in table")

Django only reaches for that combined form because
``sql_create_column_inline_fk`` is set on the MySQL backend. Clearing it for
the duration of the operation makes Django fall back to its other supported
path, appending the constraint to ``deferred_sql`` instead - which is flushed
as a separate statement once the migration's operations have run.

Because TiDB's schema change is still propagating when that flush happens,
:func:`SplitForeignKeyAddField._wait_for_column` blocks until the new column
is actually visible in ``information_schema`` rather than assuming it is.
"""
import time

from django.db import migrations

#: How long to wait for TiDB to publish a new column before giving up.
COLUMN_VISIBILITY_TIMEOUT = 60.0
COLUMN_VISIBILITY_INTERVAL = 0.25


class SplitForeignKeyAddField(migrations.AddField):
    """AddField that creates a FK column and its constraint separately.

    Behaves exactly like ``migrations.AddField`` on backends that do not inline
    foreign keys, so it is safe to use unconditionally.
    """

    def _inlines_foreign_key(self, schema_editor, field):
        return (
            getattr(schema_editor, 'sql_create_column_inline_fk', None)
            and field.remote_field
            and field.foreign_related_fields
            and field.db_constraint
            and schema_editor.connection.features.supports_foreign_keys
        )

    def database_forwards(self, app_label, schema_editor, from_state, to_state):
        model = to_state.apps.get_model(app_label, self.model_name)
        field = model._meta.get_field(self.name)

        if not self._inlines_foreign_key(schema_editor, field):
            return super().database_forwards(
                app_label, schema_editor, from_state, to_state
            )

        original = schema_editor.sql_create_column_inline_fk
        schema_editor.sql_create_column_inline_fk = None
        try:
            super().database_forwards(
                app_label, schema_editor, from_state, to_state
            )
        finally:
            schema_editor.sql_create_column_inline_fk = original

        # The constraint now sits in schema_editor.deferred_sql and will run
        # after the migration's remaining operations. Make sure the column it
        # references exists before that happens.
        self._wait_for_column(
            schema_editor, model._meta.db_table, field.column
        )

    def _wait_for_column(self, schema_editor, table, column):
        query = (
            'SELECT COUNT(*) FROM information_schema.COLUMNS '
            'WHERE TABLE_SCHEMA = DATABASE() AND TABLE_NAME = %s '
            'AND COLUMN_NAME = %s'
        )
        deadline = time.monotonic() + COLUMN_VISIBILITY_TIMEOUT
        with schema_editor.connection.cursor() as cursor:
            while True:
                cursor.execute(query, [table, column])
                if cursor.fetchone()[0]:
                    return
                if time.monotonic() >= deadline:
                    raise RuntimeError(
                        'column {}.{} still not visible after {:.0f}s; '
                        'is this TiDB with an unusually slow schema sync?'
                        .format(table, column, COLUMN_VISIBILITY_TIMEOUT)
                    )
                time.sleep(COLUMN_VISIBILITY_INTERVAL)

    def describe(self):
        return 'Split FK AddField {}.{}'.format(self.model_name, self.name)
