
# Applicant/Employee matcher

This tool loads data received from a client's HRIS (employee) and ATS (applicant) systems
and uses our fancy proprietary algorithm to match employees to applicants. This is necessary
because our questionnaire and model use applicant data in production, but the model needs
employee data (hire/termination dates) for training.

## Installation

You can setup this project using <setup.sh>:

```
./setup.sh
source venv/bin/activate
```

This should install the correct version of Python though pyenv and any necessary pip dependencies.

## Running

See the help output:

```
./matching.py --help
```

To run matching using the data in this repo:

```
./matching.py --applicant-csv ../data/applicants.csv --employee-csv ../data/employees.csv -o matches.csv
```

The matched output will be in `matches.csv` in the current folder.

## Running tests

You can run tests with

```
python -m pytest
```
