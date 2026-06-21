#!/usr/bin/bash
#
#     (C) COPYRIGHT 2026   Al von Ruff
#         ALL RIGHTS RESERVED
#
#     The copyright notice above does not evidence any actual or
#     intended publication of such source code.

set -x

# Set this variable to 'Y', if you want the script to create the final isfdb.db file.
# It defaults to 'N' as the gzip .sql file is much smaller the a gzip .db file

MAKE_DB='N'

#
# Remove old tmp files and isfdb.db, otherwise sqlite3 will ADD content to the db
#
rm -f fixed.sql
rm -f isfdb_sqlite.sql

#
# Extract the backup from the zip file
#
/usr/bin/unzip $1
TARGET=$(basename $1 .zip)
mv cygdrive/c/ISFDB/Backups/$TARGET .
rm -rf cygdrive

#
# Convert ISO-8859-1 to UTF-8
#
python3 fix_ampersands.py $TARGET

#
# Convert MySQL to SQLite
#
./mysql2sqlite.py fixed.sql  isfdb_sqlite.sql

if [[ "$MAKE_DB" == "Y" ]]; then
	rm -f isfdb.db
	sqlite3 isfdb.db < isfdb_sqlite.sql
else
	rm -f isfdb_sqlite.sql.gz
	gzip isfdb_sqlite.sql
fi

rm -f fixed.sql
rm -f $TARGET


