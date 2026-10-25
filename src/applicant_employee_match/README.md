
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
python src/applicant_employee_match/matching.py --help
```

To run matching using the data in this repo, from the project directory, run the following:

```
python src/applicant_employee_match/matching.py --applicant-csv data/input/applicants.csv --employee-csv data/input/employees.csv -o data/output/matches.csv
```

The matched output will be in `matches.csv` in the data/output/ folder. The package also installs an
`applicant-employee-match` command, and `python -m applicant_employee_match` works too. All three run the same
code, so `uv run applicant-employee-match --help` gives the same help.

* Without `-o` (or with `-o -`) the CSV is written to standard output, so it can be piped. The summary
  (`Read 900 applicants ...`, `Found 600 matches`) and any warnings always go to standard error.
* Exit codes: `0` success, `1` missing or invalid input (the message names the file and line), `2` bad
  command-line arguments.
* The output file is opened only after both inputs have been read and validated, so a bad input never
  truncates the previous output. The tool also refuses to write its output over one of its inputs.

## How matching works

1. **Key.** An employee row and an applicant row match when their first names and last names are equal
   after normalisation: Unicode NFKC, case-folding, surrounding whitespace removed and inner runs of
   whitespace collapsed. `KATHERINE BUTLER` therefore matches `Katherine Butler`. Hyphens, apostrophes and
   accents still count, so `Price-Chavez` ≠ `Price Chavez`, `José` ≠ `Jose`, and nicknames don't
   match (`Kathy` ≠ `Katherine`). The job is not taken into account.
2. **One applicant per hire.** Each employee row is a hire and is matched on its own. A rehire (the same
   `employee_id` on a second row) produces a second match. An applicant can match several employee rows.
3. **Ties.** If several different applicants share the key, the match goes to the latest application on or
   before the hire date. If every application is after the hire date, it goes to the earliest one. On the
   same date, the lexicographically smallest `applicant_id` wins. These matches are counted in a warning.
4. **Duplicates.** Exact duplicate applicant rows count once. Exact duplicate employee rows produce a single
   match, and the number skipped is reported.
5. **Name collisions.** If one applicant matches more than one distinct `employee_id`, which probably
   means two people share a name, the run still succeeds and reports the count in a warning.
6. **Output.** The values are copied from the two input rows (trimmed, not re-capitalised). Rows are
   sorted by `employee_id` (as text), then hire date, then `applicant_id`, so the output does not depend on
   the order of the input rows.

The key is a parameter (`match_records(..., name_key=...)`), so fuzzier rules such as nickname tables,
hyphen/space folding or linking rows that share an `employee_id` can be plugged in without touching the
join. On the sample data: case-insensitive matching finds 600 matches. Folding hyphens and spaces would
add about 60 more, a nickname table about 200 more, and linking rows by `employee_id` about 100 more.

## Input format

* UTF-8 CSV with a header row. A byte-order mark (as Excel writes) is fine. Header names are matched
  case-insensitively and with surrounding whitespace ignored, columns may be in any order, and extra
  columns are ignored.
* Applicants: `applicant_id`, `first_name`, `last_name`, `application_date`. Employees: `employee_id`,
  `first_name`, `last_name`, `hire_date` and an optional `term_date`.
* Dates must be `YYYY-MM-DD`. An empty `term_date` means still employed, and `term_date` may not be
  before `hire_date`. IDs and names must be non-blank. Cell values are trimmed.
* A header-only file is valid and has zero rows. Rows whose cells are all empty are skipped. An
  empty file, missing or duplicated columns, a row with the wrong number of fields, a non-UTF-8 file or
  an invalid value stops the run with an error such as
  `data/input/employees.csv:42: hire_date='2019-13-01': Value error, expected a date in YYYY-MM-DD format, ...`.

## Performance

Matching is a hash join. Applicants are loaded into a dictionary keyed by name, and employee rows are
streamed past it, so the cost is O(A + E + M log M) time and O(A + M) memory for A applicants, E employee
rows and M matches. The log term is the final sort. With 1,000,000 applicants and 1,000,000 employee
rows (CPython 3.13, Apple Silicon), a run takes about 15 s and peaks at about 2 GB RSS. The previous
version took about 13 s and peaked at about 2.7 GB, because it held both files in memory. For inputs that
don't fit in memory, do the join in a database (for example DuckDB) instead.

## Using it as a library

```python
from applicant_employee_match.matching import match_records, read_applicants, read_employees, write_matches

result = match_records(read_applicants("data/input/applicants.csv"), read_employees("data/input/employees.csv"))
print(len(result.matches), result.ambiguous_matches, result.duplicate_employee_rows)
write_matches(result.matches, "matches.csv")
```

## Running tests

You can run tests with

```
uv run pytest
```

* `tests/test_matching.py`: the models and the matching rules, including a differential test against a
  brute-force version of the rules on seeded random data.
* `tests/test_io.py`: CSV parsing, validation and the error messages for malformed input.
* `tests/test_cli.py`: the command line end to end. This includes a check that `data/output/matches.csv`
  is exactly what the documented command produces from `data/input`. If you change the matching
  behaviour, regenerate that file with the command above and commit it together with the change.
