
from datetime import datetime



SITES = {
    "altamont_pass": {
        "name":             "altamont_pass",
        "lat":              37.737,
        "lon":              -121.641,
        "type":             "wind",       # "wind" or "solar"
        "hub_height":       100,          # meters — only used for wind sites
    },
    "mojave_solar": {
        "name":             "mojave_solar",
        "lat":              35.052,
        "lon":              -118.172,
        "type":             "solar",
        "hub_height":       None,         # not applicable for solar
    },
    "solano_wind": {
        "name":             "solano_wind",
        "lat":              38.163,
        "lon":              -121.982,
        "type":             "wind",
        "hub_height":       80,
    },
}



ACTIVE_SITE = "altamont_pass"


FORECAST_HOUR = 1


START_DATE = datetime(2024, 1, 1)
END_DATE   = datetime(2024, 1, 7)   # Start small — expand once pipeline works



CACHE_DIR  = "./hrrr_cache"         # Where raw GRIB2 files are cached locally
OUTPUT_DIR = "./data"               # Where cleaned CSVs are saved

WIND_SHEAR_ALPHA = 0.143


if ACTIVE_SITE not in SITES:
    raise ValueError(
        f"ACTIVE_SITE '{ACTIVE_SITE}' not found in SITES. "
        f"Available options: {list(SITES.keys())}"
    )

SITE      = SITES[ACTIVE_SITE]
SITE_NAME = SITE["name"]
SITE_LAT  = SITE["lat"]
SITE_LON  = SITE["lon"]
SITE_TYPE = SITE["type"]
TURBINE_HUB_HEIGHT = SITE["hub_height"]

OUTPUT_CSV = f"{OUTPUT_DIR}/hrrr_{SITE_NAME}_raw.csv"