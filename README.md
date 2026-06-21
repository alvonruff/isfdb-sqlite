
The code here translates an ISFDB MySQL backup to an SQLite backup.

The motivation is associated with a desktop version of the ISFDB (isfdb-go), which uses
go's built-in web server (removing need for a complex install / config of Apache)
as well as go's support for SQLite (removing the need for a complex install / config 
of MySQL, and the associated mysql.connector)

Sqlite uses UTF encodings, so the data is also converted from ISO-8859-1 to UTF-8.
The associated code is pretty trivial, as most of the ISO-8859-1 support is in the
code base for the ISFDB. This could theoretically work with any MySQL dump, but it
has only been tested on ISFDB data.

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

