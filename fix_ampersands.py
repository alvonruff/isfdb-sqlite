#
#     (C) COPYRIGHT 2026   Al von Ruff
#         ALL RIGHTS RESERVED
#
#     The copyright notice above does not evidence any actual or
#     intended publication of such source code.

import sys
import html

# This code handles conversion from ISO-8859-1 to UTF-8

if __name__ == '__main__':

        try:
                path = sys.argv[1]
        except:
                print("Usage: fix_ampersands.py <inputFile>")
                sys.exit(0)

        with open(path, 'r', encoding='utf-8') as fin, \
             open('fixed.sql', 'w', encoding='utf-8') as fout:
                for line in fin:
                        line = line.replace('&apos;', "''")
                        line = line.replace('&#x27;', "''")
                        line = line.replace('&#39;', "''")
                        fout.write(html.unescape(line))
