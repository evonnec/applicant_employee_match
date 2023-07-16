
# Applicant/Employee matcher

This tool loads data received from a client's HRIS (employee) and ATS (applicant) systems
and uses our fancy proprietary algorithm to match employees to applicants. This is necessary
because our questionnaire and model use applicant data in production, but the model needs
employee data (hire/termination dates) for training.

## Installation

From the project directory, setup this project using a python environment and pyproject-toml:

create a virtual environment called `dev`
```
python -m venv dev
```

source the virtual environment called `dev`
```
source dev/bin/activate
```
This installs the .python-version for the virtual environment.  
  
install dependencies for the project  
```
pip install -e .
```
  
This should install the correct version of Python though pyenv and any necessary pip dependencies.  

## Running

See the help output:

```
src/applicant_employee_match/matching.py --help
```

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
