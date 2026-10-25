
# Applicant/Employee matcher

This tool loads data received from a client's HRIS (employee) and ATS (applicant) systems
and uses our fancy proprietary algorithm to match employees to applicants. This is necessary
because our questionnaire and model use applicant data in production, but the model needs
employee data (hire/termination dates) for training.

## Installation

This project is managed with [uv](https://docs.astral.sh/uv/). It supports Python 3.13+, and
`.python-version` pins the interpreter used for development (3.15).

From the project directory, create the `.venv` virtual environment and install the package plus its
dev tools (pytest, ruff, mypy) from `uv.lock`:
```
uv sync
```
uv downloads the pinned Python if it isn't installed yet.

Either prefix the commands below with `uv run` (for example `uv run python -m pytest`), or activate
the environment first:
```
source .venv/bin/activate
```

Lint, format, type and test checks:
```
uv run ruff check
uv run ruff format --check
uv run mypy
uv run pytest
```

## Running

See the help output:

```
src/applicant_employee_match/matching.py --help
```

The package also installs an `applicant-employee-match` command, so `uv run applicant-employee-match --help`
works too.

To run matching using the data in this repo, from the project directory, run the following:

```
python src/applicant_employee_match/matching.py --applicant-csv data/input/applicants.csv --employee-csv data/input/employees.csv -o data/output/matches.csv
```

The matched output will be in `matches.csv` in the data/output/ folder.

## Running tests

You can run tests with

```
python -m pytest
```
