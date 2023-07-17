import argparse
import csv
from datetime import date as dtdate
from typing import Iterator, List, Optional, Type, TypeVar
from collections import defaultdict
from pydantic import BaseModel, ValidationError, Field


class Applicant(BaseModel):
    applicant_id: str
    first_name: str
    last_name: str
    application_date: dtdate

try:
    Applicant()
except ValidationError as exc:
    print(repr(exc.errors()[0]['type']))

class Employee(BaseModel):
    employee_id: str
    first_name: str
    last_name: str
    hire_date: dtdate = Field(description="Date of hire")
    term_date: Optional[dtdate] = None # Field(description="Date of termination")

try:
    Employee()
except ValidationError as exc:
    print(repr(exc.errors()[0]['type']))


T = TypeVar("T", Applicant, Employee)


def read_csv(cls: Type[T], filename: str) -> Iterator[T]:
    with open(filename, "r") as f:
        reader = csv.DictReader(f)
        for line in reader:
            filtered_line = {name: value for (name, value) in line.items() if value != ''}
            yield cls.model_validate(filtered_line)


class Match(BaseModel):
    employee_id: str
    employee_first_name: str
    employee_last_name: str
    applicant_id: str
    applicant_first_name: str
    applicant_last_name: str
    application_date: dtdate = Field(description="Date of application")
    employee_hire_date: dtdate = Field(description="Date of hire") 
    employee_term_date: Optional[dtdate] = None #Field(description="Date of termination")

    @classmethod
    def match(cls, applicants: List[Applicant], employees: List[Employee]) -> List["Match"]:
        applicants_by_name = {(applicant.first_name, applicant.last_name): applicant for applicant in applicants}
        employees_by_id = defaultdict(list)
        employees_by_name = defaultdict(list)
        
        for employee in employees:
            employees_by_id[employee.employee_id].append(employee)
            employees_by_name[employee.first_name + employee.last_name].append(employee)
        
        matches: List[Match] = []
        all_ids_to_map: List = []

        for employee in employees:
            this_employee_id = employee.employee_id
            group_of_employee_ids = employees_by_id.get(this_employee_id)
            first_name = employee.first_name.capitalize() # list(set([i.first_name.capitalize() for i in group_of_employee_ids]))
            last_name = employee.last_name.capitalize() # list(set([i.last_name.capitalize() for i in group_of_employee_ids]))
            applicant = applicants_by_name.get((first_name, last_name))
            if applicant:
                group_of_ids_to_map = [group_of_employee_ids, this_employee_id] # are these needed?
                all_ids_to_map.append(group_of_ids_to_map) # are these needed

                matches.append(
                    cls(
                        employee_id=employee.employee_id,
                        employee_first_name=employee.first_name.capitalize(),
                        employee_last_name=employee.last_name.capitalize(),
                        applicant_id=applicant.applicant_id,
                        applicant_first_name=applicant.first_name,
                        applicant_last_name=applicant.last_name,
                        application_date=applicant.application_date,
                        employee_hire_date=employee.hire_date,
                        employee_term_date=employee.term_date,
                    )
                )
        
        return matches

try:
    Match()
except ValidationError as exc:
    print(repr(exc.errors()[0]['type']))


def main() -> None:
    parser = argparse.ArgumentParser(
        description="A tool for matching HRIS (employee) and applicant (ATS) data. Applicants in the CSV file "
        "given by --applicant-csv will be matched to employees in the file given with --employee-csv, and the "
        "output will be written to --match-out-csv. The matching process uses employee and applicant names to "
        "determine that an employee and applicant are the same person."
    )
    parser.add_argument(
        "--applicant-csv",
        "-a",
        required=True,
        help="Path to a file containing applicant (ATS) data. The file should have the following headers: "
        f"{', '.join(Applicant.model_fields.keys())}. The first_name, last_name, and applicant_id "
        "headers may contain arbitrary strings. The application_date header should be a date in YYYY-MM-DD "
        "format."
    )
    parser.add_argument(
        "--employee-csv",
        "-e",
        required=True,
        help="Path to a file containing employee (HRIS) data. The file should have the following headers: "
        f"{', '.join(Employee.model_fields.keys())}. The first_name, last_name, and employee_id "
        "headers may contain arbitrary strings. The hire_date and term_date should be a date in YYYY-MM-DD "
        "format."
    )
    parser.add_argument(
        "--match-out-csv",
        "-o",
        help="Path to write matched employee/applicant data. The file will have the following headers: "
        f"{', '.join(Match.model_fields.keys())}. The data in the file exactly match "
        "the data from one row in --applicant-csv and one row in the --employee-id."
    )
    args = parser.parse_args()
    applicant_csv: str = args.applicant_csv
    employee_csv: str = args.employee_csv
    match_out_csv: Optional[str] = args.match_out_csv

    applicants = list(read_csv(Applicant, applicant_csv))
    print(f"{len(applicants)} applicants")

    employees = list(read_csv(Employee, employee_csv))
    print(f"{len(employees)} employees")

    matches = Match.match(applicants, employees)
    print(f"{len(matches)} matches")

    if match_out_csv is not None:
        print(f"Writing matches to {match_out_csv}")
        # Sort to make this CSV a little easier to read by hand
        matches = sorted(matches, key=lambda match: match.employee_id)
        with open(match_out_csv, "w") as f:
            writer = csv.DictWriter(f, Match.model_fields.keys())
            writer.writeheader()
            for match in matches:
                writer.writerow(match.model_dump())


if __name__ == "__main__":
    main()
