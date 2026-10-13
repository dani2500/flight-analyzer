"""`python -m airdata [--force]`: download the datasets and print their status."""
import json
import sys

from airdata import store

print(json.dumps(store.prepare(force="--force" in sys.argv), indent=1))
