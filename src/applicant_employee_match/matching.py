import argparse
import csv
from collections.abc import Iterator
from datetime import date as dtdate
from typing import Self

from pydantic import BaseModel, Field


class Applicant(BaseModel):
    applicant_id: str
    first_name: str
    last_name: str
    application_date: dtdate


class Employee(BaseModel):
    employee_id: str
    first_name: str
    last_name: str
    hire_date: dtdate = Field(description="Date of hire")
    term_date: dtdate | None = None  # Field(description="Date of termination")


def read_csv[T: (Applicant, Employee)](cls: type[T], filename: str) -> Iterator[T]:
    with open(filename) as f:
        reader = csv.DictReader(f)
        for line in reader:
            filtered_line = {name: value for (name, value) in line.items() if value != ""}
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
    employee_term_date: dtdate | None = None  # Field(description="Date of termination")

    @classmethod
    def match(cls, applicants: list[Applicant], employees: list[Employee]) -> list[Self]:
        # Compare names case-insensitively on *both* sides. The previous version capitalized only
        # the employee's name, which fixed "KATHERINE BUTLER" but broke every compound surname
        # ("Price-Chavez" -> "Price-chavez", "Brown Alexander" -> "Brown alexander").
        def name_key(first_name: str, last_name: str) -> tuple[str, str]:
            return first_name.casefold(), last_name.casefold()

        applicants_by_name = {name_key(a.first_name, a.last_name): a for a in applicants}
        matches: list[Self] = []
        for employee in employees:
            applicant = applicants_by_name.get(name_key(employee.first_name, employee.last_name))
            if applicant is not None:
                matches.append(
                    cls(
                        employee_id=employee.employee_id,
                        employee_first_name=employee.first_name,
                        employee_last_name=employee.last_name,
                        applicant_id=applicant.applicant_id,
                        applicant_first_name=applicant.first_name,
                        applicant_last_name=applicant.last_name,
                        application_date=applicant.application_date,
                        employee_hire_date=employee.hire_date,
                        employee_term_date=employee.term_date,
                    )
                )
        return matches


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
        "format.",
    )
    parser.add_argument(
        "--employee-csv",
        "-e",
        required=True,
        help="Path to a file containing employee (HRIS) data. The file should have the following headers: "
        f"{', '.join(Employee.model_fields.keys())}. The first_name, last_name, and employee_id "
        "headers may contain arbitrary strings. The hire_date and term_date should be a date in YYYY-MM-DD "
        "format.",
    )
    parser.add_argument(
        "--match-out-csv",
        "-o",
        help="Path to write matched employee/applicant data. The file will have the following headers: "
        f"{', '.join(Match.model_fields.keys())}. The data in the file exactly match "
        "the data from one row in --applicant-csv and one row in the --employee-id.",
    )
    args = parser.parse_args()
    applicant_csv: str = args.applicant_csv
    employee_csv: str = args.employee_csv
    match_out_csv: str | None = args.match_out_csv

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
