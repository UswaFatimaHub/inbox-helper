"""Offline evaluation of the inbox helper against a golden dataset (deepeval).

Run from the project root, e.g. `evals\\.venv\\Scripts\\python -m evals.run_eval --results out\\results.json`.
See evals/README.md.
"""
import os
import sys
from pathlib import Path

sys.dont_write_bytecode = True  # importing inbox_helper from here must not write into the app's __pycache__

# deepeval reads these at import time, so they are set before any submodule imports it. Keep its scratch files
# inside evals/ (it defaults to ./.deepeval in the cwd), skip telemetry, and stop it auto-loading the project's
# .env: API keys are read by inbox_helper.config.load_api_keys like the app does.
_EVAL_DIR = Path(__file__).resolve().parent
os.environ.setdefault("DEEPEVAL_CACHE_FOLDER", str(_EVAL_DIR / ".deepeval"))
os.environ.setdefault("DEEPEVAL_TELEMETRY_OPT_OUT", "YES")
os.environ.setdefault("DEEPEVAL_DISABLE_DOTENV", "1")
os.environ.setdefault("DEEPEVAL_EVAL_MODE", "llm")
