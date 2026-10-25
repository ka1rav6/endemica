import psycopg

conn = psycopg.connect(
    "postgresql://endemica:endemica@localhost:55433/endemica", connect_timeout=4
)
cur = conn.cursor()
for table in ("countries", "outbreak_reports", "outbreak_observations", "country_flows"):
    cur.execute(f"select count(*) from {table}")
    print(table, cur.fetchone()[0])
cur.execute(
    """
    select disease_label, pathogen_key, count(*)
    from outbreak_reports
    group by 1, 2
    order by 3 desc
    limit 25
    """
)
print("--- diseases ---")
for row in cur.fetchall():
    print(row)
cur.execute(
    """
    select grounding_status, count(*)
    from outbreak_observations
    group by 1
    """
)
print("--- grounding ---")
for row in cur.fetchall():
    print(row)
