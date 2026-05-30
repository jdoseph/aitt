# AI Value Chain Trading Agent — task shortcuts.
#   Install just: https://github.com/casey/just  (or: cargo install just / winget install casey.just)
#   Run `just` with no args to list recipes.
#
# All recipes use the project virtualenv interpreter so they work without a
# pre-activated venv (the project lives under OneDrive; see CLAUDE.md).

py := ".venv/Scripts/python.exe"

# List available recipes.
default:
    @just --list

# Run the full test suite.
test:
    {{py}} -m pytest tests/ -q

# Strict type check.
types:
    {{py}} -m mypy --strict src

# Tests + types (the pre-commit gate).
check: test types

# Run a single evaluation cycle now (fetch -> evaluate -> alert), then exit.
fetch-once:
    {{py}} -m src.agent --once

# Evaluate using prices already in the DB (no network fetch).
eval-cached:
    {{py}} -m src.agent --once --no-fetch

# Check the watchlist loads and every ticker is fetchable.
validate:
    {{py}} -m src.agent --validate

# Run the background agent (daily-close scheduler; Ctrl-C to stop).
run-agent:
    {{py}} -m src.agent

# Launch the Streamlit dashboard at http://localhost:8501.
run-dashboard:
    {{py}} -m streamlit run src/dashboard/app.py
