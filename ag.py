# Car Rental Forecasting Pipeline

End-to-end pipeline to extract car rental transaction data from a Hive data
lake, clean and combine it, and generate city-level rate forecasts using
Facebook Prophet. Final output is a weighted year-on-year (YoY) % change
forecast per city and car type.

---

## Project Structure

```
car_rental_project/
│
├── config/
│   └── config.json                  # All settings: credentials, paths, dates, thresholds
│
├── data_and_other_files/
│   ├── all_codes_using_2023.xlsx    # Master country/city/currency reference
│   ├── currency_rates.csv           # Currency-to-USD conversion rates
│   └── Remove_combinations_2025.xlsx  # Manual city/car-type combos to exclude
│
├── ref/
│   ├── City1.xlsx                   # City ID → City name mapping
│   └── Agency.csv                   # Agency ID → Agency name mapping
│
├── sql/
│   └── fetch_car_rental.sql         # Hive query template (placeholders for country/year)
│
├── France_sweden/                   # Legacy FR/SE source files (pre-2021)
├── US/                              # Legacy US source files (pre-2021)
├── req_files/                       # Legacy combined files (pre-2021)
│
├── raw_data/{year}/                 # Output of fetch_data.py
├── clean/{year}/                    # Output of clean_data.py
├── combined_clean/                  # Output of combine_data.py
├── Results_{year}/                  # Output of ground_monitor.py and yoy_forecast.py
│
├── fetch_data.py                    # Step 1: Extract raw data from Hive
├── clean_data.py                    # Step 2: Clean and enrich raw CSVs
├── combine_data.py                  # Step 3: Combine per-country CSVs by year
├── ground_monitor.py                # Step 4: Outlier removal + Prophet forecasting
├── yoy_forecast.py                  # Step 5: YoY % change computation
│
├── requirements.txt                 # Python dependencies
└── README.md                        # This file
```

---

## Pipeline Overview

```
Hive Data Lake
      │
      ▼
fetch_data.py          → raw_data/{year}/{country}.csv
      │
      ▼
clean_data.py          → clean/{year}/{country_code}_CLEAN.csv
      │
      ▼
combine_data.py        → combined_clean/{year}_comb.csv
      │
      ▼
ground_monitor.py      → Results_{year}/predictions_threshold_all_175.csv
                         Results_{year}/Training_data_threshold_all_175.csv
                         Results_{year}/city_tier_usage_all_175.csv
      │
      ▼
yoy_forecast.py        → Results_{year}/Car_Rentals_Forecast_{year}_175.csv
```

---

## Setup

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

> **Note:** `jaydebeapi` and `JPype1` require Java to be installed on your machine.
> The Hive JDBC driver jar (`HiveJDBC42.jar`) must be placed in the project root directory.

### 2. Configure credentials and settings

Open `config/config.json` and fill in:

```json
"hive": {
    "jdbc_url":  "YOUR_JDBC_URL_HERE",
    "username":  "YOUR_USERNAME_HERE",
    "password":  "YOUR_PASSWORD_HERE"
}
```

All other settings (year, date ranges, thresholds, output folder name) are
also controlled from `config.json` — no need to touch any Python file for a
new year's run.

### 3. Place reference files

Make sure the following files are in place before running:

| File | Location |
|------|----------|
| `all_codes_using_2023.xlsx` | `data_and_other_files/` |
| `currency_rates.csv` | `data_and_other_files/` |
| `Remove_combinations_2025.xlsx` | `data_and_other_files/` |
| `City1.xlsx` | `ref/` |
| `Agency.csv` | `ref/` |
| `HiveJDBC42.jar` | project root |

---

## Running the Pipeline

Run each step in order:

```bash
python fetch_data.py
python clean_data.py
python combine_data.py
python ground_monitor.py
python yoy_forecast.py
```

### Overriding year or config path

Each script accepts optional command-line arguments:

```bash
# Use a different config file
python fetch_data.py --config config/config_2026.json

# Override the extraction year without editing config
python fetch_data.py --year 2024
```

---

## Configuration Reference

All settings live in `config/config.json`. Key sections:

| Section | Key | Description |
|---------|-----|-------------|
| `hive` | `jdbc_url` | Full Hive JDBC connection string |
| `hive` | `jar_filename` | Name of the JDBC driver jar (must be in project root) |
| `extraction` | `year` | Year to extract from Hive |
| `extraction` | `years_to_clean` | List of years to run through clean_data.py |
| `extraction` | `years_to_combine` | List of years to run through combine_data.py |
| `forecasting` | `training_start_date` | Start of Prophet training window |
| `forecasting` | `training_end_date` | End of Prophet training window |
| `forecasting` | `prediction_start_date` | Start of forecast period |
| `forecasting` | `prediction_end_date` | End of forecast period |
| `forecasting` | `results_dir` | Output folder name (e.g. `Results_2025`) |
| `yoy` | `actuals_start_date` | Start of actuals window for YoY comparison |
| `yoy` | `actuals_end_date` | End of actuals window for YoY comparison |
| `thresholds` | `uk_rate_threshold` | Max daily rate for UK in GBP (default: 120) |
| `thresholds` | `other_rate_threshold_usd` | Max daily rate for all others in USD (default: 175) |

---

## Output Files

| File | Description |
|------|-------------|
| `raw_data/{year}/{country}.csv` | Raw transaction data per country from Hive |
| `clean/{year}/{country_code}_CLEAN.csv` | Cleaned, enriched data per country |
| `combined_clean/{year}_comb.csv` | All countries combined for that year |
| `Results_{year}/Training_data_threshold_all_175.csv` | Final training data used by Prophet |
| `Results_{year}/predictions_threshold_all_175.csv` | Prophet forecasts per city/type |
| `Results_{year}/city_tier_usage_all_175.csv` | Car-day weightage per city/type |
| `Results_{year}/Car_Rentals_Forecast_{year}_175.csv` | **Final YoY forecast output** |

---

## Logging

Each script writes a timestamped log file to the project root:

```
fetch_data_20250307_143022.log
clean_data_20250307_143045.log
...
```

Logs include row counts at each stage, skipped countries, model fitting
progress, and any errors encountered.

---

## Known Issues / Items to Verify

The following items were flagged during development and should be confirmed
before the final run:

- **Agency list incomplete** — `get_approved_agencies()` in `clean_data.py`
  only has entries for AE, AR, AU. Remaining 25 countries need to be filled in.

- **2020 FR/SE data split** — `ground_monitor.py` loads 2020 data from two
  separate source files (one for FR/SE, one for all others). Confirm with
  manager that this split is intentional.

- **City1.xlsx column name** — verify the exact column name for city name in
  `City1.xlsx` matches `"CAR CITY NAME"` used in `clean_data.py`.

- **Remove_combinations column name** — verify that `CAR_TYPE_1` is the
  correct column name in `Remove_combinations_2025.xlsx`.

- **NEWMAN city name** — confirm spelling in `ground_monitor.py` special
  cases (may have been distorted by OCR).

- **yhat_lower / yhat_upper** — original source had `yhat_lower` listed
  twice in output columns. Verify the final output CSV in `yoy_forecast.py`
  has both `yhat_lower` and `yhat_upper` correctly.
