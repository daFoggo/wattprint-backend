"""Copilot retrieval and advice: lexicon, terms, rules, motif instances, same-home device links

Spec: docs/superpowers/specs/2026-11-06-copilot-text2sql-design.md ("Schema changes").

- catalog.device_type.synonyms (everyday and regional names) and a `fan` type; devices named
  like "fan" are re-typed from `other`.
- copilot_ro.match_key(text): lower case, no tone marks, question syllables dropped. The lexicon
  phrase and the question both go through it before strict_word_similarity.
- unique core.device (home_id, id); the device links of copilot.suggestion, insight.alert and
  insight.device_cycle become (home_id, device_id), so a row can no longer name another home's
  device. billing.bill_item has no home_id and keeps its plain link (its view joins the bill).
- copilot.term, copilot.rule, insight.motif_instance; copilot.suggestion gains rule_id,
  motif_instance_id and evidence.
- copilot_ro views lexicon, term, rule, motif_instance (scoped by current_home()).

Revision ID: 6c2e8f1a4b90
Revises: f3a9c1e5b7d2
"""

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import JSONB

from alembic import op

revision = "6c2e8f1a4b90"
down_revision = "f3a9c1e5b7d2"
branch_labels = None
depends_on = None

APP = "wattprint_app"
COPILOT = "wattprint_copilot_ro"
HOME = "copilot_ro.current_home()"

# Kept in step with app.copilot.utils.catalog.QUESTION_SYLLABLES by tests/test_copilot_sql.py.
# Unaccented question words: điện dùng tốn bao nhiêu hôm qua không cái kWh, and đó / này / kia /
# nào / thế ("đó" and "đồ" both become "do": "cái máy đó" must not link to "máy sấy đồ").
QUESTION_SYLLABLES = (
    "dien", "dung", "ton", "bao", "nhieu", "hom", "qua", "khong", "cai", "kwh", "do", "nay", "kia",
    "nao", "the",
)

MATCH_KEY_FN = f"""
CREATE FUNCTION copilot_ro.match_key(text) RETURNS text
LANGUAGE sql IMMUTABLE PARALLEL SAFE STRICT
SET search_path = pg_catalog, public AS $$
    SELECT coalesce(string_agg(w, ' ' ORDER BY i), '')
    FROM unnest(regexp_split_to_array(lower(knowledge.immutable_unaccent($1)), '[^a-z0-9]+'))
         WITH ORDINALITY AS t(w, i)
    WHERE w <> '' AND w <> ALL (ARRAY[{", ".join(f"'{s}'" for s in QUESTION_SYLLABLES)}])
$$
"""

SYNONYMS: dict[str, list[str]] = {
    "ac": ["máy lạnh", "điều hoà", "máy điều hòa", "air con", "aircon"],
    "computer": ["máy vi tính", "laptop", "pc"],
    "dishwasher": ["máy rửa chén", "máy rửa chén bát"],
    "electric_car": ["ô tô điện", "sạc xe", "ev"],
    "electric_heater": ["máy sưởi", "sưởi điện"],
    "fan": ["quạt trần", "quạt đứng", "quạt máy", "quạt điện"],
    "fridge": ["tủ mát"],
    "fridge_freezer": ["tủ lạnh", "fridge"],
    "hifi": ["loa", "dàn loa", "âm ly"],
    "kettle": ["ấm siêu tốc", "ấm điện", "ấm nước", "bình đun"],
    "lights": ["đèn", "bóng đèn"],
    "microwave": ["lò vi ba"],
    "router": ["wifi", "modem", "cục phát wifi"],
    "television": ["tivi", "tv"],
    "tumble_dryer": ["máy sấy", "máy sấy đồ", "dryer"],
    "washing_machine": ["máy giặt đồ", "washer"],
    "water_heater": ["bình tắm", "máy nước nóng", "bình nước nóng", "bình nóng"],
}
FAN = ("fan", "Quạt", "Fan", 60, "Bật quạt thay điều hoà khi trời mát để tiết kiệm điện.")

SAME_HOME_FKS = (
    # table, old FK, new FK, ON DELETE
    ("copilot.suggestion", "fk_suggestion_device_id_device", "fk_suggestion_home_id_device",
     "SET NULL (device_id)"),
    ("insight.alert", "fk_alert_device_id_device", "fk_alert_home_id_device",
     "SET NULL (device_id)"),
    ("insight.device_cycle", "fk_device_cycle_device_id_device", "fk_device_cycle_home_id_device",
     "CASCADE"),  # device_id is part of the primary key: it cannot be set to NULL
)

VIEWS: dict[str, str] = {
    # What words can link to, each with its match key. Precedence (term > type > device name)
    # is applied by the caller; the view only lists.
    "lexicon": f"""
        SELECT 'device'::text AS source, 'device'::text AS kind, d.id::text AS ref,
               NULL::jsonb AS target, d.name::text AS phrase,
               copilot_ro.match_key(d.name) AS match_key
        FROM core.device d
        WHERE d.home_id = {HOME} AND d.deleted_at IS NULL
        UNION ALL
        SELECT 'room', 'device', d.id::text, NULL, d.room::text, copilot_ro.match_key(d.room)
        FROM core.device d
        WHERE d.home_id = {HOME} AND d.deleted_at IS NULL AND d.room IS NOT NULL
        UNION ALL
        SELECT 'device_type', 'device_type', t.code::text, NULL, p.phrase,
               copilot_ro.match_key(p.phrase)
        FROM catalog.device_type t
        CROSS JOIN LATERAL unnest(ARRAY[t.label_vi::text, t.label_en::text] || t.synonyms)
             AS p(phrase)
        WHERE {HOME} IS NOT NULL
        UNION ALL
        SELECT 'term', m.kind::text, coalesce(m.target->>'device_id', m.target->>'code'),
               m.target, m.phrase, m.match_key
        FROM copilot.term m
        WHERE m.home_id = {HOME}""",
    "term": f"""
        SELECT m.id, m.phrase, m.match_key, m.kind, m.target, m.created_at, m.updated_at
        FROM copilot.term m
        WHERE m.home_id = {HOME}""",
    "rule": f"""
        SELECT r.id, r.home_id, r.name, r.motif, r.body, r.suggest_kind, r.compiled_sql,
               r.enabled, r.version
        FROM copilot.rule r
        WHERE (r.home_id IS NULL AND {HOME} IS NOT NULL) OR r.home_id = {HOME}""",
    "motif_instance": f"""
        SELECT i.id, i.home_id, i.motif, i.device_id, i.start_ts, i.end_ts, i.facts, i.kwh,
               i.detected_at
        FROM insight.motif_instance i
        WHERE i.home_id = {HOME}""",
}

SUGGESTION_VIEW_OLD = f"""
        SELECT g.id, g.home_id, g.device_id, g.alert_id, g.kind, g.title, g.body,
               g.expected_kwh, g.expected_amount, g.status, g.created_at
        FROM copilot.suggestion g
        WHERE g.home_id = {HOME}
          AND (g.device_id IS NULL
               OR EXISTS (SELECT 1 FROM core.device d
                          WHERE d.id = g.device_id AND d.home_id = g.home_id))"""
SUGGESTION_VIEW_NEW = SUGGESTION_VIEW_OLD.replace(
    "g.status, g.created_at",
    "g.status, g.created_at,\n               g.rule_id, g.motif_instance_id, g.evidence",
)

NEW_TABLES = ("copilot.term", "copilot.rule", "insight.motif_instance")


def _uuid_pk() -> sa.Column:
    return sa.Column("id", sa.UUID, primary_key=True, server_default=sa.text("gen_random_uuid()"))


def _ts(name: str) -> sa.Column:
    return sa.Column(name, sa.DateTime(timezone=True), nullable=False,
                     server_default=sa.text("now()"))


def _device_types() -> None:
    op.add_column(
        "device_type",
        sa.Column("synonyms", sa.ARRAY(sa.Text), nullable=False, server_default="{}"),
        schema="catalog",
    )
    op.execute(
        sa.text(
            "INSERT INTO catalog.device_type (code, label_vi, label_en, typical_watts, tip_text) "
            "VALUES (:c, :vi, :en, :w, :tip) ON CONFLICT (code) DO NOTHING"
        ).bindparams(c=FAN[0], vi=FAN[1], en=FAN[2], w=FAN[3], tip=FAN[4])
    )
    for code, words in SYNONYMS.items():
        op.execute(
            sa.text("UPDATE catalog.device_type SET synonyms = :s WHERE code = :c")
            .bindparams(sa.bindparam("s", words, type_=sa.ARRAY(sa.Text)), c=code)
        )
    op.execute(
        "UPDATE core.device SET device_type_code = 'fan' "
        "WHERE device_type_code = 'other' AND name ~* '\\mfan\\M'"
    )


def _same_home_links() -> None:
    op.create_unique_constraint("uq_device_home_id", "device", ["home_id", "id"], schema="core")
    for table, old, new, on_delete in SAME_HOME_FKS:
        op.execute(f"ALTER TABLE {table} DROP CONSTRAINT {old}")
        op.execute(
            f"ALTER TABLE {table} ADD CONSTRAINT {new} FOREIGN KEY (home_id, device_id) "
            f"REFERENCES core.device (home_id, id) ON DELETE {on_delete}"
        )


def _tables() -> None:
    op.create_table(
        "term",
        _uuid_pk(),
        sa.Column("home_id", sa.UUID, nullable=False),
        sa.Column("phrase", sa.Text, nullable=False),
        sa.Column("match_key", sa.Text, nullable=False),
        sa.Column("kind", sa.String(16), nullable=False),
        sa.Column("target", JSONB, nullable=False),
        sa.Column("created_by", sa.UUID),
        sa.Column("created_from_message_id", sa.UUID),
        _ts("created_at"),
        _ts("updated_at"),
        sa.CheckConstraint("kind IN ('device','device_type','time_window','threshold')",
                           name="ck_term_kind"),
        sa.CheckConstraint("match_key <> ''", name="ck_term_match_key"),
        sa.ForeignKeyConstraint(["home_id"], ["core.home.id"], ondelete="CASCADE",
                                name="fk_term_home_id_home"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL",
                                name="fk_term_created_by_users"),
        sa.ForeignKeyConstraint(["created_from_message_id"], ["copilot.message.id"],
                                ondelete="SET NULL",
                                name="fk_term_created_from_message_id_message"),
        sa.UniqueConstraint("home_id", "match_key", name="uq_term_home_id"),
        schema="copilot",
    )
    op.create_table(
        "rule",
        _uuid_pk(),
        sa.Column("home_id", sa.UUID),  # NULL: shared expert rule, seeded from the code
        sa.Column("name", sa.Text, nullable=False),
        sa.Column("motif", sa.Text, nullable=False),
        sa.Column("body", JSONB, nullable=False),
        sa.Column("suggest_kind", sa.Text, nullable=False),
        sa.Column("compiled_sql", sa.Text, nullable=False),
        sa.Column("enabled", sa.Boolean, nullable=False, server_default=sa.text("true")),
        sa.Column("version", sa.Integer, nullable=False, server_default="1"),
        sa.Column("content_hash", sa.Text, nullable=False),
        sa.Column("created_by", sa.UUID),
        _ts("created_at"),
        _ts("updated_at"),
        sa.ForeignKeyConstraint(["home_id"], ["core.home.id"], ondelete="CASCADE",
                                name="fk_rule_home_id_home"),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], ondelete="SET NULL",
                                name="fk_rule_created_by_users"),
        schema="copilot",
    )
    op.execute(
        "ALTER TABLE copilot.rule ADD CONSTRAINT uq_rule_home_id "
        "UNIQUE NULLS NOT DISTINCT (home_id, name)"
    )
    op.create_table(
        "motif_instance",
        _uuid_pk(),
        sa.Column("home_id", sa.UUID, nullable=False),
        sa.Column("motif", sa.Text, nullable=False),
        sa.Column("device_id", sa.UUID),
        sa.Column("start_ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_ts", sa.DateTime(timezone=True), nullable=False),
        sa.Column("facts", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("kwh", sa.Numeric(12, 3)),
        _ts("detected_at"),
        sa.CheckConstraint("end_ts > start_ts", name="ck_motif_instance_range"),
        sa.ForeignKeyConstraint(["home_id"], ["core.home.id"], ondelete="CASCADE",
                                name="fk_motif_instance_home_id_home"),
        # An instance about a deleted device is meaningless: it goes with the device.
        sa.ForeignKeyConstraint(["home_id", "device_id"], ["core.device.home_id", "core.device.id"],
                                ondelete="CASCADE", name="fk_motif_instance_home_id_device"),
        schema="insight",
    )
    op.execute(
        "ALTER TABLE insight.motif_instance ADD CONSTRAINT uq_motif_instance_home_id "
        "UNIQUE NULLS NOT DISTINCT (home_id, motif, device_id, start_ts)"
    )
    op.create_index("ix_motif_instance_home_motif_start", "motif_instance",
                    ["home_id", "motif", sa.text("start_ts DESC")], schema="insight")

    op.add_column("suggestion", sa.Column("rule_id", sa.UUID), schema="copilot")
    op.add_column("suggestion", sa.Column("motif_instance_id", sa.UUID), schema="copilot")
    op.add_column(
        "suggestion",
        sa.Column("evidence", JSONB, nullable=False, server_default=sa.text("'{}'::jsonb")),
        schema="copilot",
    )
    op.create_foreign_key("fk_suggestion_rule_id_rule", "suggestion", "rule", ["rule_id"], ["id"],
                          source_schema="copilot", referent_schema="copilot", ondelete="SET NULL")
    op.create_foreign_key("fk_suggestion_motif_instance_id_motif_instance", "suggestion",
                          "motif_instance", ["motif_instance_id"], ["id"],
                          source_schema="copilot", referent_schema="insight",
                          ondelete="SET NULL")


def _indexes() -> None:
    op.drop_index("ix_copilot_message_conversation_id", "message", schema="copilot")
    op.create_index("ix_message_conversation_created", "message",
                    ["conversation_id", sa.text("created_at DESC")], schema="copilot")
    op.create_index("ix_suggestion_home_status", "suggestion", ["home_id", "status"],
                    schema="copilot")


def upgrade() -> None:
    _device_types()
    op.execute(MATCH_KEY_FN)
    op.execute("REVOKE ALL ON FUNCTION copilot_ro.match_key(text) FROM PUBLIC")
    op.execute(f"GRANT EXECUTE ON FUNCTION copilot_ro.match_key(text) TO {COPILOT}, {APP}")
    # the app login computes a term's match key; USAGE alone shows it no view (no SELECT)
    op.execute(f"GRANT USAGE ON SCHEMA copilot_ro TO {APP}")
    _same_home_links()
    _tables()
    _indexes()
    op.execute(f"CREATE OR REPLACE VIEW copilot_ro.suggestion WITH (security_barrier = true) AS "
               f"{SUGGESTION_VIEW_NEW}")
    for name, body in VIEWS.items():
        op.execute(f"CREATE VIEW copilot_ro.{name} WITH (security_barrier = true) AS {body}")
        op.execute(f"REVOKE ALL ON copilot_ro.{name} FROM PUBLIC")
        op.execute(f"GRANT SELECT ON copilot_ro.{name} TO {COPILOT}")
    for table in NEW_TABLES:
        op.execute(f"GRANT SELECT, INSERT, UPDATE, DELETE ON {table} TO {APP}")


def downgrade() -> None:
    op.execute(f"REVOKE USAGE ON SCHEMA copilot_ro FROM {APP}")
    for table in NEW_TABLES:
        op.execute(f"REVOKE ALL ON {table} FROM {APP}")
    for name in reversed(list(VIEWS)):
        op.execute(f"DROP VIEW copilot_ro.{name}")
    # a view cannot lose columns with CREATE OR REPLACE
    op.execute("DROP VIEW copilot_ro.suggestion")
    op.execute(f"CREATE VIEW copilot_ro.suggestion WITH (security_barrier = true) AS "
               f"{SUGGESTION_VIEW_OLD}")
    op.execute("REVOKE ALL ON copilot_ro.suggestion FROM PUBLIC")
    op.execute(f"GRANT SELECT ON copilot_ro.suggestion TO {COPILOT}")

    op.drop_index("ix_suggestion_home_status", "suggestion", schema="copilot")
    op.drop_index("ix_message_conversation_created", "message", schema="copilot")
    op.create_index("ix_copilot_message_conversation_id", "message", ["conversation_id"],
                    schema="copilot")

    op.drop_constraint("fk_suggestion_motif_instance_id_motif_instance", "suggestion",
                       schema="copilot")
    op.drop_constraint("fk_suggestion_rule_id_rule", "suggestion", schema="copilot")
    for col in ("evidence", "motif_instance_id", "rule_id"):
        op.drop_column("suggestion", col, schema="copilot")
    op.drop_table("motif_instance", schema="insight")
    op.drop_table("rule", schema="copilot")
    op.drop_table("term", schema="copilot")

    for table, old, new, on_delete in SAME_HOME_FKS:
        op.execute(f"ALTER TABLE {table} DROP CONSTRAINT {new}")
        old_delete = "CASCADE" if on_delete == "CASCADE" else "SET NULL"
        op.execute(
            f"ALTER TABLE {table} ADD CONSTRAINT {old} FOREIGN KEY (device_id) "
            f"REFERENCES core.device (id) ON DELETE {old_delete}"
        )
    op.drop_constraint("uq_device_home_id", "device", schema="core")

    op.execute("DROP FUNCTION copilot_ro.match_key(text)")
    op.execute("UPDATE core.device SET device_type_code = 'other' WHERE device_type_code = 'fan'")
    op.execute("DELETE FROM catalog.device_type WHERE code = 'fan'")
    op.drop_column("device_type", "synonyms", schema="catalog")
