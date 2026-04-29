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
        "currency_rates_file": "data_and_other_files/currency_rates.csv",
        "sql_file": "sql/fetch_car_rental.sql",
        "raw_data_dir": "raw_data",
        "clean_data_dir": "clean",
        "combined_data_dir": "combined_clean",
        "ref_city_file": "ref/City1.xlsx",
        "ref_agency_file": "ref/Agency.csv",
        "legacy_fr_se_12_18": "France_sweden/12-18FR_SE.csv",
        "legacy_fr_se_19_23": "France_sweden/FR_SEltd19-23Comb_datanf.csv",
        "legacy_us_12_18": "US/US_1218_CLEAN.csv",
        "legacy_wu1218": "req_files/wu1218_Comb_data.csv",
        "legacy_2019": "req_files/19Comb_data.csv",
        "legacy_2020_2023": "req_files/20-23Comb_data.csv",
        "remove_combinations_file": "data_and_other_files/Remove_combinations_2025.xlsx"
    },
    "extraction": {
        "year": 2025,
        "years_to_clean": [2024, 2025],
        "years_to_combine": [2024, 2025]
    },
    "forecasting": {
        "training_start_date": "2012-01-01",
        "training_end_date": "2025-03-01",
        "prediction_start_date": "2025-04-01",
        "prediction_end_date": "2026-06-01",
        "results_dir": "Results_2025",
        "predictions_filename": "predictions_threshold_all_175.csv",
        "training_filename": "Training_data_threshold_all_175.csv",
        "weightage_filename": "city_tier_usage_all_175.csv",
        "final_forecast_filename": "Car_Rentals_Forecast_2025_175.csv"
    },
    "yoy": {
        "actuals_start_date": "2024-04-01",
        "actuals_end_date": "2025-03-01",
        "predictions_start_date": "2025-04-01",
        "predictions_end_date": "2026-03-01"
    },
    "thresholds": {
        "uk_rate_threshold": 120,
        "other_rate_threshold_usd": 175
    }
}
