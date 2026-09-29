"""
Historical Data Ingestion & Indexing ETL for MPLADS Platform.
Reads raw CSV files without modifying them and builds an indexed SQLite read layer.
"""
import os
import re
import sqlite3
import pandas as pd
import numpy as np

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "data")
PROJ_CSV = os.path.join(DATA_DIR, "all_states_projects.csv")
PAY_CSV = os.path.join(DATA_DIR, "all_states_payment_events.csv")
HISTORICAL_DB = os.path.join(DATA_DIR, "mplads_historical.db")


def extract_district(ida_str: str) -> str:
    """Extracts a clean district name from the IDA string."""
    if not isinstance(ida_str, str):
        return "Unknown"
    m = re.match(r"^([^(]+)", ida_str)
    if m:
        name = m.group(1).strip()
        # Title case clean
        return name.title()
    return ida_str.strip().title()


def reconstruct_project_row(row):
    wid = str(row['work_id'])
    wtitle = str(row['work_title'])
    if '\t' in wid or ' ' in wid:
        # Check if title has the prefix pattern 'YYYY/SERIAL-Title'
        m = re.match(r"^(\d+)/(\d+)-(.*)$", wtitle)
        if m:
            clean_wid = wid.replace('\t ', '').replace('\t', '').replace(' ', '').strip()
            # clean_wid is like "WS/MP319/2024"
            full_wid = f"{clean_wid}-{m.group(1)}/{m.group(2)}"
            cleaned_title = m.group(3).strip()
            return full_wid, cleaned_title
        else:
            clean_wid = wid.replace('\t ', '').replace('\t', '').replace(' ', '').strip()
            return clean_wid, wtitle
    return wid.strip(), wtitle.strip()


def run_etl():
    print(f"[ETL] Reading historical projects from {PROJ_CSV}...")
    df_p = pd.read_csv(PROJ_CSV, low_memory=False)
    print(f"[ETL] Read {len(df_p)} project rows.")

    print(f"[ETL] Reading historical payments from {PAY_CSV}...")
    df_e = pd.read_csv(PAY_CSV, low_memory=False)
    print(f"[ETL] Read {len(df_e)} payment event rows.")

    # Reconstruct project IDs and clean titles where mangled
    print("[ETL] Reconstructing project IDs and normalizing strings...")
    reconstructed_data = [reconstruct_project_row(row) for _, row in df_p.iterrows()]
    df_p['work_id'] = [item[0] for item in reconstructed_data]
    df_p['work_title'] = [item[1] for item in reconstructed_data]

    # Clean district from IDA
    df_p['district'] = df_p['ida'].apply(extract_district)

    # Clean payments work_id
    df_e['work_id'] = df_e['work_id'].astype(str).str.replace('WS/ ', 'WS/', regex=False).str.replace('\t', '', regex=False).str.strip()
    df_e['district'] = df_e['ida'].apply(extract_district)

    print(f"[ETL] Distinct projects after reconstruction: {df_p['work_id'].nunique()}")
    print(f"[ETL] Distinct payment projects after cleaning: {df_e['work_id'].nunique()}")

    # Aggregating payments summary per work_id
    print("[ETL] Pre-aggregating payment metrics per project...")
    pay_summary = df_e.groupby('work_id').agg(
        total_disbursed=('reported_fund_disbursed_amount', 'sum'),
        payment_events_count=('source_serial_number', 'count'),
        last_payment_date=('expenditure_date', 'max'),
        first_payment_date=('expenditure_date', 'min'),
        primary_vendor=('vendor_name_normalized', lambda s: s.iloc[0] if len(s) > 0 else 'Unknown')
    ).reset_index()

    # Merge aggregated payments into projects
    df_p = pd.merge(df_p, pay_summary, on='work_id', how='left')
    df_p['total_disbursed'] = df_p['total_disbursed'].fillna(0.0)
    df_p['payment_events_count'] = df_p['payment_events_count'].fillna(0).astype(int)

    # Remove temporary DB if exists to start fresh
    if os.path.exists(HISTORICAL_DB):
        os.remove(HISTORICAL_DB)

    print(f"[ETL] Writing to SQLite database at {HISTORICAL_DB}...")
    conn = sqlite3.connect(HISTORICAL_DB)

    df_p.to_sql('historical_projects', conn, if_exists='replace', index=False)
    df_e.to_sql('historical_payment_events', conn, if_exists='replace', index=False)

    print("[ETL] Creating database indexes...")
    cursor = conn.cursor()
    cursor.execute("CREATE UNIQUE INDEX idx_hp_work_id ON historical_projects(work_id);")
    cursor.execute("CREATE INDEX idx_hp_state ON historical_projects(state);")
    cursor.execute("CREATE INDEX idx_hp_district ON historical_projects(district);")
    cursor.execute("CREATE INDEX idx_hp_constituency ON historical_projects(constituency);")
    cursor.execute("CREATE INDEX idx_hp_mp ON historical_projects(mp_name);")
    cursor.execute("CREATE INDEX idx_hp_status ON historical_projects(work_completion_status);")
    cursor.execute("CREATE INDEX idx_hp_exec_status ON historical_projects(portal_execution_status);")
    cursor.execute("CREATE INDEX idx_hp_cat ON historical_projects(work_category);")

    cursor.execute("CREATE INDEX idx_hpe_work_id ON historical_payment_events(work_id);")
    cursor.execute("CREATE INDEX idx_hpe_vendor ON historical_payment_events(vendor_name_normalized);")
    cursor.execute("CREATE INDEX idx_hpe_date ON historical_payment_events(expenditure_date);")
    cursor.execute("CREATE INDEX idx_hpe_state ON historical_payment_events(state);")

    # Create pre-computed state and district summary table for analytics speed
    cursor.execute("""
        CREATE TABLE state_summary AS
        SELECT 
            state,
            COUNT(*) as total_projects,
            SUM(sanction_amount) as total_sanction_amount,
            SUM(total_disbursed) as total_disbursed_amount,
            SUM(CASE WHEN work_completion_status = 'COMPLETED' THEN 1 ELSE 0 END) as completed_projects,
            SUM(CASE WHEN work_completion_status != 'COMPLETED' THEN 1 ELSE 0 END) as ongoing_projects,
            COUNT(DISTINCT constituency) as total_constituencies,
            COUNT(DISTINCT ida) as total_idas
        FROM historical_projects
        GROUP BY state;
    """)

    conn.commit()
    conn.close()
    print("[ETL] Historical database successfully built and indexed!")


if __name__ == "__main__":
    run_etl()
