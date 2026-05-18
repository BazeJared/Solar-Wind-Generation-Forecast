import pandas as pd
import numpy as np
from datetime import datetime, timedelta
import herbie
import warnings

warnings.filterwarnings("ignore")


from config import (
    SITE_NAME,
    SITE_LAT,
    SITE_LON,
    SITE_TYPE,
    TURBINE_HUB_HEIGHT,
    START_DATE,
    END_DATE,
    FORECAST_HOUR,
    OUTPUT_CSV,
    CACHE_DIR,
    WIND_SHEAR_ALPHA,
)



WIND_VARS = {
    "u_wind_10m": ":UGRD:10 m above ground",  # U-component wind at 10m (m/s)
    "v_wind_10m": ":VGRD:10 m above ground",  # V-component wind at 10m (m/s)
    "u_wind_80m": ":UGRD:80 m above ground",  # U-component wind at 80m (m/s)
    "v_wind_80m": ":VGRD:80 m above ground",  # V-component wind at 80m (m/s)
    "temp_2m": ":TMP:2 m above ground",  # Temperature at 2m (K)
    "pressure_sfc": ":PRES:surface",  # Surface pressure (Pa)
}

SOLAR_VARS = {
    "ghi": ":DSWRF:surface",  # Downward shortwave radiation (W/m²) ≈ GHI
    "temp_2m": ":TMP:2 m above ground",  # Temperature (K) — affects panel efficiency
    "cloud_cover": ":TCDC:entire atmosphere",  # Total cloud cover (%)
    "u_wind_10m": ":UGRD:10 m above ground",  # Wind for panel cooling
    "v_wind_10m": ":VGRD:10 m above ground",
}

VARS_TO_EXTRACT = WIND_VARS if SITE_TYPE == "wind" else SOLAR_VARS



def extract_point_value(H, search_string, lat, lon):

    try:
        ds = H.xarray(search_string, remove_grib=True)

        # Find nearest grid point index
        # HRRR uses a Lambert Conformal grid — xarray handles this via coords
        lat_arr = ds.latitude.values
        lon_arr = ds.longitude.values

        # Compute distance to target point
        dist = np.sqrt((lat_arr - lat) ** 2 + (lon_arr - lon) ** 2)
        idx = np.unravel_index(np.argmin(dist), dist.shape)

        # Extract the variable value (first field if time dim exists)
        var_name = [v for v in ds.data_vars][0]
        value = float(ds[var_name].values[idx])
        return value

    except Exception as e:
        print(f"    Warning: Could not extract '{search_string}': {e}")
        return None


def wind_speed_from_components(u, v):
    if u is None or v is None:
        return None
    return np.sqrt(u ** 2 + v ** 2)


def wind_direction_from_components(u, v):
    if u is None or v is None:
        return None
    direction = (270 - np.degrees(np.arctan2(v, u))) % 360
    return direction


def extrapolate_wind_to_hub_height(wspd_10m, hub_height=100, ref_height=10, alpha=WIND_SHEAR_ALPHA):
    if wspd_10m is None:
        return None
    return wspd_10m * (hub_height / ref_height) ** alpha


def kelvin_to_celsius(temp_k):
    if temp_k is None:
        return None
    return temp_k - 273.15


# ─────────────────────────────────────────────
# 4. MAIN DATA COLLECTION LOOP
# ─────────────────────────────────────────────

def collect_hrrr_data(start_date, end_date, lat, lon, forecast_hour=1):
    records = []
    current = start_date

    while current <= end_date:
        for hour in range(0, 24):  # All 24 UTC initialization times
            run_time = current.replace(hour=hour)
            print(f"Fetching HRRR: {run_time.strftime('%Y-%m-%d %Hz')} F{forecast_hour:02d}...")

            try:
                # Initialize Herbie — auto-selects best available mirror (AWS recommended)
                H = herbie.Herbie(
                    run_time.strftime("%Y-%m-%d %H:%M"),
                    model="hrrr",
                    product="sfc",  # Surface fields (use "prs" for pressure levels)
                    fxx=forecast_hour,
                    save_dir=CACHE_DIR,
                    overwrite=False,
                )

                # Valid time = initialization time + forecast hour
                valid_time = run_time + timedelta(hours=forecast_hour)

                record = {
                    "init_time": run_time,
                    "valid_time": valid_time,
                    "fxx": forecast_hour,
                }

                # Extract each variable
                for var_key, search_str in VARS_TO_EXTRACT.items():
                    record[var_key] = extract_point_value(H, search_str, lat, lon)

                # ── Derived variables ──────────────────────────────────────
                if SITE_TYPE == "wind":
                    # Wind speed & direction at 10m
                    record["wspd_10m"] = wind_speed_from_components(
                        record.get("u_wind_10m"), record.get("v_wind_10m")
                    )
                    record["wdir_10m"] = wind_direction_from_components(
                        record.get("u_wind_10m"), record.get("v_wind_10m")
                    )
                    # Wind speed & direction at 80m (if available)
                    record["wspd_80m"] = wind_speed_from_components(
                        record.get("u_wind_80m"), record.get("v_wind_80m")
                    )
                    # Extrapolate to hub height from 10m baseline
                    record[f"wspd_{TURBINE_HUB_HEIGHT}m_extrap"] = extrapolate_wind_to_hub_height(
                        record["wspd_10m"], hub_height=TURBINE_HUB_HEIGHT
                    )
                    record["temp_c"] = kelvin_to_celsius(record.get("temp_2m"))

                elif SITE_TYPE == "solar":
                    record["temp_c"] = kelvin_to_celsius(record.get("temp_2m"))
                    # Panel efficiency degrades above 25°C — useful feature later
                    record["temp_above_stc"] = max(0, (record["temp_c"] or 0) - 25)
                    record["wspd_10m"] = wind_speed_from_components(
                        record.get("u_wind_10m"), record.get("v_wind_10m")
                    )

                records.append(record)

            except Exception as e:
                print(f"  ERROR on {run_time}: {e}")
                continue

        current += timedelta(days=1)

    return pd.DataFrame(records)



def quality_check(df):
    print("\n── Quality Check ─────────────────────────────")
    print(f"Total records:    {len(df)}")
    print(f"Missing values:\n{df.isnull().sum()}")

    if SITE_TYPE == "wind":
        if "wspd_10m" in df.columns:
            print(f"\nWind speed 10m — min: {df['wspd_10m'].min():.2f}, "
                  f"max: {df['wspd_10m'].max():.2f}, "
                  f"mean: {df['wspd_10m'].mean():.2f} m/s")
        if f"wspd_{TURBINE_HUB_HEIGHT}m_extrap" in df.columns:
            print(f"Wind speed {TURBINE_HUB_HEIGHT}m  — min: {df[f'wspd_{TURBINE_HUB_HEIGHT}m_extrap'].min():.2f}, "
                  f"max: {df[f'wspd_{TURBINE_HUB_HEIGHT}m_extrap'].max():.2f} m/s")

    elif SITE_TYPE == "solar":
        if "ghi" in df.columns:
            # GHI should be 0 at night — flag negative values
            neg_ghi = (df["ghi"] < -5).sum()
            print(f"\nGHI — max: {df['ghi'].max():.1f} W/m², "
                  f"negative values: {neg_ghi} (should be ~0)")

    print("──────────────────────────────────────────────\n")
    return df


if __name__ == "__main__":
    print(f"Collecting HRRR data for: {SITE_NAME} ({SITE_LAT}°N, {SITE_LON}°E)")
    print(f"Date range: {START_DATE.date()} → {END_DATE.date()}")
    print(f"Site type: {SITE_TYPE}\n")

    df = collect_hrrr_data(
        start_date=START_DATE,
        end_date=END_DATE,
        lat=SITE_LAT,
        lon=SITE_LON,
        forecast_hour=FORECAST_HOUR,
    )

    df = quality_check(df)

    # Save to CSV
    df.to_csv(OUTPUT_CSV, index=False)
    print(f"Saved {len(df)} records → {OUTPUT_CSV}")
    print(df.head())

# ─────────────────────────────────────────────
# NEXT STEPS (after this script runs clean):
# ─────────────────────────────────────────────
# 1. Download CAISO actual generation → hrrr_caiso_actuals.py
# 2. Merge HRRR features with actuals on valid_time
# 3. Engineer lag features, cyclical time encodings
# 4. Train baseline persistence model
# 5. Train LSTM and compare