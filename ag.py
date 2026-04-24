"""
fetch_data.py
-------------
Extracts car rental transaction data from Hive data lake
for multiple countries and saves results as CSVs.

Usage:
    python fetch_data.py
    python fetch_data.py --config config/config.json
    python fetch_data.py --year 2024
"""


{
    "hive": {
        "driver_class": "com.cloudera.hive.jdbc.HS2Driver",
        "jdbc_url": "YOUR_JDBC_URL_HERE",
        "username": "YOUR_USERNAME_HERE",
        "password": "YOUR_PASSWORD_HERE",
        "jar_filename": "HiveJDBC42.jar"
    },
    "paths": {
        "country_codes_file": "data_and_other_files/all_codes_using_2023.xlsx",
        "sql_file": "sql/fetch_car_rental.sql",
        "output_dir": "raw_data"
    },
    "extraction": {
        "year": 2025
    }
}

import os
import json
import logging
import argparse
from datetime import datetime

import pandas as pd
import jaydebeapi


# ---------------------------------------------------------------------------
# Logging setup
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(f"fetch_data_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"),
    ],
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def load_config(config_path: str) -> dict:
    """Load configuration from a JSON file."""
    with open(config_path, "r") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Hive connection
# ---------------------------------------------------------------------------

def get_hive_connection(config: dict):
    """
    Create and return a JayDeBeApi connection to Hive.
    The JDBC jar is expected to be in the same directory as this script
    (or the path is specified in config).
    """
    hive_cfg = config["hive"]
    jar_path = os.path.join(os.getcwd(), hive_cfg["jar_filename"])

    logger.info("Connecting to Hive at: %s", hive_cfg["jdbc_url"])
    conn = jaydebeapi.connect(
        hive_cfg["driver_class"],
        hive_cfg["jdbc_url"],
        {"UID": hive_cfg["username"], "PWD": hive_cfg["password"]},
        jar_path,
    )
    logger.info("Hive connection established.")
    return conn


# ---------------------------------------------------------------------------
# Country codes
# ---------------------------------------------------------------------------

def load_country_codes(filepath: str) -> pd.DataFrame:
    """
    Load the master country/currency reference file.
    Expected columns: Country, City, Ctry_ID, country_code, Curr
    """
    df = pd.read_excel(filepath)
    df.dropna(inplace=True)
    df["Ctry_ID"] = df["Ctry_ID"].astype(int)

    logger.info("Loaded %d countries from: %s", df["Ctry_ID"].nunique(), filepath)
    return df


# ---------------------------------------------------------------------------
# SQL query
# ---------------------------------------------------------------------------

def load_sql_query(sql_path: str) -> str:
    """Load the SQL query template from file."""
    with open(sql_path, "r") as f:
        return f.read()


def build_query(template: str, country_curr: str, country_id: int, year: int) -> str:
    """Substitute placeholders in the SQL template."""
    return template.format(
        country_curr=country_curr,
        country_id=country_id,
        year=year,
    )


# ---------------------------------------------------------------------------
# Data fetching
# ---------------------------------------------------------------------------

def fetch_country_data(cursor, query: str, country_name: str) -> pd.DataFrame | None:
    """
    Execute a query and return results as a DataFrame.
    Returns None if the query fails so the loop can continue.
    """
    try:
        cursor.execute(query)
        rows = cursor.fetchall()
        columns = [desc[0] for desc in cursor.description]
        df = pd.DataFrame(rows, columns=columns)
        logger.info("  Fetched %d rows for %s", len(df), country_name)
        return df
    except Exception as exc:
        logger.error("  FAILED to fetch data for %s: %s", country_name, exc)
        return None


# ---------------------------------------------------------------------------
# Month-wise count
# ---------------------------------------------------------------------------

def month_wise_count(df: pd.DataFrame, country_name: str, year: int) -> pd.DataFrame:
    """
    Count car rental records per calendar month for a given country and year.
    Returns a single-row DataFrame with columns Jan..Dec.
    """
    pickup = pd.to_datetime(df["car_pickup_dt"], errors="coerce")

    counts = {
        "Country": country_name,
        "year": year,
    }
    month_names = ["Jan", "Feb", "Mar", "Apr", "May", "Jun",
                   "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]

    for month_num, month_name in enumerate(month_names, start=1):
        counts[month_name] = (pickup.dt.month == month_num).sum()

    return pd.DataFrame([counts])


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------

def ensure_output_dir(output_dir: str, year: int) -> str:
    """Create raw_data/{year}/ directory if it does not exist."""
    path = os.path.join(output_dir, str(year))
    os.makedirs(path, exist_ok=True)
    return path


def save_country_csv(df: pd.DataFrame, output_dir: str, country_name: str) -> None:
    """Save raw country data to CSV."""
    filepath = os.path.join(output_dir, f"{country_name}.csv")
    df.to_csv(filepath, index=False)
    logger.info("  Saved: %s", filepath)


def build_summary_row(df: pd.DataFrame, country_name: str, country_curr: str) -> dict:
    """Build a one-row summary dict for the all_countries_details report."""
    return {
        "Country": country_name,
        "Curr": country_curr,
        "min_date": df["car_pickup_dt"].min(),
        "max_date": df["car_pickup_dt"].max(),
        "Total records": len(df),
    }


# ---------------------------------------------------------------------------
# Main extraction loop
# ---------------------------------------------------------------------------

def run_extraction(config: dict, year: int | None = None) -> None:
    """
    Main pipeline:
      1. Load config, country codes, SQL template
      2. Connect to Hive
      3. For each country: fetch → save CSV → compute monthly counts → log summary
      4. Save aggregate reports
    """
    year = year or config["extraction"]["year"]
    paths = config["paths"]

    # Load reference data
    df_codes = load_country_codes(paths["country_codes_file"])
    sql_template = load_sql_query(paths["sql_file"])
    output_dir = ensure_output_dir(paths["output_dir"], year)

    # Connect
    conn = get_hive_connection(config)
    cursor = conn.cursor()

    # Accumulators
    all_details = []
    all_month_wise = []

    country_ids = df_codes["Ctry_ID"].unique()
    logger.info("Starting extraction for year=%d | countries=%d", year, len(country_ids))

    for country_id in country_ids:
        country_rows = df_codes[df_codes["Ctry_ID"] == country_id]
        country_name = country_rows["Country"].iloc[0]
        country_curr = country_rows["Curr"].iloc[0]

        logger.info("Processing: %s (ID=%s, Curr=%s)", country_name, country_id, country_curr)

        query = build_query(sql_template, country_curr, country_id, year)
        df = fetch_country_data(cursor, query, country_name)

        if df is None or df.empty:
            logger.warning("  No data for %s — skipping.", country_name)
            continue

        # Save raw CSV
        save_country_csv(df, output_dir, country_name)

        # Monthly counts
        month_df = month_wise_count(df, country_name, year)
        all_month_wise.append(month_df)

        # Summary row
        summary = build_summary_row(df, country_name, country_curr)
        all_details.append(summary)

        logger.info("  Done: %s", country_name)

    # Save aggregate reports
    if all_details:
        df_details = pd.DataFrame(all_details)
        details_path = os.path.join(output_dir, "all_countries_details.csv")
        df_details.to_csv(details_path, index=False)
        logger.info("Saved summary: %s", details_path)

    if all_month_wise:
        df_month_wise = pd.concat(all_month_wise, ignore_index=True)
        month_path = os.path.join(output_dir, "month_wise_details.csv")
        df_month_wise.to_csv(month_path, index=False)
        logger.info("Saved monthly summary: %s", month_path)

    cursor.close()
    conn.close()
    logger.info("Extraction complete.")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def parse_args():
    parser = argparse.ArgumentParser(description="Fetch car rental data from Hive.")
    parser.add_argument(
        "--config",
        default="config/config.json",
        help="Path to config JSON file (default: config/config.json)",
    )
    parser.add_argument(
        "--year",
        type=int,
        default=None,
        help="Override extraction year from config (e.g. --year 2024)",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    config = load_config(args.config)
    run_extraction(config, year=args.year)


if __name__ == "__main__":
    main()
