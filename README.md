
The code here translates an ISFDB MySQL backup to an SQLite backup.

# Motivation

The motivation is associated with a desktop version of the ISFDB (isfdb-go), which uses
go's built-in web server (removing need for a complex install / config of Apache)
as well as go's support for SQLite (removing the need for a complex install / config 
of MySQL, and the associated mysql.connector)

# Alterations

Sqlite uses UTF encodings, so the data is also converted from ISO-8859-1 to UTF-8.
The associated code is pretty trivial, as most of the ISO-8859-1 support is in the
code base for the ISFDB. This could theoretically work with any MySQL dump, but it
has only been tested on ISFDB data.

In order to address sqlite performance issues, the conversion process adds some additional 
indexes that are not present in the ISFDB MySQL version:

    CREATE INDEX IF NOT EXISTS idx_ca_author_status ON canonical_author (author_id, ca_status);
    CREATE INDEX IF NOT EXISTS idx_ca_title_status  ON canonical_author (title_id,  ca_status);
    CREATE INDEX IF NOT EXISTS idx_titles_id  ON titles  (title_id);
    CREATE INDEX IF NOT EXISTS idx_authors_id ON authors (author_id);
    CREATE INDEX IF NOT EXISTS idx_series_id  ON series  (series_id);

Additionally, since the desktop version of the ISFDB does not support editing or database management,
all wiki-related tables (mw_*) have been removed, as well as the following tables (controlled by the 
EXCLUDED_TABLES variable):

* author_views
* bad_images
* changed_verified_pubs
* cleanup
* deleted_secondary_verifications
* front_page_pubs
* history
* license_keys 
* reports
* submissions
* self_approvers
* sfe3_authors
* tag_status_log
* title_views
* user_languages
* user_preferences 
* user_status
* websites
* web_api_users

If you wish to retain these tables, a simple alteration of the is_excluded() function is in order.

# Operation

You need to do a download and extraction of the ISFDB daily backup, from: 

        https://www.isfdb.org/wiki/index.php/ISFDB_Downloads

Pick the latest release from the section Database Backups. You then perform the conversion with:

	./convert.sh <BACKUP_FILE>

Example:

	./convert.sh backup-MySQL-55-2026-06-13.zip

There are three files here:

* convert.sh        - The high-level bash script
* fix_ampersands.py - Converts the MySQL dump to UTF-8
* mysql2sqlite.py   - Converts from MySQL to SQLite.

The process will either generate a compressed sqlite3 dump (isfdb_sqlite.sql.gz) or 
an sqlite3 database (isfdb.db). This action is controlled by the shell variable MAKE_DB
in convert.sh. If set to 'Y' the isfdb.db file is created; if set to 'N' the backup file is 
created. The backup file is much smaller than the compressed version of isfdb.db, taking up
far less cloud storage.

