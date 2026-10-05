"""
Loads data.csv into SQLite, runs repeat_purchase_analysis.sql and writes
sql_output.txt (a copy of every query's result).

Usage: python run_sql_sqlite.py --data data.csv --sql repeat_purchase_analysis.sql
"""
import argparse
import sqlite3

import pandas as pd

parser = argparse.ArgumentParser()
parser.add_argument("--data", default="data.csv")
parser.add_argument("--sql", default="repeat_purchase_analysis.sql")
parser.add_argument("--out", default="sql_output.txt")
args = parser.parse_args()

con = sqlite3.connect(":memory:")
pd.read_csv(args.data, dtype={"InvoiceDate": str}).to_sql("transactions", con, index=False)

lines_out = ["SQL OUTPUT - repeat_purchase_analysis.sql (SQLite %s)" % sqlite3.sqlite_version,
             "Data: %s (%d rows)\n" % (args.data, con.execute("SELECT COUNT(*) FROM transactions").fetchone()[0])]
buf = ""
for line in open(args.sql):
    buf += line
    if sqlite3.complete_statement(buf):
        stmt = buf.strip()
        buf = ""
        title = next((l[3:].strip() for l in stmt.splitlines() if l.startswith("-- [Q")), None)
        if stmt.lstrip().upper().startswith("SELECT") or title:
            df = pd.read_sql(stmt, con)
            lines_out.append("=" * 70)
            lines_out.append(title or "result")
            lines_out.append("=" * 70)
            lines_out.append(df.to_string(index=False))
            lines_out.append("(%d rows)\n" % len(df))
        else:
            con.executescript(stmt)

text = "\n".join(lines_out)
open(args.out, "w").write(text)
print(text)
