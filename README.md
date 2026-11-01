# Applicant–Employee Match

Match the people in an applicant tracking system (ATS) to the employees they became in an HR information
system (HRIS).

The two systems are exported separately and share no identifier, so nothing in the data says that the person who
applied for a job is the person who was hired. This tool reads one CSV from each system, matches every hire to
its application by first and last name, and writes one row per hire with the applicant and employee records side
by side. That joined view lets what is known at application time be analysed against what happened after the
hire, such as tenure.

It is a command-line tool and a small Python library. Its only runtime dependency is
[pydantic](https://docs.pydantic.dev/), which validates the input rows.

## Quick start

You need [uv](https://docs.astral.sh/uv/). It installs the Python version the project pins if you don't have it.

```
uv sync
uv run applicant-employee-match -a data/input/applicants.csv -e data/input/employees.csv -o data/output/matches.csv
```

The run summary goes to standard error:

```
Read 900 applicants from data/input/applicants.csv
Read 1100 employees from data/input/employees.csv
Found 600 matches
```

Without `-o` the CSV is written to standard output, so it can be piped. `python -m applicant_employee_match` and
`python src/applicant_employee_match/matching.py` run the same code.

As a library:

```python
from applicant_employee_match.matching import match_records, read_applicants, read_employees, write_matches

result = match_records(read_applicants("data/input/applicants.csv"), read_employees("data/input/employees.csv"))
write_matches(result.matches, "matches.csv")
```

## Input and output

* Applicants: `applicant_id`, `first_name`, `last_name`, `application_date`.
* Employees: `employee_id`, `first_name`, `last_name`, `hire_date` and an optional `term_date`.
* Both are UTF-8 CSV files with a header row and `YYYY-MM-DD` dates. Invalid input stops the run with an error
  that names the file and line.
* The output has one row per hire. In the sample data, applicant 251 (Richard Bennett, applied 2016-03-25) and
  employee 1003 (Richard Bennett, hired 2016-04-13, left 2017-07-24) become
  `1003,Richard,Bennett,251,Richard,Bennett,2016-03-25,2016-04-13,2017-07-24`.

## How matching works

* An applicant and an employee match when their first and last names are equal after Unicode normalisation,
  case-folding and whitespace clean-up, so `KATHERINE BUTLER` matches `Katherine Butler`. Hyphens, apostrophes,
  accents and nicknames still count as differences: `Price-Chavez` ≠ `Price Chavez` and `Kathy` ≠ `Katherine`.
  The job is not used.
* Each employee row is a hire and is matched on its own. When several applicants share the name, the match goes to
  the latest application on or before the hire date. Ties are broken the same way every time, so the output does
  not depend on the order of the input rows.
* Exact duplicate rows count once. Applicants whose name matches more than one employee are reported as warnings.
* The output file is written atomically, only after both inputs have been read and validated.
* The name comparison is a parameter (`match_records(..., name_key=...)`), so fuzzier rules such as nickname
  tables or hyphen folding can be added without changing the join.

The rules in full, with the input format, exit codes, performance and the test suite, are in
[src/applicant_employee_match/README.md](src/applicant_employee_match/README.md).

## What is in the repository

| Path | What it is |
| --- | --- |
| `src/applicant_employee_match/matching.py` | Data models, matching logic, CSV I/O and the CLI |
| `src/applicant_employee_match/README.md` | Detailed documentation: matching rules, input format, performance, library use |
| `data/input/` | Sample ATS (applicants) and HRIS (employees) exports |
| `data/output/matches.csv` | The output for the sample input; a test checks that it is reproducible |
| `tests/` | Unit, I/O, end-to-end and property-based (hypothesis) tests |
| `.github/workflows/ci.yml` | Continuous integration (see below) |
| `pyproject.toml`, `uv.lock` | Project metadata and the locked dependencies, managed with uv |
| `renovate.json` | Renovate configuration: monthly dependency updates, with minor and patch updates grouped |

## Development

The package supports Python 3.13 and later; `.python-version` pins 3.15 for development. The checks are:

```
uv run pytest
uv run ruff check
uv run ruff format --check
uv run mypy
```

CI runs the tests on Python 3.13, 3.14 and 3.15, plus lint, format and type checks. It then builds the package and
smoke-tests the installed `applicant-employee-match` command. Tagging a release (`v*`) runs the same checks and then
publishes with PyPI Trusted Publishing.

If you change the matching behaviour, regenerate `data/output/matches.csv` with the command in the quick start and
commit it together with the change.

## License

GNU General Public License v3. See [LICENSE](LICENSE).
