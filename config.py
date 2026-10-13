"""Every tunable assumption lives here, so the scoring is easy to audit and change."""
import os

# --- data sources (all public, no key) ---
# Monthly passengers, seats and departures per airport. T-100 is the US Department of
# Transportation's report of airline traffic; BTS is the Bureau of Transportation Statistics.
T100_URL = "https://data.bts.gov/resource/r495-tyji.json"

# Live airport delay programmes (ground stops, delays). FAA is the Federal Aviation
# Administration; NAS is the National Airspace System.
FAA_STATUS_URL = "https://nasstatus.faa.gov/api/airport-status-information"
FAA_CACHE_TTL_S = 60              # the feed covers every airport, so one fetch serves a whole comparison
FAA_ERROR_TTL_S = 10              # a failed fetch is remembered briefly, so a down feed is not retried per airport

# Airport list: code, name, city, state, keywords. OurAirports is a public community dataset.
AIRPORTS_URL = "https://davidmegginson.github.io/ourairports-data/airports.csv"

# Runways per airport, used to count open runways.
RUNWAYS_URL = "https://davidmegginson.github.io/ourairports-data/runways.csv"

# Region names and codes (country, state); used here for US state names and postal codes.
STATES_URL = "https://davidmegginson.github.io/ourairports-data/regions.csv"

# One month of flight-level On-Time Performance (delays, taxi-out time, distance), as a zip.
# *The "1987_present" is part of BTS’s name for the whole dataset
ONTIME_URL = ("https://transtats.bts.gov/PREZIP/"
              "On_Time_Reporting_Carrier_On_Time_Performance_1987_present_{year}_{month}.zip")

ONTIME_YEAR, ONTIME_MONTH = 2026, 4
ONTIME_PERIOD = f"{ONTIME_YEAR}-{ONTIME_MONTH:02d}"

# --- local data store (git-ignored; filled at server start or by `python -m airdata`) ---
DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
T100_CSV = os.path.join(DATA_DIR, "t100_monthly.csv")
AIRPORTS_CSV = os.path.join(DATA_DIR, "airports.csv")
STATES_CSV = os.path.join(DATA_DIR, "states.csv")
ONTIME_CSV = os.path.join(DATA_DIR, f"ontime_{ONTIME_YEAR}_{ONTIME_MONTH:02d}.csv")

# --- fetching ---
HTTP_TIMEOUT_S = 60               # seconds, for every download except the on-time zip
ONTIME_TIMEOUT_S = 900            # the on-time zip is ~30 MB
T100_ROW_LIMIT = 500_000          # rows requested from the T-100 API in one call

# --- scoring assumptions ---
WINDOW_MONTHS = 12                # "last 12 months" window for annual figures
DAYS_PER_YEAR = 365
MIN_ANNUAL_PASSENGERS = 100_000   # peer set: airports with real commercial service
LONG_HAUL_MILES = 2_500           # ~4,000 km, the usual long-haul cut-off
COMFORT_LOAD_FACTOR = 80.0        # above this, flights start turning passengers away
GROWTH_YEARS = 3

# Expansion score = weighted sum of percentile ranks (0-100) within the peer set.
EXPANSION_WEIGHTS = {
    "load_factor": 0.35,        # planes are full -> demand is pressing on supply
    "passenger_growth": 0.30,   # demand is still rising
    "volume": 0.20,             # bigger airport -> bigger payoff per % of capacity added
    "airfield_headroom": 0.15,  # runways can take more flights, so a terminal is the fix
}
UNKNOWN_GROWTH_RANK = 50          # an airport with no growth history is scored as median

# Alternative weightings used only to test how much a rank depends on the judgement call
# above. Each must have the same keys as EXPANSION_WEIGHTS and sum to 1.
SENSITIVITY_WEIGHTS = {
    "equal": {"load_factor": 0.25, "passenger_growth": 0.25, "volume": 0.25,
              "airfield_headroom": 0.25},
    "growth-heavy": {"load_factor": 0.25, "passenger_growth": 0.50, "volume": 0.10,
                     "airfield_headroom": 0.15},
    "volume-heavy": {"load_factor": 0.25, "passenger_growth": 0.15, "volume": 0.45,
                     "airfield_headroom": 0.15},
}
RANK_STABLE_SPREAD = 5            # best-to-worst rank spread up to this counts as robust
ROBUST_TOP_N = 10                 # so does staying inside this many places under every weighting

# --- thresholds for the written reasons (scoring.drivers) ---
CONGESTED_INDEX = 75              # congestion index at or above this: airfield is the limit
HEADROOM_INDEX = 40               # at or below this: the airfield can take more flights
GROWTH_GAP_POINTS = 1             # passenger vs seat growth must differ by more than this
SEASONAL_PEAK_RATIO = 1.25        # peak month / average month
FAST_GROWTH_PCT = 5               # passenger growth per year

# --- LLM ---
OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://localhost:11434")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "qwen2.5:7b")
OLLAMA_NUM_CTX = 8192             # Ollama defaults to 4096 and silently drops what does not fit
OLLAMA_TIMEOUT_S = 300            # a local 7-8B model can take minutes on CPU
DEFAULT_TOP_N = 5                 # airports returned by rank_airports when none is asked for
MAX_TOP_N = 25                    # upper bound on what a user (or the model) can ask for

# --- web app ---
PORT = 5000
