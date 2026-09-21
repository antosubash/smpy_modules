BEGIN;

CREATE TABLE alembic_version (
    version_num VARCHAR(32) NOT NULL, 
    CONSTRAINT alembic_version_pkc PRIMARY KEY (version_num)
);

-- Running upgrade  -> ed06f4584f6b

CREATE TABLE permissions_role_permission (
    created_at TIMESTAMP WITH TIME ZONE DEFAULT (CURRENT_TIMESTAMP) NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE, 
    created_by VARCHAR(255), 
    updated_by VARCHAR(255), 
    role_name VARCHAR(64) NOT NULL, 
    permission_key VARCHAR(128) NOT NULL, 
    assigned_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    assigned_by VARCHAR(255), 
    CONSTRAINT pk_permissions_role_permission PRIMARY KEY (role_name, permission_key)
);

CREATE INDEX ix_permissions_role_permission_key ON permissions_role_permission (permission_key);

CREATE TABLE permissions_user_permission (
    created_at TIMESTAMP WITH TIME ZONE DEFAULT (CURRENT_TIMESTAMP) NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE, 
    created_by VARCHAR(255), 
    updated_by VARCHAR(255), 
    user_id UUID NOT NULL, 
    permission_key VARCHAR(128) NOT NULL, 
    assigned_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    assigned_by VARCHAR(255), 
    CONSTRAINT pk_permissions_user_permission PRIMARY KEY (user_id, permission_key)
);

CREATE INDEX ix_permissions_user_permission_key ON permissions_user_permission (permission_key);

CREATE TABLE settings_setting (
    created_at TIMESTAMP WITH TIME ZONE DEFAULT (CURRENT_TIMESTAMP) NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE, 
    created_by VARCHAR(255), 
    updated_by VARCHAR(255), 
    id SERIAL NOT NULL, 
    scope VARCHAR(10) NOT NULL, 
    scope_id VARCHAR(255) NOT NULL, 
    key VARCHAR(200) NOT NULL, 
    value VARCHAR(4000) NOT NULL, 
    value_type VARCHAR(10) NOT NULL, 
    description VARCHAR(2000), 
    CONSTRAINT pk_settings_setting PRIMARY KEY (id), 
    CONSTRAINT uq_settings_setting_scope_scope_id_key UNIQUE (scope, scope_id, key)
);

CREATE INDEX ix_settings_setting_key ON settings_setting (key);

CREATE INDEX ix_settings_setting_scope ON settings_setting (scope);

CREATE INDEX ix_settings_setting_scope_id ON settings_setting (scope_id);

CREATE TABLE users_role (
    created_at TIMESTAMP WITH TIME ZONE DEFAULT (CURRENT_TIMESTAMP) NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE, 
    created_by VARCHAR(255), 
    updated_by VARCHAR(255), 
    id UUID NOT NULL, 
    name VARCHAR(64) NOT NULL, 
    description VARCHAR(255), 
    CONSTRAINT pk_users_role PRIMARY KEY (id)
);

CREATE UNIQUE INDEX ix_users_role_name ON users_role (name);

CREATE TABLE users_user (
    created_at TIMESTAMP WITH TIME ZONE DEFAULT (CURRENT_TIMESTAMP) NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE, 
    created_by VARCHAR(255), 
    updated_by VARCHAR(255), 
    id UUID NOT NULL, 
    email VARCHAR(320) NOT NULL, 
    hashed_password VARCHAR(1024), 
    is_active BOOLEAN NOT NULL, 
    is_superuser BOOLEAN NOT NULL, 
    is_verified BOOLEAN NOT NULL, 
    is_external BOOLEAN DEFAULT false NOT NULL, 
    full_name VARCHAR(255), 
    tenant_id VARCHAR(50), 
    disabled_at TIMESTAMP WITH TIME ZONE, 
    last_login_at TIMESTAMP WITH TIME ZONE, 
    CONSTRAINT pk_users_user PRIMARY KEY (id)
);

CREATE UNIQUE INDEX ix_users_user_email ON users_user (email);

CREATE INDEX ix_users_user_last_login_at ON users_user (last_login_at);

CREATE INDEX ix_users_user_tenant_id ON users_user (tenant_id);

CREATE TABLE users_access_token (
    token VARCHAR(43) NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    user_id UUID NOT NULL, 
    CONSTRAINT pk_users_access_token PRIMARY KEY (token), 
    CONSTRAINT fk_users_access_token_user_id_users_user FOREIGN KEY(user_id) REFERENCES users_user (id) ON DELETE CASCADE
);

CREATE INDEX ix_users_access_token_created_at ON users_access_token (created_at);

CREATE INDEX ix_users_access_token_user_id ON users_access_token (user_id);

CREATE TABLE users_oauth_account (
    id UUID NOT NULL, 
    user_id UUID NOT NULL, 
    oauth_name VARCHAR(100) NOT NULL, 
    access_token VARCHAR(1024) NOT NULL, 
    expires_at INTEGER, 
    refresh_token VARCHAR(1024), 
    account_id VARCHAR(320) NOT NULL, 
    account_email VARCHAR(320) NOT NULL, 
    CONSTRAINT pk_users_oauth_account PRIMARY KEY (id), 
    CONSTRAINT fk_users_oauth_account_user_id_users_user FOREIGN KEY(user_id) REFERENCES users_user (id) ON DELETE CASCADE
);

CREATE INDEX ix_users_oauth_account_account_id ON users_oauth_account (account_id);

CREATE INDEX ix_users_oauth_account_oauth_name ON users_oauth_account (oauth_name);

CREATE INDEX ix_users_oauth_account_user_id ON users_oauth_account (user_id);

CREATE TABLE users_refresh_token (
    token UUID NOT NULL, 
    user_id UUID NOT NULL, 
    created_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
    expires_at TIMESTAMP WITHOUT TIME ZONE NOT NULL, 
    revoked_at TIMESTAMP WITHOUT TIME ZONE, 
    CONSTRAINT pk_users_refresh_token PRIMARY KEY (token), 
    CONSTRAINT fk_users_refresh_token_user_id_users_user FOREIGN KEY(user_id) REFERENCES users_user (id)
);

CREATE INDEX ix_users_refresh_token_user_id ON users_refresh_token (user_id);

CREATE TABLE users_user_role (
    user_id UUID NOT NULL, 
    role_id UUID NOT NULL, 
    assigned_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    assigned_by VARCHAR(255), 
    CONSTRAINT pk_users_user_role PRIMARY KEY (user_id, role_id), 
    CONSTRAINT fk_users_user_role_role_id_users_role FOREIGN KEY(role_id) REFERENCES users_role (id) ON DELETE CASCADE, 
    CONSTRAINT fk_users_user_role_user_id_users_user FOREIGN KEY(user_id) REFERENCES users_user (id) ON DELETE CASCADE
);

CREATE INDEX ix_users_user_role_role_id ON users_user_role (role_id);

INSERT INTO alembic_version (version_num) VALUES ('ed06f4584f6b') RETURNING alembic_version.version_num;

-- Running upgrade ed06f4584f6b -> 4cf1b4c9f8f9

CREATE TABLE pagebuilder_layout (
    created_at TIMESTAMP WITH TIME ZONE DEFAULT (CURRENT_TIMESTAMP) NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE, 
    created_by VARCHAR(255), 
    updated_by VARCHAR(255), 
    id SERIAL NOT NULL, 
    header_data JSON NOT NULL, 
    footer_data JSON NOT NULL, 
    CONSTRAINT pk_pagebuilder_layout PRIMARY KEY (id)
);

CREATE TABLE pagebuilder_media (
    created_at TIMESTAMP WITH TIME ZONE DEFAULT (CURRENT_TIMESTAMP) NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE, 
    created_by VARCHAR(255), 
    updated_by VARCHAR(255), 
    id SERIAL NOT NULL, 
    filename VARCHAR(300) NOT NULL, 
    original_filename VARCHAR(300) NOT NULL, 
    content_type VARCHAR(120) NOT NULL, 
    size_bytes INTEGER NOT NULL, 
    width INTEGER, 
    height INTEGER, 
    folder VARCHAR(300), 
    variants JSON NOT NULL, 
    CONSTRAINT pk_pagebuilder_media PRIMARY KEY (id)
);

CREATE UNIQUE INDEX ix_pagebuilder_media_filename ON pagebuilder_media (filename);

CREATE INDEX ix_pagebuilder_media_folder ON pagebuilder_media (folder);

CREATE TYPE pagebuilder_page_status AS ENUM ('DRAFT', 'SUBMITTED_FOR_REVIEW', 'PUBLISHED');

CREATE TABLE pagebuilder_pages (
    created_at TIMESTAMP WITH TIME ZONE DEFAULT (CURRENT_TIMESTAMP) NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE, 
    created_by VARCHAR(255), 
    updated_by VARCHAR(255), 
    id SERIAL NOT NULL, 
    slug VARCHAR(200) NOT NULL, 
    title VARCHAR(300) NOT NULL, 
    meta_description VARCHAR(500), 
    og_image VARCHAR(500), 
    status pagebuilder_page_status NOT NULL, 
    draft_data JSON NOT NULL, 
    published_data JSON, 
    canonical_url VARCHAR(500), 
    index_in_search BOOLEAN NOT NULL, 
    json_ld JSON, 
    rejection_note VARCHAR(2000), 
    publish_at TIMESTAMP WITH TIME ZONE, 
    unpublish_at TIMESTAMP WITH TIME ZONE, 
    CONSTRAINT pk_pagebuilder_pages PRIMARY KEY (id)
);

CREATE UNIQUE INDEX ix_pagebuilder_pages_slug ON pagebuilder_pages (slug);

CREATE INDEX ix_pagebuilder_pages_status ON pagebuilder_pages (status);

CREATE TABLE pagebuilder_layout_revisions (
    created_at TIMESTAMP WITH TIME ZONE DEFAULT (CURRENT_TIMESTAMP) NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE, 
    created_by VARCHAR(255), 
    updated_by VARCHAR(255), 
    id SERIAL NOT NULL, 
    layout_id INTEGER NOT NULL, 
    header_data JSON NOT NULL, 
    footer_data JSON NOT NULL, 
    note VARCHAR(2000), 
    CONSTRAINT pk_pagebuilder_layout_revisions PRIMARY KEY (id), 
    CONSTRAINT fk_pagebuilder_layout_revisions_layout_id_pagebuilder_layout FOREIGN KEY(layout_id) REFERENCES pagebuilder_layout (id)
);

CREATE INDEX ix_pagebuilder_layout_revisions_layout_id ON pagebuilder_layout_revisions (layout_id);

CREATE TYPE pagebuilder_revision_event AS ENUM ('PUBLISH', 'UNPUBLISH', 'SUBMIT', 'APPROVE', 'REJECT');

CREATE TABLE pagebuilder_page_revisions (
    created_at TIMESTAMP WITH TIME ZONE DEFAULT (CURRENT_TIMESTAMP) NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE, 
    created_by VARCHAR(255), 
    updated_by VARCHAR(255), 
    id SERIAL NOT NULL, 
    page_id INTEGER NOT NULL, 
    title VARCHAR(300) NOT NULL, 
    meta_description VARCHAR(500), 
    og_image VARCHAR(500), 
    data JSON NOT NULL, 
    event pagebuilder_revision_event DEFAULT 'PUBLISH' NOT NULL, 
    note VARCHAR(2000), 
    CONSTRAINT pk_pagebuilder_page_revisions PRIMARY KEY (id), 
    CONSTRAINT fk_pagebuilder_page_revisions_page_id_pagebuilder_pages FOREIGN KEY(page_id) REFERENCES pagebuilder_pages (id)
);

CREATE INDEX ix_pagebuilder_page_revisions_event ON pagebuilder_page_revisions (event);

CREATE INDEX ix_pagebuilder_page_revisions_page_id ON pagebuilder_page_revisions (page_id);

UPDATE alembic_version SET version_num='4cf1b4c9f8f9' WHERE alembic_version.version_num = 'ed06f4584f6b';

-- Running upgrade 4cf1b4c9f8f9 -> ca297bbf33bf

CREATE TABLE file_storage_stored_file (
    is_deleted BOOLEAN NOT NULL, 
    deleted_at TIMESTAMP WITH TIME ZONE, 
    deleted_by VARCHAR(255), 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT (CURRENT_TIMESTAMP) NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE, 
    created_by VARCHAR(255), 
    updated_by VARCHAR(255), 
    id UUID NOT NULL, 
    key VARCHAR(512) NOT NULL, 
    filename VARCHAR(255) NOT NULL, 
    content_type VARCHAR(128) NOT NULL, 
    size_bytes INTEGER NOT NULL, 
    backend VARCHAR(32) NOT NULL, 
    checksum_sha256 VARCHAR(64) NOT NULL, 
    extra_metadata JSON NOT NULL, 
    CONSTRAINT pk_file_storage_stored_file PRIMARY KEY (id)
);

CREATE INDEX ix_file_storage_stored_file_created_by ON file_storage_stored_file (created_by);

CREATE INDEX ix_file_storage_stored_file_is_deleted ON file_storage_stored_file (is_deleted);

CREATE UNIQUE INDEX ix_file_storage_stored_file_key ON file_storage_stored_file (key);

UPDATE alembic_version SET version_num='ca297bbf33bf' WHERE alembic_version.version_num = '4cf1b4c9f8f9';

-- Running upgrade ca297bbf33bf -> 52d927feccb3

CREATE TABLE news_articles (
    created_at TIMESTAMP WITH TIME ZONE DEFAULT (CURRENT_TIMESTAMP) NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE, 
    created_by VARCHAR(255), 
    updated_by VARCHAR(255), 
    id SERIAL NOT NULL, 
    page_id INTEGER NOT NULL, 
    category VARCHAR(80) NOT NULL, 
    published_at TIMESTAMP WITH TIME ZONE, 
    CONSTRAINT pk_news_articles PRIMARY KEY (id)
);

CREATE INDEX ix_news_articles_category ON news_articles (category);

CREATE UNIQUE INDEX ix_news_articles_page_id ON news_articles (page_id);

CREATE INDEX ix_news_articles_published_at ON news_articles (published_at);

UPDATE alembic_version SET version_num='52d927feccb3' WHERE alembic_version.version_num = 'ca297bbf33bf';

-- Running upgrade 52d927feccb3 -> 7fa1b9a883ff

CREATE TABLE news_categories (
    created_at TIMESTAMP WITH TIME ZONE DEFAULT (CURRENT_TIMESTAMP) NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE, 
    created_by VARCHAR(255), 
    updated_by VARCHAR(255), 
    id SERIAL NOT NULL, 
    name VARCHAR(80) NOT NULL, 
    slug VARCHAR(80) NOT NULL, 
    position INTEGER NOT NULL, 
    CONSTRAINT pk_news_categories PRIMARY KEY (id)
);

CREATE UNIQUE INDEX ix_news_categories_name ON news_categories (name);

CREATE INDEX ix_news_categories_position ON news_categories (position);

CREATE UNIQUE INDEX ix_news_categories_slug ON news_categories (slug);

CREATE TABLE news_tags (
    created_at TIMESTAMP WITH TIME ZONE DEFAULT (CURRENT_TIMESTAMP) NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE, 
    created_by VARCHAR(255), 
    updated_by VARCHAR(255), 
    id SERIAL NOT NULL, 
    name VARCHAR(60) NOT NULL, 
    slug VARCHAR(60) NOT NULL, 
    CONSTRAINT pk_news_tags PRIMARY KEY (id)
);

CREATE UNIQUE INDEX ix_news_tags_name ON news_tags (name);

CREATE UNIQUE INDEX ix_news_tags_slug ON news_tags (slug);

CREATE TABLE news_article_tags (
    article_id INTEGER NOT NULL, 
    tag_id INTEGER NOT NULL, 
    CONSTRAINT pk_news_article_tags PRIMARY KEY (article_id, tag_id), 
    CONSTRAINT fk_news_article_tags_article_id_news_articles FOREIGN KEY(article_id) REFERENCES news_articles (id) ON DELETE CASCADE, 
    CONSTRAINT fk_news_article_tags_tag_id_news_tags FOREIGN KEY(tag_id) REFERENCES news_tags (id) ON DELETE CASCADE
);

UPDATE alembic_version SET version_num='7fa1b9a883ff' WHERE alembic_version.version_num = '52d927feccb3';

-- Running upgrade 7fa1b9a883ff -> af06f6ea093e

ALTER TABLE pagebuilder_pages ADD COLUMN parent_id INTEGER;

ALTER TABLE pagebuilder_pages ADD COLUMN is_template BOOLEAN DEFAULT false NOT NULL;

ALTER TABLE pagebuilder_pages ADD CONSTRAINT fk_pagebuilder_pages_parent_id_pagebuilder_pages FOREIGN KEY(parent_id) REFERENCES pagebuilder_pages (id) ON DELETE SET NULL;

CREATE INDEX ix_pagebuilder_pages_is_template ON pagebuilder_pages (is_template);

CREATE INDEX ix_pagebuilder_pages_parent_id ON pagebuilder_pages (parent_id);

ALTER TABLE pagebuilder_pages ALTER COLUMN is_template DROP DEFAULT;

UPDATE alembic_version SET version_num='af06f6ea093e' WHERE alembic_version.version_num = '7fa1b9a883ff';

-- Running upgrade af06f6ea093e -> 0cce3a443a27

ALTER TABLE pagebuilder_pages ADD COLUMN deleted_at TIMESTAMP WITH TIME ZONE;

CREATE INDEX ix_pagebuilder_pages_deleted_at ON pagebuilder_pages (deleted_at);

UPDATE alembic_version SET version_num='0cce3a443a27' WHERE alembic_version.version_num = 'af06f6ea093e';

-- Running upgrade 0cce3a443a27 -> 7a776d0b6240

ALTER TABLE news_articles ADD COLUMN pinned BOOLEAN DEFAULT false NOT NULL;

ALTER TABLE news_articles ADD COLUMN show_in_feed BOOLEAN DEFAULT true NOT NULL;

ALTER TABLE news_articles ADD COLUMN author VARCHAR(120) DEFAULT '' NOT NULL;

CREATE INDEX ix_news_articles_pinned ON news_articles (pinned);

CREATE INDEX ix_news_articles_show_in_feed ON news_articles (show_in_feed);

ALTER TABLE news_articles ALTER COLUMN pinned DROP DEFAULT;

ALTER TABLE news_articles ALTER COLUMN show_in_feed DROP DEFAULT;

ALTER TABLE news_articles ALTER COLUMN author DROP DEFAULT;

UPDATE alembic_version SET version_num='7a776d0b6240' WHERE alembic_version.version_num = '0cce3a443a27';

-- Running upgrade 7a776d0b6240 -> 7327cb99fe0a

CREATE TABLE pagebuilder_page_redirects (
    id SERIAL NOT NULL, 
    from_slug VARCHAR(200) NOT NULL, 
    page_id INTEGER NOT NULL, 
    CONSTRAINT pk_pagebuilder_page_redirects PRIMARY KEY (id), 
    CONSTRAINT fk_pagebuilder_page_redirects_page_id_pagebuilder_pages FOREIGN KEY(page_id) REFERENCES pagebuilder_pages (id) ON DELETE CASCADE
);

CREATE UNIQUE INDEX ix_pagebuilder_page_redirects_from_slug ON pagebuilder_page_redirects (from_slug);

CREATE INDEX ix_pagebuilder_page_redirects_page_id ON pagebuilder_page_redirects (page_id);

ALTER TABLE pagebuilder_pages ADD COLUMN meta_title VARCHAR(200);

ALTER TABLE pagebuilder_pages ADD COLUMN show_in_header_nav BOOLEAN DEFAULT false NOT NULL;

ALTER TABLE pagebuilder_pages ADD COLUMN show_in_footer BOOLEAN DEFAULT false NOT NULL;

CREATE INDEX ix_pagebuilder_pages_show_in_header_nav ON pagebuilder_pages (show_in_header_nav);

CREATE INDEX ix_pagebuilder_pages_show_in_footer ON pagebuilder_pages (show_in_footer);

ALTER TABLE pagebuilder_pages ALTER COLUMN show_in_header_nav DROP DEFAULT;

ALTER TABLE pagebuilder_pages ALTER COLUMN show_in_footer DROP DEFAULT;

UPDATE alembic_version SET version_num='7327cb99fe0a' WHERE alembic_version.version_num = '7a776d0b6240';

-- Running upgrade 7327cb99fe0a -> 6504b2249610

ALTER TABLE pagebuilder_media ADD COLUMN alt_text VARCHAR(500) DEFAULT '' NOT NULL;

ALTER TABLE pagebuilder_media ADD COLUMN caption VARCHAR(500) DEFAULT '' NOT NULL;

ALTER TABLE pagebuilder_media ADD COLUMN credit VARCHAR(200) DEFAULT '' NOT NULL;

ALTER TABLE pagebuilder_media ALTER COLUMN alt_text DROP DEFAULT;

ALTER TABLE pagebuilder_media ALTER COLUMN caption DROP DEFAULT;

ALTER TABLE pagebuilder_media ALTER COLUMN credit DROP DEFAULT;

UPDATE alembic_version SET version_num='6504b2249610' WHERE alembic_version.version_num = '7327cb99fe0a';

-- Running upgrade 6504b2249610 -> b98d8185ecef

CREATE TYPE pagebuilder_snapshot_source AS ENUM ('MANUAL', 'UPLOAD', 'PRE_RESTORE');

CREATE TABLE pagebuilder_snapshots (
    created_at TIMESTAMP WITH TIME ZONE DEFAULT (CURRENT_TIMESTAMP) NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE, 
    created_by VARCHAR(255), 
    updated_by VARCHAR(255), 
    id SERIAL NOT NULL, 
    note VARCHAR(2000), 
    source pagebuilder_snapshot_source NOT NULL, 
    format_version INTEGER NOT NULL, 
    manifest JSON NOT NULL, 
    size_bytes INTEGER NOT NULL, 
    CONSTRAINT pk_pagebuilder_snapshots PRIMARY KEY (id)
);

CREATE INDEX ix_pagebuilder_snapshots_source ON pagebuilder_snapshots (source);

CREATE TYPE pagebuilder_import_status AS ENUM ('PENDING', 'APPROVED', 'REJECTED');

CREATE TABLE pagebuilder_pending_imports (
    created_at TIMESTAMP WITH TIME ZONE DEFAULT (CURRENT_TIMESTAMP) NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE, 
    created_by VARCHAR(255), 
    updated_by VARCHAR(255), 
    id SERIAL NOT NULL, 
    snapshot_id INTEGER NOT NULL, 
    plan JSON NOT NULL, 
    status pagebuilder_import_status NOT NULL, 
    note VARCHAR(2000), 
    decided_at TIMESTAMP WITH TIME ZONE, 
    decided_by VARCHAR(200), 
    CONSTRAINT pk_pagebuilder_pending_imports PRIMARY KEY (id), 
    CONSTRAINT fk_pagebuilder_pending_imports_snapshot_id_pagebuilder__2bf7 FOREIGN KEY(snapshot_id) REFERENCES pagebuilder_snapshots (id) ON DELETE CASCADE
);

CREATE INDEX ix_pagebuilder_pending_imports_snapshot_id ON pagebuilder_pending_imports (snapshot_id);

CREATE INDEX ix_pagebuilder_pending_imports_status ON pagebuilder_pending_imports (status);

CREATE UNIQUE INDEX uq_pagebuilder_pending_imports_one_pending ON pagebuilder_pending_imports (status) WHERE status = 'PENDING';

CREATE TABLE pagebuilder_snapshot_media (
    id SERIAL NOT NULL, 
    snapshot_id INTEGER NOT NULL, 
    sha256 VARCHAR(64) NOT NULL, 
    bundle_name VARCHAR(300) NOT NULL, 
    original_filename VARCHAR(300) NOT NULL, 
    content_type VARCHAR(120) NOT NULL, 
    folder VARCHAR(300), 
    CONSTRAINT pk_pagebuilder_snapshot_media PRIMARY KEY (id), 
    CONSTRAINT fk_pagebuilder_snapshot_media_snapshot_id_pagebuilder_snapshots FOREIGN KEY(snapshot_id) REFERENCES pagebuilder_snapshots (id) ON DELETE CASCADE
);

CREATE INDEX ix_pagebuilder_snapshot_media_sha256 ON pagebuilder_snapshot_media (sha256);

CREATE INDEX ix_pagebuilder_snapshot_media_snapshot_id ON pagebuilder_snapshot_media (snapshot_id);

UPDATE alembic_version SET version_num='b98d8185ecef' WHERE alembic_version.version_num = '6504b2249610';

-- Running upgrade b98d8185ecef -> b1f4a72c9d30

ALTER TABLE pagebuilder_pages ADD COLUMN locale VARCHAR(12) DEFAULT 'en' NOT NULL;

ALTER TABLE pagebuilder_pages ADD COLUMN translation_group VARCHAR(32);

UPDATE pagebuilder_pages SET translation_group=('p' || CAST(pagebuilder_pages.id AS VARCHAR));

DROP INDEX ix_pagebuilder_pages_slug;

ALTER TABLE pagebuilder_pages ALTER COLUMN locale DROP DEFAULT;

ALTER TABLE pagebuilder_pages ALTER COLUMN translation_group SET NOT NULL;

CREATE UNIQUE INDEX ix_pagebuilder_pages_locale_slug ON pagebuilder_pages (locale, slug);

CREATE UNIQUE INDEX ix_pagebuilder_pages_group_locale ON pagebuilder_pages (translation_group, locale);

ALTER TABLE pagebuilder_page_redirects ADD COLUMN locale VARCHAR(12) DEFAULT 'en' NOT NULL;

DROP INDEX ix_pagebuilder_page_redirects_from_slug;

ALTER TABLE pagebuilder_page_redirects ALTER COLUMN locale DROP DEFAULT;

CREATE UNIQUE INDEX ix_pagebuilder_page_redirects_locale_from_slug ON pagebuilder_page_redirects (locale, from_slug);

UPDATE alembic_version SET version_num='b1f4a72c9d30' WHERE alembic_version.version_num = 'b98d8185ecef';

-- Running upgrade b1f4a72c9d30 -> e23090832709

CREATE TABLE records_type (
    created_at TIMESTAMP WITH TIME ZONE DEFAULT (CURRENT_TIMESTAMP) NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE, 
    created_by VARCHAR(255), 
    updated_by VARCHAR(255), 
    id SERIAL NOT NULL, 
    key VARCHAR(64) NOT NULL, 
    label VARCHAR(200) NOT NULL, 
    label_plural VARCHAR(200) NOT NULL, 
    description VARCHAR(1000), 
    icon VARCHAR(64), 
    fields JSON NOT NULL, 
    schema_version INTEGER NOT NULL, 
    display_field VARCHAR(64), 
    slug_field VARCHAR(64), 
    is_public BOOLEAN NOT NULL, 
    allowed_roles JSON NOT NULL, 
    version INTEGER NOT NULL, 
    reindex_pending JSON NOT NULL, 
    CONSTRAINT pk_records_type PRIMARY KEY (id)
);

CREATE UNIQUE INDEX ix_records_type_key ON records_type (key);

CREATE TYPE records_record_status AS ENUM ('DRAFT', 'PUBLISHED');

CREATE TABLE records_record (
    is_deleted BOOLEAN NOT NULL, 
    deleted_at TIMESTAMP WITH TIME ZONE, 
    deleted_by VARCHAR(255), 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT (CURRENT_TIMESTAMP) NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE, 
    created_by VARCHAR(255), 
    updated_by VARCHAR(255), 
    id SERIAL NOT NULL, 
    uuid VARCHAR(32) NOT NULL, 
    type_id INTEGER NOT NULL, 
    data JSON NOT NULL, 
    schema_version INTEGER NOT NULL, 
    version INTEGER NOT NULL, 
    status records_record_status NOT NULL, 
    slug VARCHAR(200), 
    display_title VARCHAR(300) NOT NULL, 
    position INTEGER NOT NULL, 
    published_at TIMESTAMP WITH TIME ZONE, 
    CONSTRAINT pk_records_record PRIMARY KEY (id), 
    CONSTRAINT fk_records_record_type_id_records_type FOREIGN KEY(type_id) REFERENCES records_type (id) ON DELETE RESTRICT
);

CREATE INDEX ix_records_record_published_at ON records_record (published_at);

CREATE INDEX ix_records_record_status ON records_record (status);

CREATE INDEX ix_records_record_type_id ON records_record (type_id);

CREATE UNIQUE INDEX ix_records_record_type_slug ON records_record (type_id, slug) WHERE slug IS NOT NULL;

CREATE INDEX ix_records_record_type_status_position ON records_record (type_id, status, position);

CREATE UNIQUE INDEX ix_records_record_uuid ON records_record (uuid);

CREATE TABLE records_type_revision (
    id SERIAL NOT NULL, 
    type_id INTEGER NOT NULL, 
    version INTEGER NOT NULL, 
    schema_version INTEGER NOT NULL, 
    fields JSON NOT NULL, 
    display_field VARCHAR(64), 
    slug_field VARCHAR(64), 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    created_by VARCHAR(255), 
    CONSTRAINT pk_records_type_revision PRIMARY KEY (id), 
    CONSTRAINT fk_records_type_revision_type_id_records_type FOREIGN KEY(type_id) REFERENCES records_type (id) ON DELETE CASCADE
);

CREATE INDEX ix_records_type_revision_type_version ON records_type_revision (type_id, version);

CREATE TABLE records_index_bool (
    id SERIAL NOT NULL, 
    type_id INTEGER NOT NULL, 
    field_key VARCHAR(64) NOT NULL, 
    record_id INTEGER NOT NULL, 
    value BOOLEAN NOT NULL, 
    CONSTRAINT pk_records_index_bool PRIMARY KEY (id), 
    CONSTRAINT fk_records_index_bool_record_id_records_record FOREIGN KEY(record_id) REFERENCES records_record (id) ON DELETE CASCADE
);

CREATE INDEX ix_records_index_bool_lookup ON records_index_bool (type_id, field_key, value);

CREATE INDEX ix_records_index_bool_record ON records_index_bool (record_id);

CREATE TABLE records_index_date (
    id SERIAL NOT NULL, 
    type_id INTEGER NOT NULL, 
    field_key VARCHAR(64) NOT NULL, 
    record_id INTEGER NOT NULL, 
    value DATE NOT NULL, 
    CONSTRAINT pk_records_index_date PRIMARY KEY (id), 
    CONSTRAINT fk_records_index_date_record_id_records_record FOREIGN KEY(record_id) REFERENCES records_record (id) ON DELETE CASCADE
);

CREATE INDEX ix_records_index_date_lookup ON records_index_date (type_id, field_key, value);

CREATE INDEX ix_records_index_date_record ON records_index_date (record_id);

CREATE TABLE records_index_datetime (
    id SERIAL NOT NULL, 
    type_id INTEGER NOT NULL, 
    field_key VARCHAR(64) NOT NULL, 
    record_id INTEGER NOT NULL, 
    value TIMESTAMP WITH TIME ZONE NOT NULL, 
    CONSTRAINT pk_records_index_datetime PRIMARY KEY (id), 
    CONSTRAINT fk_records_index_datetime_record_id_records_record FOREIGN KEY(record_id) REFERENCES records_record (id) ON DELETE CASCADE
);

CREATE INDEX ix_records_index_datetime_lookup ON records_index_datetime (type_id, field_key, value);

CREATE INDEX ix_records_index_datetime_record ON records_index_datetime (record_id);

CREATE TABLE records_index_number (
    id SERIAL NOT NULL, 
    type_id INTEGER NOT NULL, 
    field_key VARCHAR(64) NOT NULL, 
    record_id INTEGER NOT NULL, 
    value NUMERIC(19, 5) NOT NULL, 
    CONSTRAINT pk_records_index_number PRIMARY KEY (id), 
    CONSTRAINT fk_records_index_number_record_id_records_record FOREIGN KEY(record_id) REFERENCES records_record (id) ON DELETE CASCADE
);

CREATE INDEX ix_records_index_number_lookup ON records_index_number (type_id, field_key, value);

CREATE INDEX ix_records_index_number_record ON records_index_number (record_id);

CREATE TABLE records_index_ref (
    id SERIAL NOT NULL, 
    type_id INTEGER NOT NULL, 
    field_key VARCHAR(64) NOT NULL, 
    record_id INTEGER NOT NULL, 
    target_uuid VARCHAR(32) NOT NULL, 
    target_type_id INTEGER NOT NULL, 
    CONSTRAINT pk_records_index_ref PRIMARY KEY (id), 
    CONSTRAINT fk_records_index_ref_record_id_records_record FOREIGN KEY(record_id) REFERENCES records_record (id) ON DELETE CASCADE
);

CREATE INDEX ix_records_index_ref_lookup ON records_index_ref (type_id, field_key, target_uuid);

CREATE INDEX ix_records_index_ref_record ON records_index_ref (record_id);

CREATE INDEX ix_records_index_ref_target ON records_index_ref (target_uuid);

CREATE TABLE records_index_text (
    id SERIAL NOT NULL, 
    type_id INTEGER NOT NULL, 
    field_key VARCHAR(64) NOT NULL, 
    record_id INTEGER NOT NULL, 
    value VARCHAR(512) NOT NULL, 
    value_full TEXT, 
    CONSTRAINT pk_records_index_text PRIMARY KEY (id), 
    CONSTRAINT fk_records_index_text_record_id_records_record FOREIGN KEY(record_id) REFERENCES records_record (id) ON DELETE CASCADE
);

CREATE INDEX ix_records_index_text_lookup ON records_index_text (type_id, field_key, value);

CREATE INDEX ix_records_index_text_record ON records_index_text (record_id);

CREATE TYPE records_revision_event AS ENUM ('CREATE', 'UPDATE', 'DELETE', 'RESTORE');

CREATE TABLE records_revision (
    id SERIAL NOT NULL, 
    record_id INTEGER NOT NULL, 
    schema_version INTEGER NOT NULL, 
    version INTEGER NOT NULL, 
    data JSON NOT NULL, 
    display_title VARCHAR(300) NOT NULL, 
    event records_revision_event NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    created_by VARCHAR(255), 
    CONSTRAINT pk_records_revision PRIMARY KEY (id), 
    CONSTRAINT fk_records_revision_record_id_records_record FOREIGN KEY(record_id) REFERENCES records_record (id) ON DELETE CASCADE
);

CREATE INDEX ix_records_revision_record_id ON records_revision (record_id, id);

UPDATE alembic_version SET version_num='e23090832709' WHERE alembic_version.version_num = 'b1f4a72c9d30';

-- Running upgrade e23090832709 -> fccc111ff2e9

CREATE INDEX ix_records_record_type_created_id ON records_record (type_id, created_at, id);

CREATE INDEX ix_records_record_type_position_id ON records_record (type_id, position, id);

CREATE INDEX ix_records_record_type_published_id ON records_record (type_id, published_at, id);

CREATE INDEX ix_records_record_type_slug_id ON records_record (type_id, slug, id);

CREATE INDEX ix_records_record_type_title_id ON records_record (type_id, display_title, id);

CREATE INDEX ix_records_record_type_updated_id ON records_record (type_id, updated_at, id);

UPDATE alembic_version SET version_num='fccc111ff2e9' WHERE alembic_version.version_num = 'e23090832709';

-- Running upgrade fccc111ff2e9 -> a7c3e1d4b920

DROP INDEX ix_records_record_type_slug;

ALTER TABLE records_record ADD COLUMN locale VARCHAR(16) DEFAULT 'en' NOT NULL;

ALTER TABLE records_record ADD COLUMN translation_group VARCHAR(32);

UPDATE records_record SET translation_group=records_record.uuid;

ALTER TABLE records_record ALTER COLUMN locale DROP DEFAULT;

ALTER TABLE records_record ALTER COLUMN translation_group SET NOT NULL;

CREATE UNIQUE INDEX ix_records_record_type_slug ON records_record (type_id, locale, slug) WHERE slug IS NOT NULL;

CREATE INDEX ix_records_record_translation_group ON records_record (translation_group);

CREATE UNIQUE INDEX ix_records_record_group_locale ON records_record (translation_group, locale);

ALTER TABLE records_type ADD COLUMN translatable BOOLEAN DEFAULT false NOT NULL;

ALTER TABLE records_type ALTER COLUMN translatable DROP DEFAULT;

UPDATE alembic_version SET version_num='a7c3e1d4b920' WHERE alembic_version.version_num = 'fccc111ff2e9';

-- Running upgrade a7c3e1d4b920 -> 26bfe5e5f063

CREATE TABLE records_index_reduce (
    id SERIAL NOT NULL, 
    type_id INTEGER NOT NULL, 
    key VARCHAR(64) NOT NULL, 
    group_value VARCHAR(512) NOT NULL, 
    count INTEGER NOT NULL, 
    sum NUMERIC(19, 5), 
    updated_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    CONSTRAINT pk_records_index_reduce PRIMARY KEY (id)
);

CREATE INDEX ix_records_index_reduce_lookup ON records_index_reduce (type_id, key);

CREATE UNIQUE INDEX uq_records_index_reduce_group ON records_index_reduce (type_id, key, group_value);

UPDATE alembic_version SET version_num='26bfe5e5f063' WHERE alembic_version.version_num = 'a7c3e1d4b920';

-- Running upgrade 26bfe5e5f063 -> 5e2a32dccc22

ALTER TABLE records_type ADD COLUMN collection VARCHAR(32);

UPDATE alembic_version SET version_num='5e2a32dccc22' WHERE alembic_version.version_num = '26bfe5e5f063';

-- Running upgrade 5e2a32dccc22 -> 3b4733cf5444

CREATE TYPE records_c_events_record_status AS ENUM ('DRAFT', 'PUBLISHED');

CREATE TABLE records_c_events_record (
    is_deleted BOOLEAN NOT NULL, 
    deleted_at TIMESTAMP WITH TIME ZONE, 
    deleted_by VARCHAR(255), 
    created_at TIMESTAMP WITH TIME ZONE DEFAULT (CURRENT_TIMESTAMP) NOT NULL, 
    updated_at TIMESTAMP WITH TIME ZONE, 
    created_by VARCHAR(255), 
    updated_by VARCHAR(255), 
    id SERIAL NOT NULL, 
    uuid VARCHAR(32) NOT NULL, 
    type_id INTEGER NOT NULL, 
    data JSON NOT NULL, 
    schema_version INTEGER NOT NULL, 
    version INTEGER NOT NULL, 
    status records_c_events_record_status NOT NULL, 
    slug VARCHAR(200), 
    locale VARCHAR(16) NOT NULL, 
    translation_group VARCHAR(32) NOT NULL, 
    display_title VARCHAR(300) NOT NULL, 
    position INTEGER NOT NULL, 
    published_at TIMESTAMP WITH TIME ZONE, 
    CONSTRAINT pk_records_c_events_record PRIMARY KEY (id), 
    CONSTRAINT fk_records_c_events_record_type_id_records_type FOREIGN KEY(type_id) REFERENCES records_type (id) ON DELETE RESTRICT
);

CREATE UNIQUE INDEX ix_records_c_events_record_group_locale ON records_c_events_record (translation_group, locale);

CREATE INDEX ix_records_c_events_record_published_at ON records_c_events_record (published_at);

CREATE INDEX ix_records_c_events_record_status ON records_c_events_record (status);

CREATE INDEX ix_records_c_events_record_translation_group ON records_c_events_record (translation_group);

CREATE INDEX ix_records_c_events_record_type_created_id ON records_c_events_record (type_id, created_at, id);

CREATE INDEX ix_records_c_events_record_type_id ON records_c_events_record (type_id);

CREATE INDEX ix_records_c_events_record_type_position_id ON records_c_events_record (type_id, position, id);

CREATE INDEX ix_records_c_events_record_type_published_id ON records_c_events_record (type_id, published_at, id);

CREATE UNIQUE INDEX ix_records_c_events_record_type_slug ON records_c_events_record (type_id, locale, slug) WHERE slug IS NOT NULL;

CREATE INDEX ix_records_c_events_record_type_slug_id ON records_c_events_record (type_id, slug, id);

CREATE INDEX ix_records_c_events_record_type_status_position ON records_c_events_record (type_id, status, position);

CREATE INDEX ix_records_c_events_record_type_title_id ON records_c_events_record (type_id, display_title, id);

CREATE INDEX ix_records_c_events_record_type_updated_id ON records_c_events_record (type_id, updated_at, id);

CREATE UNIQUE INDEX ix_records_c_events_record_uuid ON records_c_events_record (uuid);

CREATE TABLE records_c_events_index_bool (
    id SERIAL NOT NULL, 
    type_id INTEGER NOT NULL, 
    field_key VARCHAR(64) NOT NULL, 
    record_id INTEGER NOT NULL, 
    value BOOLEAN NOT NULL, 
    CONSTRAINT pk_records_c_events_index_bool PRIMARY KEY (id), 
    CONSTRAINT fk_records_c_events_index_bool_record_id_records_c_even_aafa FOREIGN KEY(record_id) REFERENCES records_c_events_record (id) ON DELETE CASCADE
);

CREATE INDEX ix_records_c_events_index_bool_lookup ON records_c_events_index_bool (type_id, field_key, value);

CREATE INDEX ix_records_c_events_index_bool_record ON records_c_events_index_bool (record_id);

CREATE TABLE records_c_events_index_date (
    id SERIAL NOT NULL, 
    type_id INTEGER NOT NULL, 
    field_key VARCHAR(64) NOT NULL, 
    record_id INTEGER NOT NULL, 
    value DATE NOT NULL, 
    CONSTRAINT pk_records_c_events_index_date PRIMARY KEY (id), 
    CONSTRAINT fk_records_c_events_index_date_record_id_records_c_even_2956 FOREIGN KEY(record_id) REFERENCES records_c_events_record (id) ON DELETE CASCADE
);

CREATE INDEX ix_records_c_events_index_date_lookup ON records_c_events_index_date (type_id, field_key, value);

CREATE INDEX ix_records_c_events_index_date_record ON records_c_events_index_date (record_id);

CREATE TABLE records_c_events_index_datetime (
    id SERIAL NOT NULL, 
    type_id INTEGER NOT NULL, 
    field_key VARCHAR(64) NOT NULL, 
    record_id INTEGER NOT NULL, 
    value TIMESTAMP WITH TIME ZONE NOT NULL, 
    CONSTRAINT pk_records_c_events_index_datetime PRIMARY KEY (id), 
    CONSTRAINT fk_records_c_events_index_datetime_record_id_records_c__3c04 FOREIGN KEY(record_id) REFERENCES records_c_events_record (id) ON DELETE CASCADE
);

CREATE INDEX ix_records_c_events_index_datetime_lookup ON records_c_events_index_datetime (type_id, field_key, value);

CREATE INDEX ix_records_c_events_index_datetime_record ON records_c_events_index_datetime (record_id);

CREATE TABLE records_c_events_index_number (
    id SERIAL NOT NULL, 
    type_id INTEGER NOT NULL, 
    field_key VARCHAR(64) NOT NULL, 
    record_id INTEGER NOT NULL, 
    value NUMERIC(19, 5) NOT NULL, 
    CONSTRAINT pk_records_c_events_index_number PRIMARY KEY (id), 
    CONSTRAINT fk_records_c_events_index_number_record_id_records_c_ev_af0b FOREIGN KEY(record_id) REFERENCES records_c_events_record (id) ON DELETE CASCADE
);

CREATE INDEX ix_records_c_events_index_number_lookup ON records_c_events_index_number (type_id, field_key, value);

CREATE INDEX ix_records_c_events_index_number_record ON records_c_events_index_number (record_id);

CREATE TABLE records_c_events_index_ref (
    id SERIAL NOT NULL, 
    type_id INTEGER NOT NULL, 
    field_key VARCHAR(64) NOT NULL, 
    record_id INTEGER NOT NULL, 
    target_uuid VARCHAR(32) NOT NULL, 
    target_type_id INTEGER NOT NULL, 
    CONSTRAINT pk_records_c_events_index_ref PRIMARY KEY (id), 
    CONSTRAINT fk_records_c_events_index_ref_record_id_records_c_events_record FOREIGN KEY(record_id) REFERENCES records_c_events_record (id) ON DELETE CASCADE
);

CREATE INDEX ix_records_c_events_index_ref_lookup ON records_c_events_index_ref (type_id, field_key, target_uuid);

CREATE INDEX ix_records_c_events_index_ref_record ON records_c_events_index_ref (record_id);

CREATE INDEX ix_records_c_events_index_ref_target ON records_c_events_index_ref (target_uuid);

CREATE TABLE records_c_events_index_text (
    id SERIAL NOT NULL, 
    type_id INTEGER NOT NULL, 
    field_key VARCHAR(64) NOT NULL, 
    record_id INTEGER NOT NULL, 
    value VARCHAR(512) NOT NULL, 
    value_full TEXT, 
    CONSTRAINT pk_records_c_events_index_text PRIMARY KEY (id), 
    CONSTRAINT fk_records_c_events_index_text_record_id_records_c_even_9f4c FOREIGN KEY(record_id) REFERENCES records_c_events_record (id) ON DELETE CASCADE
);

CREATE INDEX ix_records_c_events_index_text_lookup ON records_c_events_index_text (type_id, field_key, value);

CREATE INDEX ix_records_c_events_index_text_record ON records_c_events_index_text (record_id);

CREATE TYPE records_c_events_revision_event AS ENUM ('CREATE', 'UPDATE', 'DELETE', 'RESTORE');

CREATE TABLE records_c_events_revision (
    id SERIAL NOT NULL, 
    record_id INTEGER NOT NULL, 
    schema_version INTEGER NOT NULL, 
    version INTEGER NOT NULL, 
    data JSON NOT NULL, 
    display_title VARCHAR(300) NOT NULL, 
    event records_c_events_revision_event NOT NULL, 
    created_at TIMESTAMP WITH TIME ZONE NOT NULL, 
    created_by VARCHAR(255), 
    CONSTRAINT pk_records_c_events_revision PRIMARY KEY (id), 
    CONSTRAINT fk_records_c_events_revision_record_id_records_c_events_record FOREIGN KEY(record_id) REFERENCES records_c_events_record (id) ON DELETE CASCADE
);

CREATE INDEX ix_records_c_events_revision_record_id ON records_c_events_revision (record_id, id);

UPDATE alembic_version SET version_num='3b4733cf5444' WHERE alembic_version.version_num = '5e2a32dccc22';

-- Running upgrade 3b4733cf5444 -> fe3ea2dfe0fb

DROP INDEX ix_records_record_group_locale;

CREATE UNIQUE INDEX ix_records_record_group_locale ON records_record (type_id, translation_group, locale);

DROP INDEX ix_records_c_events_record_group_locale;

CREATE UNIQUE INDEX ix_records_c_events_record_group_locale ON records_c_events_record (type_id, translation_group, locale);

UPDATE alembic_version SET version_num='fe3ea2dfe0fb' WHERE alembic_version.version_num = '3b4733cf5444';

-- Running upgrade fe3ea2dfe0fb -> c4a17b9de0f2

CREATE INDEX ix_records_record_type_published_desc ON records_record (type_id, published_at DESC NULLS LAST, id DESC);

CREATE INDEX ix_records_record_type_slug_desc ON records_record (type_id, slug DESC NULLS LAST, id DESC);

CREATE INDEX ix_records_record_type_updated_desc ON records_record (type_id, updated_at DESC NULLS LAST, id DESC);

CREATE INDEX ix_records_c_events_record_type_published_desc ON records_c_events_record (type_id, published_at DESC NULLS LAST, id DESC);

CREATE INDEX ix_records_c_events_record_type_slug_desc ON records_c_events_record (type_id, slug DESC NULLS LAST, id DESC);

CREATE INDEX ix_records_c_events_record_type_updated_desc ON records_c_events_record (type_id, updated_at DESC NULLS LAST, id DESC);

UPDATE alembic_version SET version_num='c4a17b9de0f2' WHERE alembic_version.version_num = 'fe3ea2dfe0fb';

-- Running upgrade c4a17b9de0f2 -> b81c5f3a27d6

ALTER TABLE records_type ADD COLUMN show_in_menu BOOLEAN DEFAULT false NOT NULL;

UPDATE alembic_version SET version_num='b81c5f3a27d6' WHERE alembic_version.version_num = 'c4a17b9de0f2';

-- Running upgrade b81c5f3a27d6 -> d2b7a1c4e905

CREATE INDEX ix_users_user_email_lower ON users_user (lower(email));

UPDATE alembic_version SET version_num='d2b7a1c4e905' WHERE alembic_version.version_num = 'b81c5f3a27d6';

COMMIT;

