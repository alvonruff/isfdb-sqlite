#!/usr/bin/env python3

#
#     (C) COPYRIGHT 2026   Al von Ruff
#         ALL RIGHTS RESERVED
#
#     The copyright notice above does not evidence any actual or
#     intended publication of such source code.


"""
mysql2sqlite.py - Convert a mysqldump file to SQLite3-compatible SQL.

Usage:
    python3 mysql2sqlite.py input.sql output.sql
    python3 mysql2sqlite.py input.sql.gz output.sql   # handles gzip too
"""

import re
import sys
import gzip
import io


# ---------------------------------------------------------------------------
# Type / clause rewriting rules applied inside CREATE TABLE bodies
# ---------------------------------------------------------------------------

# Order matters: more-specific patterns first.
TYPE_REPLACEMENTS = [
    # Exact numeric types with display widths → INTEGER
    (re.compile(r'\b(TINYINT|SMALLINT|MEDIUMINT|BIGINT|INT)\s*\(\s*\d+\s*\)\s*(?:UNSIGNED\s*)?(?:ZEROFILL\s*)?', re.I), 'INTEGER '),
    (re.compile(r'\bINT\b\s*(?:UNSIGNED\s*)?(?:ZEROFILL\s*)?', re.I), 'INTEGER '),
    # FLOAT / DOUBLE / DECIMAL → REAL
    (re.compile(r'\b(FLOAT|DOUBLE(?:\s+PRECISION)?|DECIMAL|NUMERIC)\s*(?:\(\s*\d+\s*(?:,\s*\d+\s*)?\))?\s*(?:UNSIGNED\s*)?', re.I), 'REAL '),
    # String types → TEXT
    (re.compile(r'\b(TINYTEXT|MEDIUMTEXT|LONGTEXT|TEXT)\b', re.I), 'TEXT'),
    (re.compile(r'\b(VARCHAR|NVARCHAR|CHAR|NCHAR)\s*\(\s*\d+\s*\)', re.I), 'TEXT'),
    (re.compile(r'\bBINARY\s*\(\s*\d+\s*\)', re.I), 'BLOB'),
    (re.compile(r'\bVARBINARY\s*\(\s*\d+\s*\)', re.I), 'BLOB'),
    # Date/time → TEXT (SQLite stores these as text anyway)
    (re.compile(r'\b(DATETIME|TIMESTAMP|DATE|TIME|YEAR)\b', re.I), 'TEXT'),
    # Blob types
    (re.compile(r'\b(TINYBLOB|MEDIUMBLOB|LONGBLOB|BLOB)\b', re.I), 'BLOB'),
    # ENUM / SET → TEXT
    (re.compile(r"\bENUM\s*\([^)]+\)", re.I), 'TEXT'),
    (re.compile(r"\bSET\s*\([^)]+\)", re.I), 'TEXT'),
    # Strip AUTO_INCREMENT — SQLite INTEGER PRIMARY KEY is implicitly auto-incrementing
    (re.compile(r'\bAUTO_INCREMENT\b', re.I), ''),
    # Remove leftover UNSIGNED / ZEROFILL / CHARACTER SET / COLLATE clauses
    (re.compile(r'\bUNSIGNED\b', re.I), ''),
    (re.compile(r'\bZEROFILL\b', re.I), ''),
    (re.compile(r'\bCHARACTER\s+SET\s+\S+', re.I), ''),
    (re.compile(r'\bCHARSET\s+\S+', re.I), ''),
    (re.compile(r'\bCOLLATE\s+\S+', re.I), ''),
]

# Lines inside CREATE TABLE to drop entirely
# Lines inside CREATE TABLE that have no SQLite equivalent and must be dropped
SKIP_LINE_RE = re.compile(
    r'^\s*('
    r'FULLTEXT\s+(KEY|INDEX)\b'   # full-text index — no SQLite equivalent
    r'|SPATIAL\s+(KEY|INDEX)\b'   # spatial index  — no SQLite equivalent
    r'|PRIMARY\s+KEY\s*\('        # stand-alone PRIMARY KEY line (kept separately)
    r')',
    re.I
)

# KEY / INDEX lines we want to convert to CREATE INDEX statements
INDEX_LINE_RE = re.compile(
    r'^\s*(UNIQUE\s+)?(?:KEY|INDEX)\s+'        # optional UNIQUE, then KEY or INDEX
    r'(`[^`]+`|"[^"]+"|\'[^\']+\'|\w+)'        # index name (quoted or bare)
    r'\s*\(((?:[^()]+|\([^()]*\))*)\)',         # column list, tolerating col(N) prefix lengths
    re.I
)

# Stand-alone PRIMARY KEY line that we want to rewrite as a constraint
STANDALONE_PK_RE = re.compile(r'^\s*PRIMARY\s+KEY\s*\(([^)]+)\)', re.I)

# Table-level options after the closing ) of CREATE TABLE
TABLE_OPTIONS_RE = re.compile(
    r'\)\s*'
    r'(?:ENGINE\s*=\s*\S+\s*)?'
    r'(?:AUTO_INCREMENT\s*=\s*\d+\s*)?'
    r'(?:DEFAULT\s+CHARSET\s*=\s*\S+\s*)?'
    r'(?:CHARSET\s*=\s*\S+\s*)?'
    r'(?:COLLATE\s*=\s*\S+\s*)?'
    r'(?:ROW_FORMAT\s*=\s*\S+\s*)?'
    r'(?:COMMENT\s*=\s*\'[^\']*\'\s*)?'
    r'(?:PACK_KEYS\s*=\s*\S+\s*)?'
    r'(?:MAX_ROWS\s*=\s*\d+\s*)?'
    r'(?:MIN_ROWS\s*=\s*\d+\s*)?'
    r'(?:AVG_ROW_LENGTH\s*=\s*\d+\s*)?'
    r';',
    re.I
)


def rewrite_create_table(block: str):
    """Rewrite a single CREATE TABLE ... ; block for SQLite compatibility.

    Returns (create_sql, index_statements) where index_statements is a list
    of ready-to-emit CREATE INDEX ... ; strings for this table.
    """
    lines = block.splitlines()
    out_lines = []
    last_kept = None
    table_name = None
    index_stmts = []

    for line in lines:
        stripped = line.strip()

        # Keep the CREATE TABLE header line; capture table name for indexes
        ct_match = re.match(r'^\s*CREATE\s+TABLE\s+(\S+)', line, re.I)
        if ct_match:
            table_name = ct_match.group(1)
            if not re.search(r'IF\s+NOT\s+EXISTS', line, re.I):
                line = re.sub(r'(CREATE\s+TABLE\s+)', r'\1IF NOT EXISTS ', line, flags=re.I)
            out_lines.append(line)
            continue

        # Closing line: strip MySQL table options, keep just ');'
        if re.match(r'^\s*\)', stripped):
            if last_kept is not None:
                out_lines[last_kept] = out_lines[last_kept].rstrip().rstrip(',')
            out_lines.append(');')
            continue

        # Drop unsupported lines (FULLTEXT, SPATIAL, stand-alone PRIMARY KEY header)
        if SKIP_LINE_RE.match(stripped):
            continue

        # Convert KEY / INDEX lines into deferred CREATE INDEX statements
        idx_match = INDEX_LINE_RE.match(stripped)
        if idx_match:
            unique    = 'UNIQUE ' if idx_match.group(1) else ''
            idx_name  = idx_match.group(2)
            # Strip prefix lengths from column list: `col`(255) or col(10) → col
            cols_raw  = idx_match.group(3)
            cols      = re.sub(r'(`[^`]+`|\'[^\']+\'|"[^"]+"|\w+)\s*\(\d+\)', r'\1', cols_raw)
            # MySQL index names are scoped per-table; SQLite requires globally unique names.
            # Prefix with the table name to avoid cross-table collisions.
            clean_table = table_name.strip('`"\'')
            clean_idx   = idx_name.strip('`"\'')
            scoped_name = f'`{clean_table}_{clean_idx}`'
            index_stmts.append(
                f'CREATE {unique}INDEX IF NOT EXISTS {scoped_name} '
                f'ON {table_name} ({cols});'
            )
            continue

        # Keep PRIMARY KEY as inline constraint
        pk_match = STANDALONE_PK_RE.match(stripped)
        if pk_match:
            cols = pk_match.group(1)
            out_lines.append(f'  PRIMARY KEY ({cols}),')
            last_kept = len(out_lines) - 1
            continue

        # Apply type rewrites to column definition lines.
        # Protect the column name (first identifier on the line) so that keywords
        # used as column names (e.g. `year`, `timestamp`) are not rewritten.
        col_name_m = re.match(r'^(\s*(?:`[^`]+`|"[^"]+"|\'[^\']+\'|\w+)\s+)(.*)', line, re.S)
        if col_name_m:
            col_prefix = col_name_m.group(1)
            rest = col_name_m.group(2)
            for pattern, replacement in TYPE_REPLACEMENTS:
                rest = pattern.sub(replacement, rest)
            rest = re.sub(r'  +', ' ', rest)
            rewritten = col_prefix + rest
        else:
            rewritten = line
            for pattern, replacement in TYPE_REPLACEMENTS:
                rewritten = pattern.sub(replacement, rewritten)
            rewritten = re.sub(r'  +', ' ', rewritten)

        out_lines.append(rewritten)
        last_kept = len(out_lines) - 1

    return '\n'.join(out_lines), index_stmts


def fix_mysql_escapes(line: str) -> str:
    r"""Convert MySQL string escape sequences to SQLite equivalents.

    MySQL escape rules inside single-quoted strings:
      \\  -> \ (literal backslash — no escaping needed in SQLite)
      \'  -> '' (SQLite uses doubled quotes, not backslash)
      \n  -> newline, \r -> CR, \t -> tab  (keep as literal chars)
      \0  -> NUL char

    The naive replace("\'", "''") breaks on  \\\\'  (backslash at end of
    string) because it matches the \' at the tail first.
    """
    result = []
    i = 0
    in_str = False

    while i < len(line):
        c = line[i]
        if not in_str:
            result.append(c)
            if c == "'":
                in_str = True
            i += 1
        else:
            if c == '\\' and i + 1 < len(line):
                nxt = line[i + 1]
                if nxt == '\\':
                    result.append('\\')   # \\ → single backslash
                elif nxt == "'":
                    result.append("''")   # \' → ''
                elif nxt == 'n':
                    result.append('\n')
                elif nxt == 'r':
                    result.append('\r')
                elif nxt == 't':
                    result.append('\t')
                elif nxt == '0':
                    result.append('\x00')
                else:
                    result.append(nxt)    # any other \X → X
                i += 2
            elif c == "'":
                result.append("'")
                in_str = False
                i += 1
            else:
                result.append(c)
                i += 1

    return ''.join(result)


def open_input(path: str):
    if path.endswith('.gz'):
        return gzip.open(path, 'rt', errors='replace')
    return open(path, 'r', errors='replace')

def convert(in_path: str, out_path: str) -> None:
    # Patterns for lines/blocks to suppress entirely
    suppress_line_re = re.compile(
        r'^\s*('
        r'SET\s+'                          # SET NAMES, SET @@, etc.
        r'|LOCK\s+TABLES\b'
        r'|UNLOCK\s+TABLES\b'
        r'|ALTER\s+TABLE\s+\S+\s+(DISABLE|ENABLE)\s+KEYS\b'
        r'|DROP\s+TABLE\b'                 # optional: comment out to keep
        r'|\/\*![0-9]+ .*?\*\/;'          # conditional MySQL comments on own line
        r'|-- .*'                          # SQL comments (keep structure comments if you want)
        r'|/\*.*\*/'                       # inline block comments
        r')',
        re.I
    )

    # Tables to exclude entirely (no CREATE TABLE, no INSERT INTO).
    # Names are unquoted and matched case-insensitively.
    EXCLUDED_TABLES = {'author_views', 
			'bad_images', 
			'changed_verified_pubs', 
			'cleanup', 
			'deleted_secondary_verifications', 
			'front_page_pubs', 
			'history', 
			'license_keys', 
			'reports', 
			'submissions', 
			'self_approvers', 
			'sfe3_authors',
			'tag_status_log', 
			'title_views', 
			'user_languages', 
			'user_preferences', 
			'user_status', 
			'websites', 
			'web_api_users' }

    def is_excluded(table_name: str) -> bool:
        name = table_name.strip('`\'"')
        return name.lower().startswith('mw_') or name.lower() in EXCLUDED_TABLES

    # Regex to extract the table name from CREATE TABLE or INSERT INTO lines
    create_table_re = re.compile(r'^\s*CREATE\s+TABLE\s+(\S+)', re.I)
    insert_into_re  = re.compile(r'^\s*INSERT\s+(?:OR\s+\w+\s+)?INTO\s+(\S+)', re.I)

    with open_input(in_path) as fin, open(out_path, 'w', encoding='utf-8') as fout:
        fout.write('PRAGMA foreign_keys=OFF;\nBEGIN TRANSACTION;\n\n')

        buffer = []
        in_create = False
        skip_create = False   # True while accumulating a block for an excluded table

        for raw_line in fin:
            line = raw_line.rstrip('\n')

            # Strip MySQL conditional comments: /*!40101 ... */ → keep content
            line = re.sub(r'/\*!\d+\s*(.*?)\s*\*/', r'\1', line)
            # Remove standalone /*! ... */ that become empty after above
            line = re.sub(r'/\*\s*\*/', '', line)

            stripped = line.strip()

            # Skip blank lines and suppressed patterns
            if not stripped:
                continue
            if suppress_line_re.match(stripped):
                continue
            # Drop MySQL-only ALTER TABLE key-management statements
            if re.search(r'\b(DISABLE|ENABLE)\s+KEYS\b', stripped, re.I):
                continue

            # Accumulate CREATE TABLE blocks
            ct_match = create_table_re.match(line)
            if ct_match:
                in_create = True
                skip_create = is_excluded(ct_match.group(1))
                buffer = [line]
                continue

            if in_create:
                buffer.append(line)
                if stripped.endswith(';') or re.match(r'^\s*\)\s*[^;]*;', stripped):
                    if not skip_create:
                        block = '\n'.join(buffer)
                        create_sql, index_stmts = rewrite_create_table(block)
                        fout.write(create_sql + '\n\n')
                        for stmt in index_stmts:
                            fout.write(stmt + '\n')
                        if index_stmts:
                            fout.write('\n')
                    buffer = []
                    in_create = False
                    skip_create = False
                continue

            # Skip INSERT INTO for excluded tables
            ins_match = insert_into_re.match(stripped)
            if ins_match and is_excluded(ins_match.group(1)):
                continue

            # Pass INSERT / other DML through with minor fixes
            # MySQL uses backtick-quoted identifiers; SQLite accepts them too.
            line = fix_mysql_escapes(line)
            # Remove MySQL-specific INSERT LOW_PRIORITY / DELAYED hints
            line = re.sub(r'\bINSERT\s+(LOW_PRIORITY|DELAYED|HIGH_PRIORITY|IGNORE)\s+INTO\b',
                          'INSERT OR IGNORE INTO', line, flags=re.I)

            fout.write(line + '\n')

        fout.write('\nCREATE TABLE dual (dummy CHAR(1));\n')
        fout.write('INSERT INTO dual VALUES (\'X\');\n')
        fout.write('\nCOMMIT;\n')
        fout.write('CREATE INDEX IF NOT EXISTS idx_ca_author_status ON canonical_author (author_id, ca_status);\n')
        fout.write('CREATE INDEX IF NOT EXISTS idx_ca_title_status  ON canonical_author (title_id,  ca_status);\n')
        fout.write('CREATE INDEX IF NOT EXISTS idx_titles_id  ON titles  (title_id);\n')
        fout.write('CREATE INDEX IF NOT EXISTS idx_authors_id ON authors (author_id);\n')
        fout.write('CREATE INDEX IF NOT EXISTS idx_series_id  ON series  (series_id);\n')
        fout.write('ANALYZE;\n')

    print(f'Done. Written to {out_path}')


def main():
    if len(sys.argv) != 3:
        print(f'Usage: {sys.argv[0]} <input.sql[.gz]> <output.sql>')
        sys.exit(1)
    convert(sys.argv[1], sys.argv[2])


if __name__ == '__main__':
    main()
