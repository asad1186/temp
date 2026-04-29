currency_code,rate_to_usd
ARS,864.75
AUD,1.51
EUR,0.92
BRL,5.01
CAD,1.36
CLP,942.33
COP,3770.00
CZK,23.35
DKK,6.85
DOP,59.17
HUF,358.00
ISK,138.00
ILS,3.69
LRD,193.00
MXN,16.34
MZN,63.50
NZD,1.65
NIO,36.80
NOK,10.63
PEN,3.69
PLN,3.91
USD,1.00
ZAR,18.44
GBP,0.79
SEK,10.50

data_and_other_files
currency_rates.csv

1fetch_data.py
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

2clean_data.py
"""
clean_data.py
-------------
Reads raw country CSVs (output of fetch_data.py), enriches them with city
and agency reference data, filters by approved agencies, and writes one
clean CSV per country per year.

Pipeline position:  fetch_data.py  -->  clean_data.py  -->  combine_data.py

Usage:
    python clean_data.py
    python clean_data.py --config config/config.json
"""

import os
import json
import logging
import argparse
from datetime import datetime
from typing import List

import pandas as pd


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(
            f"clean_data_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
        ),
    ],
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def load_config(config_path: str) -> dict:
    """
    Load pipeline configuration from a JSON file.

    Parameters
    ----------
    config_path : str
        Path to the config JSON file.

    Returns
    -------
    dict
        Parsed configuration dictionary.
    """
    with open(config_path, "r") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Agency allowlist
# NOTE: Complete this list with all remaining countries.
#       Each key is a 2-letter ISO country code, value is list of approved
#       agency codes.
# ---------------------------------------------------------------------------

def get_approved_agencies(country_code: str) -> List[str]:
    """
    Return the list of approved rental agency codes for a given country.

    Parameters
    ----------
    country_code : str
        2-letter ISO country code (e.g. 'AR', 'GB').

    Returns
    -------
    List[str]
        List of approved agency codes. Returns empty list if country is not
        configured — rows will be dropped for that country (logged as warning).
    """
    agency_map = {
        "AE": ["ZE", "ZI", "EP", "ZL", "ZD", "SX", "ZT"],
        "AR": ["ZE", "ZI", "ZL", "EP", "SX", "LL", "ZD"],
        "AU": ["ZI", "ZE", "ZT", "ZD", "EP", "ZL", "SX", "ET", "AL"],
        # VERIFY: remaining countries incomplete in source — fill in below
        # "AT": [...],
        # "BE": [...],
        # "BR": [...],
        # "CA": [...],
        # "CL": [...],
        # "CZ": [...],
        # "DK": [...],
        # "FI": [...],
        # "DE": [...],
        # "HU": [...],
        # "IS": [...],
        # "IE": [...],
        # "IL": [...],
        # "LU": [...],
        # "MX": [...],
        # "NL": [...],
        # "NZ": [...],
        # "NO": [...],
        # "PL": [...],
        # "PT": [...],
        # "ZA": [...],
        # "ES": [...],
        # "GB": [...],
        # "US": [...],
        # "FR": [...],
        # "SE": [...],
    }

    agencies = agency_map.get(country_code, [])
    if not agencies:
        logger.warning(
            "No agency list configured for country_code='%s' — all rows will be dropped.",
            country_code,
        )
    return agencies


# ---------------------------------------------------------------------------
# Reference data loaders
# ---------------------------------------------------------------------------

def load_country_codes(filepath: str) -> pd.DataFrame:
    """
    Load the master country/currency reference Excel file.

    Parameters
    ----------
    filepath : str
        Path to the Excel file (e.g. 'data_and_other_files/all_codes_using_2023.xlsx').

    Returns
    -------
    pd.DataFrame
        DataFrame with columns: Country, City, Ctry_ID, country_code, Curr.
        Rows with any NaN are dropped.
    """
    df = pd.read_excel(filepath)
    df.dropna(inplace=True)
    logger.info("Loaded %d country rows from %s", len(df), filepath)
    return df


def load_city_reference(filepath: str) -> pd.DataFrame:
    """
    Load city reference file and standardise column names.

    Parameters
    ----------
    filepath : str
        Path to City1.xlsx.

    Returns
    -------
    pd.DataFrame
        DataFrame with columns:
        CAR_RENTAL_COUNTRY_ID, CAR_RENTAL_CITY_ID,
        CAR_RENTAL_CITY_NM, CAR_RENTAL_STATE_CD.
    """
    df = pd.read_excel(filepath)
    df["CAR_RENTAL_STATE_CD"] = float("nan")
    df = df.rename(
        columns={
            "CAR_RENT_CTRY_ID": "CAR_RENTAL_COUNTRY_ID",
            "TRAV_CITY_CD":     "CAR_RENTAL_CITY_ID",
            "CAR_CITY_NAME":    "CAR_RENTAL_CITY_NM",  
        }
    )
    logger.info("Loaded %d city reference rows from %s", len(df), filepath)
    return df


def load_agency_reference(filepath: str) -> pd.DataFrame:
    """
    Load agency reference CSV.

    Parameters
    ----------
    filepath : str
        Path to Agency.csv.

    Returns
    -------
    pd.DataFrame
        DataFrame with at least columns:
        CAR_RENTAL_AGENCY_ID, CAR_RENTAL_AGENCY_NM.
    """
    df = pd.read_csv(filepath)
    logger.info("Loaded %d agency reference rows from %s", len(df), filepath)
    return df


# ---------------------------------------------------------------------------
# Month helper
# ---------------------------------------------------------------------------

def add_pickup_month(df: pd.DataFrame, date_col: str = "CAR_PICKUP_DT") -> pd.DataFrame:
    """
    Derive a month-level date column (first of each month) from a date column.

    Parameters
    ----------
    df : pd.DataFrame
        Input DataFrame containing a date column.
    date_col : str
        Name of the date column to derive the month from.

    Returns
    -------
    pd.DataFrame
        Same DataFrame with an added 'CAR_PICKUP_MONTH' column (date type,
        always the 1st of the month).
    """
    dt = pd.to_datetime(df[date_col])
    df["CAR_PICKUP_MONTH"] = pd.to_datetime(
        dt.dt.year * 10000 + dt.dt.month * 100 + 1,
        format="%Y%m%d",
    ).dt.date
    return df


# ---------------------------------------------------------------------------
# Core clean function
# ---------------------------------------------------------------------------

def clean_country_year(
    country: str,
    country_code: str,
    year: int,
    raw_data_dir: str,
    clean_data_dir: str,
    df_city: pd.DataFrame,
    df_agency: pd.DataFrame,
) -> None:
    """
    Clean raw data for one country and one year:
      - Uppercases all column names
      - Adds country code column
      - Merges city name from reference
      - Merges agency name from reference
      - Derives CAR_PICKUP_MONTH from CAR_PICKUP_DT
      - Filters to approved agencies and removes UNDEFINED car types
      - Saves result to clean/{year}/{country_code}_CLEAN.csv

    Parameters
    ----------
    country : str
        Full country name (e.g. 'ARGENTINA') used to find the raw CSV.
    country_code : str
        2-letter ISO country code (e.g. 'AR') used for agency filtering
        and output filename.
    year : int
        Data year (e.g. 2025).
    raw_data_dir : str
        Root folder containing raw CSVs from fetch_data.py (e.g. 'raw_data').
    clean_data_dir : str
        Root folder for cleaned output CSVs (e.g. 'clean').
    df_city : pd.DataFrame
        City reference DataFrame (output of load_city_reference).
    df_agency : pd.DataFrame
        Agency reference DataFrame (output of load_agency_reference).

    Returns
    -------
    None
        Writes CSV to clean/{year}/{country_code}_CLEAN.csv.
    """
    raw_path = os.path.join(raw_data_dir, str(year), f"{country}.csv")
    if not os.path.exists(raw_path):
        logger.warning("Raw file not found, skipping: %s", raw_path)
        return

    df = pd.read_csv(raw_path)
    df.columns = df.columns.str.upper()
    df["CAR_RENTAL_COUNTRY_CD"] = country_code

    # --- merge city reference ---
    df = pd.merge(
        df[[
            "CAR_PICKUP_DT", "CLIENT_GROUP_ID", "CAR_RENTAL_COUNTRY_ID",
            "CAR_RENTAL_COUNTRY_CD", "CAR_RENTAL_CITY_ID", "CAR_RENTAL_AGENCY_ID",
            "CAR_TYPE_NM", "BOOKING_CT", "CAR_RATE_AM", "CAR_DAY_CT", "CAR_BOOKED_AM",
        ]],
        df_city[[
            "CAR_RENTAL_COUNTRY_ID", "CAR_RENTAL_CITY_ID",
            "CAR_RENTAL_CITY_NM", "CAR_RENTAL_STATE_CD",
        ]],
        on=["CAR_RENTAL_COUNTRY_ID", "CAR_RENTAL_CITY_ID"],
        how="left",
    )

    # --- merge agency reference ---
    df = pd.merge(
        df[[
            "CAR_PICKUP_DT", "CLIENT_GROUP_ID", "CAR_RENTAL_COUNTRY_CD",
            "CAR_RENTAL_STATE_CD", "CAR_RENTAL_CITY_NM", "CAR_RENTAL_AGENCY_ID",
            "CAR_TYPE_NM", "BOOKING_CT", "CAR_RATE_AM", "CAR_DAY_CT", "CAR_BOOKED_AM",
        ]],
        df_agency[["CAR_RENTAL_AGENCY_ID", "CAR_RENTAL_AGENCY_NM"]],
        on="CAR_RENTAL_AGENCY_ID",
        how="left",
    )

    # --- derive month column ---
    df = add_pickup_month(df, date_col="CAR_PICKUP_DT")

    # --- select final columns ---
    final_cols = [
        "CAR_PICKUP_MONTH", "CLIENT_GROUP_ID", "CAR_RENTAL_COUNTRY_CD",
        "CAR_RENTAL_STATE_CD", "CAR_RENTAL_CITY_NM", "CAR_RENTAL_AGENCY_ID",
        "CAR_RENTAL_AGENCY_NM", "CAR_TYPE_NM", "BOOKING_CT",
        "CAR_RATE_AM", "CAR_DAY_CT", "CAR_BOOKED_AM",
    ]
    df = df[final_cols]

    # --- filter by approved agencies and remove UNDEFINED car types ---
    approved = get_approved_agencies(country_code)
    before = len(df)
    df = df[
        df["CAR_RENTAL_AGENCY_ID"].isin(approved) &
        (df["CAR_TYPE_NM"] != "UNDEFINED")
    ]
    logger.info(
        "  %s %d: %d rows → %d after agency/type filter",
        country_code, year, before, len(df),
    )

    # --- save ---
    out_dir = os.path.join(clean_data_dir, str(year))
    os.makedirs(out_dir, exist_ok=True)
    out_path = os.path.join(out_dir, f"{country_code}_CLEAN.csv")
    df.to_csv(out_path, index=False)
    logger.info("  Saved: %s", out_path)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run_cleaning(config: dict) -> None:
    """
    Run the full cleaning pipeline for all countries and all configured years.

    Parameters
    ----------
    config : dict
        Loaded configuration dictionary from config.json.

    Returns
    -------
    None
    """
    paths = config["paths"]
    years: List[int] = config["extraction"]["years_to_clean"]

    df_codes  = load_country_codes(paths["country_codes_file"])
    df_city   = load_city_reference(paths["ref_city_file"])
    df_agency = load_agency_reference(paths["ref_agency_file"])

    country_code_map = dict(zip(df_codes["Country"], df_codes["country_code"]))

    logger.info(
        "Starting cleaning | years=%s | countries=%d",
        years, len(country_code_map),
    )

    for year in years:
        logger.info("--- Year: %d ---", year)
        for country, country_code in country_code_map.items():
            clean_country_year(
                country=country,
                country_code=country_code,
                year=year,
                raw_data_dir=paths["raw_data_dir"],
                clean_data_dir=paths["clean_data_dir"],
                df_city=df_city,
                df_agency=df_agency,
            )

    logger.info("Cleaning complete.")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Clean raw car rental CSVs.")
    parser.add_argument(
        "--config",
        default="config/config.json",
        help="Path to config JSON (default: config/config.json)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config = load_config(args.config)
    run_cleaning(config)


if __name__ == "__main__":
    main()

3combine_data.py
"""
combine_data.py
---------------
Combines all per-country clean CSVs (output of clean_data.py) into a single
combined CSV per year.

Pipeline position:  clean_data.py  -->  combine_data.py  -->  ground_monitor.py

Usage:
    python combine_data.py
    python combine_data.py --config config/config.json
"""

import os
import json
import logging
import argparse
from datetime import datetime
from typing import List

import pandas as pd


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(
            f"combine_data_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
        ),
    ],
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def load_config(config_path: str) -> dict:
    """
    Load pipeline configuration from a JSON file.

    Parameters
    ----------
    config_path : str
        Path to the config JSON file.

    Returns
    -------
    dict
        Parsed configuration dictionary.
    """
    with open(config_path, "r") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Core combine function
# ---------------------------------------------------------------------------

def combine_year(
    year: int,
    country_codes: List[str],
    clean_data_dir: str,
    combined_data_dir: str,
) -> None:
    """
    Combine all country clean CSVs for a given year into one file.

    Reads clean/{year}/{country_code}_CLEAN.csv for each country code,
    concatenates them, and saves to combined_clean/{year}_comb.csv.

    Parameters
    ----------
    year : int
        The data year to combine (e.g. 2025).
    country_codes : List[str]
        List of 2-letter ISO country codes to include (e.g. ['AR', 'AU', ...]).
    clean_data_dir : str
        Root folder containing per-year clean CSVs (e.g. 'clean').
    combined_data_dir : str
        Root folder where combined CSVs are saved (e.g. 'combined_clean').

    Returns
    -------
    None
        Writes combined CSV to combined_clean/{year}_comb.csv.
    """
    logger.info("--- Combining year: %d ---", year)
    frames = []

    for country_code in country_codes:
        path = os.path.join(clean_data_dir, str(year), f"{country_code}_CLEAN.csv")
        if not os.path.exists(path):
            logger.warning("  Clean file not found, skipping: %s", path)
            continue
        df = pd.read_csv(path)
        frames.append(df)
        logger.info("  Loaded %d rows from %s", len(df), path)

    if not frames:
        logger.error("  No data found for year %d — combined file not created.", year)
        return

    df_combined = pd.concat(frames, ignore_index=True)
    logger.info("  Total rows for %d: %d", year, len(df_combined))

    os.makedirs(combined_data_dir, exist_ok=True)
    out_path = os.path.join(combined_data_dir, f"{year}_comb.csv")
    df_combined.to_csv(out_path, index=False)
    logger.info("  Saved: %s", out_path)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run_combining(config: dict) -> None:
    """
    Run the combining step for all configured years.

    Reads country codes from the master Excel reference file,
    then calls combine_year for each year in years_to_combine.

    Parameters
    ----------
    config : dict
        Loaded configuration dictionary from config.json.

    Returns
    -------
    None
    """
    paths = config["paths"]
    years: List[int] = config["extraction"]["years_to_combine"]

    # Load country codes from master reference
    df_codes = pd.read_excel(paths["country_codes_file"])
    df_codes.dropna(inplace=True)
    country_codes: List[str] = df_codes["country_code"].unique().tolist()

    logger.info(
        "Starting combining | years=%s | countries=%d",
        years, len(country_codes),
    )

    for year in years:
        combine_year(
            year=year,
            country_codes=country_codes,
            clean_data_dir=paths["clean_data_dir"],
            combined_data_dir=paths["combined_data_dir"],
        )

    logger.info("Combining complete.")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Combine clean country CSVs by year.")
    parser.add_argument(
        "--config",
        default="config/config.json",
        help="Path to config JSON (default: config/config.json)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config = load_config(args.config)
    run_combining(config)


if __name__ == "__main__":
    main()

4ground_monitor.py
"""
ground_monitor.py
-----------------
Loads historical and current car rental data, applies cleaning/outlier
removal, removes manual combinations, builds Prophet forecasting models
per city/car-type, and saves predictions.

Pipeline position:  combine_data.py  -->  ground_monitor.py  -->  yoy_forecast.py

Usage:
    python ground_monitor.py
    python ground_monitor.py --config config/config.json
"""

import os
import json
import logging
import argparse
import warnings
from datetime import datetime
from typing import Tuple

import pandas as pd
import numpy as np
from prophet import Prophet

warnings.filterwarnings("ignore")


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(
            f"ground_monitor_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
        ),
    ],
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def load_config(config_path: str) -> dict:
    """
    Load pipeline configuration from a JSON file.

    Parameters
    ----------
    config_path : str
        Path to the config JSON file.

    Returns
    -------
    dict
        Parsed configuration dictionary.
    """
    with open(config_path, "r") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Data loaders
# ---------------------------------------------------------------------------

def load_currency_rates(filepath: str) -> dict:
    """
    Load currency-to-USD conversion rates from CSV.

    Parameters
    ----------
    filepath : str
        Path to currency_rates.csv with columns: currency_code, rate_to_usd.

    Returns
    -------
    dict
        Mapping of currency code (str) -> rate to USD (float).
        e.g. {'ARS': 864.75, 'AUD': 1.51, ...}
    """
    df = pd.read_csv(filepath)
    return dict(zip(df["currency_code"], df["rate_to_usd"]))


def load_country_reference(filepath: str) -> pd.DataFrame:
    """
    Load the master country/currency reference Excel file.

    Parameters
    ----------
    filepath : str
        Path to all_codes_using_2023.xlsx.

    Returns
    -------
    pd.DataFrame
        DataFrame with columns: Country, City, Ctry_ID, country_code, Curr.
        Rows with NaN dropped. Adds curr_to_dollar column.
    """
    df = pd.read_excel(filepath)
    df.dropna(inplace=True)
    return df


def add_pickup_month_from_date(df: pd.DataFrame, date_col: str) -> pd.DataFrame:
    """
    Derive CAR_PICKUP_MONTH (first of month) from a date column.

    Parameters
    ----------
    df : pd.DataFrame
        Input DataFrame with a date column.
    date_col : str
        Name of the date column to convert.

    Returns
    -------
    pd.DataFrame
        Input DataFrame with added CAR_PICKUP_MONTH column (date type).
    """
    dt = pd.to_datetime(df[date_col])
    df["CAR_PICKUP_MONTH"] = pd.to_datetime(
        dt.dt.year * 10000 + dt.dt.month * 100 + 1,
        format="%Y%m%d",
    ).dt.date
    return df


def load_legacy_data(paths: dict) -> Tuple[pd.DataFrame, pd.DataFrame]:
    """
    Load and prepare legacy (pre-2021) datasets.

    Reads FR/SE 2012-2018, US 2012-2018, combined 2012-2018,
    and 2019/2020-2023 datasets. Converts date-level files to month-level.

    Parameters
    ----------
    paths : dict
        The 'paths' section from config.json, containing keys:
        legacy_fr_se_12_18, legacy_fr_se_19_23, legacy_us_12_18,
        legacy_wu1218, legacy_2019, legacy_2020_2023.

    Returns
    -------
    Tuple[pd.DataFrame, pd.DataFrame]
        (data_2012_2018, data_2019_2025) — both at transaction level,
        not yet aggregated. Ready for filtering and outlier removal.

    Notes
    -----
    # VERIFY: data_2020_2023 (req_files/20-23Comb_data.csv) appears to
    # exclude FR and SE, which are sourced separately from
    # France_sweden/FR_SEltd19-23Comb_datanf.csv.
    # Confirm whether this split is intentional.
    """
    filtered_cols = [
        "CAR_PICKUP_MONTH", "CAR_TYPE_NM", "CAR_RENTAL_COUNTRY_CD",
        "CAR_RENTAL_CITY_NM", "CAR_RATE_AM", "CAR_DAY_CT", "CAR_BOOKED_AM",
    ]

    # --- 2012-2018 ---
    df_fr_se_12_18  = pd.read_csv(paths["legacy_fr_se_12_18"])[filtered_cols]
    df_us_12_18     = pd.read_csv(paths["legacy_us_12_18"])[filtered_cols]
    wu1218          = pd.read_csv(paths["legacy_wu1218"])[filtered_cols]
    data_2012_2018  = pd.concat([wu1218, df_fr_se_12_18, df_us_12_18], ignore_index=True)

    # --- 2019 (date-level → convert to month) ---
    data_2019 = pd.read_csv(paths["legacy_2019"])
    data_2019 = add_pickup_month_from_date(data_2019, "CAR_PICKUP_DT")
    data_2019 = data_2019[filtered_cols]

    # --- 2020-2023 (date-level → convert to month) ---
    data_2020_2023 = pd.read_csv(paths["legacy_2020_2023"])
    data_2020_2023["CAR_PICKUP_DT"] = pd.to_datetime(data_2020_2023["CAR_PICKUP_DT"])
    data_2020_2023 = add_pickup_month_from_date(data_2020_2023, "CAR_PICKUP_DT")

    # --- FR/SE 2019-2023 separate source ---
    df_fr_se_19_23 = pd.read_csv(paths["legacy_fr_se_19_23"])
    df_fr_se_19_23["CAR_PICKUP_DT"] = pd.to_datetime(df_fr_se_19_23["CAR_PICKUP_DT"])
    df_fr_se_19_23 = add_pickup_month_from_date(df_fr_se_19_23, "CAR_PICKUP_DT")

    # --- 2020 split: non-FR/SE from main file, FR/SE from separate file ---
    # VERIFY: confirm that data_2020_2023 excludes FR and SE
    data_2020_w_frse = data_2020_2023[
        (data_2020_2023["CAR_PICKUP_DT"] >= "2020-01-01") &
        (data_2020_2023["CAR_PICKUP_DT"] <= "2020-12-31")
    ][filtered_cols]

    data_2020_frse = df_fr_se_19_23[
        (df_fr_se_19_23["CAR_PICKUP_DT"] >= "2020-01-01") &
        (df_fr_se_19_23["CAR_PICKUP_DT"] <= "2020-12-31")
    ][filtered_cols]

    data_2019_2025 = pd.concat(
        [data_2019, data_2020_w_frse, data_2020_frse],
        ignore_index=True,
    )

    return data_2012_2018, data_2019_2025


def load_combined_data(combined_data_dir: str) -> pd.DataFrame:
    """
    Load combined clean data for years 2021-2025 (output of combine_data.py).

    Parameters
    ----------
    combined_data_dir : str
        Folder containing {year}_comb.csv files (e.g. 'combined_clean').

    Returns
    -------
    pd.DataFrame
        Concatenated DataFrame for years 2021-2025.
    """
    frames = []
    for year in [2021, 2022, 2023, 2024, 2025]:
        path = os.path.join(combined_data_dir, f"{year}_comb.csv")
        if not os.path.exists(path):
            logger.warning("Combined file not found, skipping: %s", path)
            continue
        df = pd.read_csv(path)
        frames.append(df)
        logger.info("  Loaded %d rows from %s", len(df), path)

    return pd.concat(frames, ignore_index=True)


# ---------------------------------------------------------------------------
# Threshold filtering
# ---------------------------------------------------------------------------

def apply_rate_thresholds(
    df: pd.DataFrame,
    country_cd_curr_map: dict,
    uk_threshold: float,
    other_threshold_usd: float,
) -> pd.DataFrame:
    """
    Remove rows where the daily car rate exceeds country-specific thresholds.

    UK (GB): threshold applied directly in local currency (GBP).
    All others: rate converted to USD using currency map, then threshold applied.

    Parameters
    ----------
    df : pd.DataFrame
        Car rental DataFrame with columns CAR_RENTAL_COUNTRY_CD, CAR_RATE_AM.
    country_cd_curr_map : dict
        Mapping of country_code -> rate_to_usd (e.g. {'GB': 0.79, 'US': 1.0}).
    uk_threshold : float
        Max allowed CAR_RATE_AM for UK (in GBP).
    other_threshold_usd : float
        Max allowed CAR_RATE_AM for all other countries (in USD).

    Returns
    -------
    pd.DataFrame
        Filtered DataFrame with high-rate rows removed.
    """
    # --- UK ---
    df_uk = df[df["CAR_RENTAL_COUNTRY_CD"] == "GB"]
    df_uk = df_uk[df_uk["CAR_RATE_AM"] <= uk_threshold]
    logger.info("  UK rows after threshold: %d", len(df_uk))

    # --- Others ---
    df_others = df[df["CAR_RENTAL_COUNTRY_CD"] != "GB"].copy()
    df_others["curr_to_dollar"] = df_others["CAR_RENTAL_COUNTRY_CD"].map(country_cd_curr_map)
    df_others["CAR_RATE_AM_dollars"] = df_others["CAR_RATE_AM"] / df_others["curr_to_dollar"]
    df_others = df_others[df_others["CAR_RATE_AM_dollars"] <= other_threshold_usd]
    df_others = df_others.drop(columns=["curr_to_dollar", "CAR_RATE_AM_dollars"])
    logger.info("  Non-UK rows after threshold: %d", len(df_others))

    return pd.concat([df_uk, df_others], ignore_index=True)


# ---------------------------------------------------------------------------
# Outlier removal
# ---------------------------------------------------------------------------

def strip_outliers(df: pd.DataFrame, date_col: str, measure: str) -> pd.DataFrame:
    """
    Remove outliers using the IQR method, applied per country/city/car-type group.

    Rows outside [Q1 - 1.5*IQR, Q3 + 1.5*IQR] for the given measure
    are dropped.

    Parameters
    ----------
    df : pd.DataFrame
        Monthly aggregated car rental data with columns:
        CAR_RENTAL_COUNTRY_CD, CAR_RENTAL_CITY_NM, CAR_TYPE_NM, and measure.
    date_col : str
        Name of the date column (used for signature clarity; not filtered on).
    measure : str
        Column name to apply outlier removal on (e.g. 'CAR_RATE_AM').

    Returns
    -------
    pd.DataFrame
        DataFrame with outlier rows removed.
    """
    group_cols = ["CAR_RENTAL_COUNTRY_CD", "CAR_RENTAL_CITY_NM", "CAR_TYPE_NM"]

    bounds = (
        df.groupby(group_cols)[measure]
        .describe()[["25%", "75%"]]
        .reset_index()
    )
    bounds["LB"] = bounds["25%"] - (bounds["75%"] - bounds["25%"]) * 1.5
    bounds["UB"] = bounds["75%"] + (bounds["75%"] - bounds["25%"]) * 1.5
    bounds.drop(columns=["25%", "75%"], inplace=True)

    df = df.merge(bounds, on=group_cols, how="left")
    df = df[(df[measure] >= df["LB"]) & (df[measure] <= df["UB"])]
    df = df.drop(columns=["LB", "UB"])

    return df.reset_index(drop=True)


# ---------------------------------------------------------------------------
# Combination removal
# ---------------------------------------------------------------------------

def remove_manual_combinations(
    df: pd.DataFrame,
    combinations_file: str,
    country_cd_map: dict,
) -> pd.DataFrame:
    """
    Drop specific country/city/car-type combinations listed in an Excel file.

    Parameters
    ----------
    df : pd.DataFrame
        Final data DataFrame containing columns Country, CAR_RENTAL_CITY_NM, CAR_TYPE_NM.
    combinations_file : str
        Path to Excel file listing combinations to remove.
        Expected columns: Country, CAR_RENTAL_CITY_NM, CAR_TYPE_1.
    country_cd_map : dict
        Mapping of country_code -> full country name.

    Returns
    -------
    pd.DataFrame
        DataFrame with specified combinations removed.
    """
    df_combos = pd.read_excel(combinations_file)
    df_combos.reset_index(drop=True, inplace=True)

    # Add full country name to main data for matching
    df["Country"] = df["CAR_RENTAL_COUNTRY_CD"].map(country_cd_map)

    before = len(df)
    for _, row in df_combos.iterrows():
        country  = row["Country"]
        city     = row["CAR_RENTAL_CITY_NM"]
        car_type = row["CAR_TYPE_NM"]          
        mask = (
            (df["Country"] == country) &
            (df["CAR_RENTAL_CITY_NM"] == city) &
            (df["CAR_TYPE_NM"] == car_type)
        )
        df = df[~mask]

    logger.info(
        "Removed %d rows via manual combinations file.", before - len(df)
    )
    return df.reset_index(drop=True)


# ---------------------------------------------------------------------------
# Aggregation
# ---------------------------------------------------------------------------

def aggregate_to_monthly(df: pd.DataFrame) -> pd.DataFrame:
    """
    Aggregate transaction-level data to monthly level per city/type/country.

    Parameters
    ----------
    df : pd.DataFrame
        Transaction-level DataFrame with columns:
        CAR_PICKUP_MONTH, CAR_TYPE_NM, CAR_RENTAL_COUNTRY_CD,
        CAR_RENTAL_CITY_NM, CAR_RATE_AM, CAR_DAY_CT, CAR_BOOKED_AM.

    Returns
    -------
    pd.DataFrame
        Monthly aggregated DataFrame:
        - CAR_RATE_AM: mean
        - CAR_DAY_CT: sum
        - CAR_BOOKED_AM: sum
    """
    group_cols = [
        "CAR_PICKUP_MONTH", "CAR_TYPE_NM",
        "CAR_RENTAL_COUNTRY_CD", "CAR_RENTAL_CITY_NM",
    ]
    return (
        df.groupby(group_cols)
        .agg(
            CAR_RATE_AM=("CAR_RATE_AM", "mean"),
            CAR_DAY_CT=("CAR_DAY_CT", "sum"),
            CAR_BOOKED_AM=("CAR_BOOKED_AM", "sum"),
        )
        .reset_index()
    )


# ---------------------------------------------------------------------------
# Weightage
# ---------------------------------------------------------------------------

def build_weightage(df: pd.DataFrame) -> pd.DataFrame:
    """
    Compute the share of car days per car type within each city (weightage).

    Used downstream in yoy_forecast.py to weight YoY % changes.

    Parameters
    ----------
    df : pd.DataFrame
        Final clean monthly data with columns:
        CAR_RENTAL_CITY_NM, CAR_RENTAL_COUNTRY_CD, CAR_TYPE_NM, CAR_DAY_CT.

    Returns
    -------
    pd.DataFrame
        DataFrame with columns:
        CAR_RENTAL_CITY_NM, CAR_RENTAL_COUNTRY_CD, CAR_TYPE_NM,
        CAR_DAY_CT (city total), weight (type total), weightage (type/city).
    """
    city_total = (
        df.groupby(["CAR_RENTAL_CITY_NM", "CAR_RENTAL_COUNTRY_CD"])["CAR_DAY_CT"]
        .sum()
        .reset_index()
    )
    type_total = (
        df.groupby(["CAR_TYPE_NM", "CAR_RENTAL_CITY_NM", "CAR_RENTAL_COUNTRY_CD"])["CAR_DAY_CT"]
        .sum()
        .reset_index()
        .rename(columns={"CAR_DAY_CT": "weight"})
    )
    merged = pd.merge(
        city_total, type_total,
        on=["CAR_RENTAL_CITY_NM", "CAR_RENTAL_COUNTRY_CD"],
        how="inner",
    )
    merged["weightage"] = merged["weight"] / merged["CAR_DAY_CT"]
    return merged


# ---------------------------------------------------------------------------
# Prophet model selection
# ---------------------------------------------------------------------------

def _is_additive_case(country_cd: str, city: str, car_type: str) -> bool:
    """
    Return True if this country/city/car-type combination should use
    additive seasonality instead of the default multiplicative.

    Hardcoded special cases identified during model tuning.

    Parameters
    ----------
    country_cd : str
        2-letter country code.
    city : str
        City name.
    car_type : str
        Car type name.

    Returns
    -------
    bool
        True if additive seasonality should be used.
    """
    # VERIFY: confirm these special cases are still valid for current data
    if country_cd == "GB" and city == "LONDON" and car_type == "SPECIAL":
        return True
    if city == "MALMO" and car_type == "LUXURY":
        return True
    if city == "ALICANTE" and car_type == "PREMIUM":
        return True
    if city == "NEWMAN" and car_type == "COMPACT":   
        return True
    return False


def build_prophet_model(country_cd: str, city: str, car_type: str) -> Prophet:
    """
    Build and return a configured Prophet model for a given country/city/car-type.

    US uses multiplicative seasonality with yearly_seasonality=5.
    A small set of hardcoded special cases use additive seasonality.
    All others use multiplicative with yearly_seasonality=5.

    Parameters
    ----------
    country_cd : str
        2-letter country code (e.g. 'US', 'GB').
    city : str
        City name (e.g. 'LONDON').
    car_type : str
        Car type name (e.g. 'COMPACT', 'LUXURY').

    Returns
    -------
    Prophet
        Configured (unfitted) Prophet model instance.
    """
    common_kwargs = dict(
        weekly_seasonality=False,
        daily_seasonality=False,
        changepoint_range=0.82,
    )

    if country_cd == "US":
        return Prophet(
            seasonality_mode="multiplicative",
            yearly_seasonality=5,
            **common_kwargs,
        )
    elif _is_additive_case(country_cd, city, car_type):
        return Prophet(
            seasonality_mode="additive",
            yearly_seasonality=True,
            **common_kwargs,
        )
    else:
        return Prophet(
            seasonality_mode="multiplicative",
            yearly_seasonality=5,
            **common_kwargs,
        )


# ---------------------------------------------------------------------------
# Forecasting loop
# ---------------------------------------------------------------------------

def run_forecasting(
    train: pd.DataFrame,
    prediction_start_date: str,
    prediction_end_date: str,
    min_rows: int = 20,
) -> pd.DataFrame:
    """
    Fit Prophet models and generate forecasts for all country/city/car-type combos.

    Iterates over every unique combination of country → city → car_type in
    the training data. Skips combinations with fewer than min_rows data points.

    Parameters
    ----------
    train : pd.DataFrame
        Training data with columns: ds, y, CAR_RENTAL_COUNTRY_CD,
        CAR_RENTAL_CITY_NM, CAR_TYPE_NM.
    prediction_start_date : str
        Start date of forecast period (e.g. '2025-04-01').
    prediction_end_date : str
        End date of forecast period (e.g. '2026-06-01').
    min_rows : int
        Minimum number of training rows required to fit a model. Default 20.

    Returns
    -------
    pd.DataFrame
        Forecast DataFrame with columns:
        ds, yhat, yhat_lower, yhat_upper,
        CAR_TYPE_NM, CAR_RENTAL_CITY_NM, CAR_RENTAL_COUNTRY_CD.
    """
    date_range = pd.date_range(
        start=prediction_start_date,
        end=prediction_end_date,
        freq="MS",
    )
    future = pd.DataFrame({"ds": date_range})

    all_forecasts = []

    for country_cd in train["CAR_RENTAL_COUNTRY_CD"].unique():
        train_country = train[train["CAR_RENTAL_COUNTRY_CD"] == country_cd]

        for city in train_country["CAR_RENTAL_CITY_NM"].unique():
            train_city = train_country[train_country["CAR_RENTAL_CITY_NM"] == city]

            for car_type in train_city["CAR_TYPE_NM"].unique():
                train_slice = train_city[train_city["CAR_TYPE_NM"] == car_type].copy()

                if len(train_slice) <= min_rows:
                    logger.debug(
                        "Skipping %s / %s / %s — only %d rows",
                        country_cd, city, car_type, len(train_slice),
                    )
                    continue

                train_slice = train_slice.sort_values("ds")
                logger.info("Fitting: %s | %s | %s (%d rows)", country_cd, city, car_type, len(train_slice))

                try:
                    model = build_prophet_model(country_cd, city, car_type)
                    model.fit(train_slice[["ds", "y"]])
                    forecast = model.predict(future)
                    forecast["CAR_RENTAL_CITY_NM"]    = city
                    forecast["CAR_RENTAL_COUNTRY_CD"] = country_cd
                    forecast["CAR_TYPE_NM"]           = car_type

                    all_forecasts.append(
                        forecast[[
                            "ds", "yhat", "yhat_lower", "yhat_upper",
                            "CAR_TYPE_NM", "CAR_RENTAL_CITY_NM", "CAR_RENTAL_COUNTRY_CD",
                        ]]
                    )
                except Exception as exc:
                    logger.error(
                        "Model failed for %s / %s / %s: %s",
                        country_cd, city, car_type, exc,
                    )
                    continue

    if not all_forecasts:
        logger.error("No forecasts were generated.")
        return pd.DataFrame()

    return pd.concat(all_forecasts, ignore_index=True)


# ---------------------------------------------------------------------------
# Main pipeline
# ---------------------------------------------------------------------------

def run_ground_monitor(config: dict) -> None:
    """
    Run the full ground monitor pipeline:
      1. Load currency rates and country reference
      2. Load legacy (pre-2021) + combined (2021-2025) data
      3. Filter to forecastable cities
      4. Apply rate thresholds (UK vs others)
      5. Aggregate to monthly level
      6. Remove outliers
      7. Combine all data and remove manual combinations
      8. Build weightage file
      9. Run Prophet forecasting
      10. Save predictions, training data, and weightage

    Parameters
    ----------
    config : dict
        Loaded configuration dictionary from config.json.

    Returns
    -------
    None
    """
    paths       = config["paths"]
    fc_cfg      = config["forecasting"]
    thresh_cfg  = config["thresholds"]

    results_dir = fc_cfg["results_dir"]
    os.makedirs(results_dir, exist_ok=True)

    # --- reference data ---
    curr_conv_map = load_currency_rates(paths["currency_rates_file"])
    df_ref        = load_country_reference(paths["country_codes_file"])
    df_ref["curr_to_dollar"] = df_ref["Curr"].map(curr_conv_map)

    city_to_forecast       = df_ref["City"].unique()
    country_cd_map         = dict(zip(df_ref["country_code"], df_ref["Country"]))
    country_cd_curr_map    = dict(zip(df_ref["country_code"], df_ref["curr_to_dollar"]))

    # --- load data ---
    logger.info("Loading legacy data...")
    data_2012_2018, data_2019_part = load_legacy_data(paths)

    logger.info("Loading combined 2021-2025 data...")
    data_2021_2025 = load_combined_data(paths["combined_data_dir"])

    # Cap 2025 data at March (data fetched in first week of March 2025)
    data_2021_2025 = data_2021_2025[
        data_2021_2025["CAR_PICKUP_MONTH"] <= "2025-03-01"
    ]

    data_2019_2025 = pd.concat(
        [data_2019_part, data_2021_2025], ignore_index=True
    )

    # --- filter to forecastable cities ---
    data_2012_2018 = data_2012_2018[
        data_2012_2018["CAR_RENTAL_CITY_NM"].isin(city_to_forecast)
    ]
    data_2019_2025 = data_2019_2025[
        data_2019_2025["CAR_RENTAL_CITY_NM"].isin(city_to_forecast)
    ]
    logger.info(
        "After city filter — 2012-2018: %d rows | 2019-2025: %d rows",
        len(data_2012_2018), len(data_2019_2025),
    )

    # --- apply rate thresholds ---
    logger.info("Applying rate thresholds...")
    data_2012_2018 = apply_rate_thresholds(
        data_2012_2018, country_cd_curr_map,
        thresh_cfg["uk_rate_threshold"],
        thresh_cfg["other_rate_threshold_usd"],
    )
    data_2019_2025 = apply_rate_thresholds(
        data_2019_2025, country_cd_curr_map,
        thresh_cfg["uk_rate_threshold"],
        thresh_cfg["other_rate_threshold_usd"],
    )

    # --- aggregate to monthly ---
    logger.info("Aggregating to monthly level...")
    data_2012_2018_mon = aggregate_to_monthly(data_2012_2018)
    data_2019_2025_mon = aggregate_to_monthly(data_2019_2025)

    # --- outlier removal ---
    logger.info("Removing outliers...")
    before_12_18 = len(data_2012_2018_mon)
    data_2012_2018_clean = strip_outliers(data_2012_2018_mon, "CAR_PICKUP_MONTH", "CAR_RATE_AM")
    logger.info("  2012-2018: %d → %d rows", before_12_18, len(data_2012_2018_clean))

    before_19_25 = len(data_2019_2025_mon)
    data_2019_2025_clean = strip_outliers(data_2019_2025_mon, "CAR_PICKUP_MONTH", "CAR_RATE_AM")
    logger.info("  2019-2025: %d → %d rows", before_19_25, len(data_2019_2025_clean))

    # --- combine all clean data ---
    final_data = pd.concat(
        [data_2012_2018_clean, data_2019_2025_clean], ignore_index=True
    )

    # --- remove manual combinations ---
    logger.info("Removing manual combinations...")
    final_data = remove_manual_combinations(
        final_data, paths["remove_combinations_file"], country_cd_map
    )

    # --- build weightage ---
    logger.info("Building weightage file...")
    df_weightage = build_weightage(final_data)
    weightage_path = os.path.join(results_dir, fc_cfg["weightage_filename"])
    df_weightage[
        ["CAR_RENTAL_COUNTRY_CD", "CAR_RENTAL_CITY_NM", "CAR_TYPE_NM", "CAR_DAY_CT", "weightage"]
    ].to_csv(weightage_path, index=False)
    logger.info("Saved weightage: %s", weightage_path)

    # --- prepare Prophet training data ---
    logger.info("Preparing Prophet training data...")
    train_prophet = (
        final_data[final_data["CAR_TYPE_NM"] != "UNDEFINED"]
        .groupby(["CAR_PICKUP_MONTH", "CAR_RENTAL_CITY_NM", "CAR_TYPE_NM", "CAR_RENTAL_COUNTRY_CD"])
        ["CAR_RATE_AM"]
        .mean()
        .reset_index()
        .rename(columns={"CAR_PICKUP_MONTH": "ds", "CAR_RATE_AM": "y"})
    )
    train_prophet["ds"] = pd.to_datetime(train_prophet["ds"])

    # filter to training window
    training_start = fc_cfg["training_start_date"]
    training_end   = fc_cfg["training_end_date"]
    train = train_prophet[
        (train_prophet["ds"] >= training_start) &
        (train_prophet["ds"] <= training_end)
    ]
    logger.info(
        "Training data: %s → %s | %d cities",
        train["ds"].min().date(), train["ds"].max().date(),
        train["CAR_RENTAL_CITY_NM"].nunique(),
    )

    # save training data
    training_path = os.path.join(results_dir, fc_cfg["training_filename"])
    train.to_csv(training_path, index=False)
    logger.info("Saved training data: %s", training_path)

    # --- run forecasting ---
    logger.info("Running Prophet forecasting...")
    predictions = run_forecasting(
        train=train,
        prediction_start_date=fc_cfg["prediction_start_date"],
        prediction_end_date=fc_cfg["prediction_end_date"],
    )

    if not predictions.empty:
        predictions_path = os.path.join(results_dir, fc_cfg["predictions_filename"])
        predictions.to_csv(predictions_path, index=False)
        logger.info("Saved predictions: %s", predictions_path)

    logger.info("Ground monitor complete.")


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run ground monitor forecasting pipeline.")
    parser.add_argument(
        "--config",
        default="config/config.json",
        help="Path to config JSON (default: config/config.json)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config = load_config(args.config)
    run_ground_monitor(config)


if __name__ == "__main__":
    main()
5yoy_forecast.py
"""
yoy_forecast.py
---------------
Loads Prophet predictions and actuals (output of ground_monitor.py),
computes weighted year-on-year (YoY) percentage change per city/car-type,
and saves the final forecast output CSV.

Pipeline position:  ground_monitor.py  -->  yoy_forecast.py

Usage:
    python yoy_forecast.py
    python yoy_forecast.py --config config/config.json
"""

import os
import json
import logging
import argparse
from datetime import datetime

import pandas as pd


# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s  %(levelname)-8s  %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(
            f"yoy_forecast_{datetime.now().strftime('%Y%m%d_%H%M%S')}.log"
        ),
    ],
)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def load_config(config_path: str) -> dict:
    """
    Load pipeline configuration from a JSON file.

    Parameters
    ----------
    config_path : str
        Path to the config JSON file.

    Returns
    -------
    dict
        Parsed configuration dictionary.
    """
    with open(config_path, "r") as f:
        return json.load(f)


# ---------------------------------------------------------------------------
# Data loaders
# ---------------------------------------------------------------------------

def load_actuals(filepath: str, start_date: str, end_date: str) -> pd.DataFrame:
    """
    Load Prophet training data (actuals) and filter to the YoY comparison window.

    Parameters
    ----------
    filepath : str
        Path to training CSV (e.g. Results_2025/Training_data_threshold_all_175.csv).
        Expected columns: ds, y, CAR_RENTAL_CITY_NM, CAR_TYPE_NM, CAR_RENTAL_COUNTRY_CD.
    start_date : str
        Start of actuals window (e.g. '2024-04-01').
    end_date : str
        End of actuals window (e.g. '2025-03-01').

    Returns
    -------
    pd.DataFrame
        Filtered actuals DataFrame with ds as datetime.
    """
    df = pd.read_csv(filepath)
    df["ds"] = pd.to_datetime(df["ds"])
    df = df[(df["ds"] >= start_date) & (df["ds"] <= end_date)]
    logger.info(
        "Actuals loaded: %s → %s | %d rows",
        df["ds"].min().date(), df["ds"].max().date(), len(df),
    )
    return df


def load_predictions(filepath: str, start_date: str, end_date: str) -> pd.DataFrame:
    """
    Load Prophet predictions and filter to the forecast window.

    Parameters
    ----------
    filepath : str
        Path to predictions CSV (e.g. Results_2025/predictions_threshold_all_175.csv).
        Expected columns: ds, yhat, yhat_lower, yhat_upper,
        CAR_RENTAL_CITY_NM, CAR_TYPE_NM, CAR_RENTAL_COUNTRY_CD.
    start_date : str
        Start of forecast window (e.g. '2025-04-01').
    end_date : str
        End of forecast window (e.g. '2026-03-01').

    Returns
    -------
    pd.DataFrame
        Filtered predictions DataFrame with ds as datetime.
    """
    df = pd.read_csv(filepath)
    df["ds"] = pd.to_datetime(df["ds"])
    df = df[(df["ds"] >= start_date) & (df["ds"] <= end_date)]
    logger.info(
        "Predictions loaded: %s → %s | %d rows",
        df["ds"].min().date(), df["ds"].max().date(), len(df),
    )
    return df


def load_weightage(filepath: str) -> pd.DataFrame:
    """
    Load the city/car-type weightage file (output of ground_monitor.py).

    Parameters
    ----------
    filepath : str
        Path to city_tier_usage_all_175.csv.
        Expected columns: CAR_RENTAL_CITY_NM, CAR_TYPE_NM,
        CAR_RENTAL_COUNTRY_CD, CAR_DAY_CT, weightage.

    Returns
    -------
    pd.DataFrame
        Weightage DataFrame.
    """
    df = pd.read_csv(filepath)
    logger.info("Weightage loaded: %d rows from %s", len(df), filepath)
    return df


# ---------------------------------------------------------------------------
# YoY computation
# ---------------------------------------------------------------------------

def compute_yoy(
    actuals: pd.DataFrame,
    predictions: pd.DataFrame,
    df_weightage: pd.DataFrame,
    country_cd_map: dict,
) -> pd.DataFrame:
    """
    Compute weighted year-on-year percentage change per city/car-type.

    Steps:
      1. Average actuals and predictions across the time window per city/type.
      2. Merge to get (actual_mean, forecast_mean) per city/type/country.
      3. Merge with weightage to get the car-day share per type within each city.
      4. Compute diff = (yhat - y) / y
      5. Add upper/lower bounds: yhat ±5%
      6. Compute weighted volumes for aggregation.
      7. Add full country name.

    Parameters
    ----------
    actuals : pd.DataFrame
        Filtered actuals with columns: ds, y, CAR_RENTAL_CITY_NM,
        CAR_TYPE_NM, CAR_RENTAL_COUNTRY_CD.
    predictions : pd.DataFrame
        Filtered predictions with columns: ds, yhat, yhat_lower, yhat_upper,
        CAR_RENTAL_CITY_NM, CAR_TYPE_NM, CAR_RENTAL_COUNTRY_CD.
    df_weightage : pd.DataFrame
        Weightage file with columns: CAR_RENTAL_CITY_NM, CAR_TYPE_NM,
        CAR_RENTAL_COUNTRY_CD, CAR_DAY_CT, weightage.
    country_cd_map : dict
        Mapping of country_code -> full country name.

    Returns
    -------
    pd.DataFrame
        Final DataFrame with YoY metrics, ready to save.
    """
    merge_cols = ["CAR_RENTAL_CITY_NM", "CAR_TYPE_NM", "CAR_RENTAL_COUNTRY_CD"]

    # --- average across time window ---
    df_actuals_avg = (
        actuals.groupby(merge_cols)["y"]
        .mean()
        .reset_index()
    )
    df_pred_avg = (
        predictions.groupby(merge_cols)["yhat"]
        .mean()
        .reset_index()
    )

    # --- merge actuals and predictions ---
    df_yoy = pd.merge(df_actuals_avg, df_pred_avg, on=merge_cols, how="inner")
    logger.info("YoY merge: %d city/type/country combinations", len(df_yoy))

    # --- merge weightage ---
    df_weighted = df_yoy.merge(df_weightage, on=merge_cols, how="left")

    # --- YoY % diff ---
    df_weighted["diff"] = (df_weighted["yhat"] - df_weighted["y"]) / df_weighted["y"]

    # --- upper/lower bounds (±5% of yhat) ---
    df_weighted["yhat_upper"] = df_weighted["yhat"] * 1.05
    df_weighted["yhat_lower"] = df_weighted["yhat"] * 0.95
    df_weighted["diff_up"]    = (df_weighted["yhat_upper"] - df_weighted["y"]) / df_weighted["y"]
    df_weighted["diff_low"]   = (df_weighted["yhat_lower"] - df_weighted["y"]) / df_weighted["y"]

    # --- name concat column ---
    df_weighted["Name_Con"] = (
        df_weighted["CAR_RENTAL_CITY_NM"] + " " + df_weighted["CAR_TYPE_NM"]
    )

    # --- volume-weighted factors for city-level rollup ---
    df_weighted["Weight"]        = df_weighted["weightage"] * df_weighted["CAR_DAY_CT"]
    df_weighted["Vol_factor"]    = df_weighted["Weight"] * df_weighted["diff"]
    df_weighted["Vol_factor_up"] = df_weighted["Weight"] * df_weighted["diff_up"]
    df_weighted["Vol_factor_low"] = df_weighted["Weight"] * df_weighted["diff_low"]

    # --- add full country name ---
    df_weighted["Country"] = df_weighted["CAR_RENTAL_COUNTRY_CD"].map(country_cd_map)

    return df_weighted


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run_yoy_forecast(config: dict) -> None:
    """
    Run the full YoY forecast pipeline:
      1. Load actuals, predictions, weightage, country reference.
      2. Compute weighted YoY % change.
      3. Select output columns and save final CSV.

    Parameters
    ----------
    config : dict
        Loaded configuration dictionary from config.json.

    Returns
    -------
    None
    """
    paths      = config["paths"]
    fc_cfg     = config["forecasting"]
    yoy_cfg    = config["yoy"]
    results_dir = fc_cfg["results_dir"]

    # --- load inputs ---
    actuals = load_actuals(
        filepath   = os.path.join(results_dir, fc_cfg["training_filename"]),
        start_date = yoy_cfg["actuals_start_date"],
        end_date   = yoy_cfg["actuals_end_date"],
    )
    predictions = load_predictions(
        filepath   = os.path.join(results_dir, fc_cfg["predictions_filename"]),
        start_date = yoy_cfg["predictions_start_date"],
        end_date   = yoy_cfg["predictions_end_date"],
    )
    df_weightage = load_weightage(
        os.path.join(results_dir, fc_cfg["weightage_filename"])
    )

    # --- country name map ---
    df_ref = pd.read_excel(paths["country_codes_file"])
    df_ref.dropna(inplace=True)
    country_cd_map = dict(zip(df_ref["country_code"], df_ref["Country"]))

    # --- compute YoY ---
    logger.info("Computing YoY...")
    df_final = compute_yoy(actuals, predictions, df_weightage, country_cd_map)

    # --- select output columns ---
    # VERIFY: yhat_lower appears twice in original source — check if yhat_upper
    #         should replace one of them in the final output
    output_cols = [
        "Country", "Name_Con", "CAR_RENTAL_CITY_NM", "CAR_TYPE_NM",
        "y", "yhat", "yhat_lower", "yhat_upper",
        "diff_up", "diff_low", "diff",
        "weightage", "weighted_forecast" if "weighted_forecast" in df_final.columns else "diff",
        "Weight", "CAR_DAY_CT",
        "Vol_factor", "Vol_factor_up", "Vol_factor_low",
    ]
    # keep only columns that actually exist to avoid KeyError
    output_cols = [c for c in output_cols if c in df_final.columns]

    # add weighted_forecast = sum of (diff * weightage) per city
    df_city_weighted = (
        df_final.groupby("CAR_RENTAL_CITY_NM")["Vol_factor"]
        .sum()
        .reset_index()
        .rename(columns={"Vol_factor": "weighted_forecast"})
    )
    df_final = df_final.merge(df_city_weighted, on="CAR_RENTAL_CITY_NM", how="left")

    final_cols = [
        "Country", "Name_Con", "CAR_RENTAL_CITY_NM", "CAR_TYPE_NM",
        "y", "yhat", "yhat_lower", "yhat_upper","yhat_lower"
        "diff_up", "diff_low", "diff",
        "weightage", "weighted_forecast",
        "Weight", "CAR_DAY_CT",
        "Vol_factor", "Vol_factor_up", "Vol_factor_low",
    ]
    df_out = df_final[[c for c in final_cols if c in df_final.columns]]

    # --- save ---
    out_path = os.path.join(results_dir, fc_cfg["final_forecast_filename"])
    df_out.to_csv(out_path, index=False)
    logger.info("Saved final forecast: %s", out_path)
    logger.info("YoY forecast complete.")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Compute YoY forecast from predictions.")
    parser.add_argument(
        "--config",
        default="config/config.json",
        help="Path to config JSON (default: config/config.json)",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    config = load_config(args.config)
    run_yoy_forecast(config)


if __name__ == "__main__":
    main()



