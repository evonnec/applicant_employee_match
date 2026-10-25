"""Tests for CSV reading (validation, malformed input) and writing."""

import csv
from collections.abc import Callable
from datetime import date
from pathlib import Path

import pytest

from applicant_employee_match.matching import (
    MATCH_COLUMNS,
    Applicant,
    Employee,
    InputDataError,
    Match,
    read_applicants,
    read_csv,
    read_employees,
    write_matches,
)

MakeCsv = Callable[..., Path]  # the `make_csv` fixture from conftest.py

APPLICANT_HEADER = "applicant_id,application_date,first_name,last_name\r\n"
EMPLOYEE_HEADER = "employee_id,hire_date,first_name,last_name,term_date\r\n"


def test_reads_valid_applicants(make_csv: MakeCsv) -> None:
    path = make_csv(
        "a.csv",
        APPLICANT_HEADER + "1,2012-01-28,Robert,Scott\r\n2,2012-02-04,Brandon,Torres\r\n",
    )
    assert list(read_applicants(path)) == [
        Applicant(
            applicant_id="1",
            application_date=date(2012, 1, 28),
            first_name="Robert",
            last_name="Scott",
        ),
        Applicant(
            applicant_id="2",
            application_date=date(2012, 2, 4),
            first_name="Brandon",
            last_name="Torres",
        ),
    ]


def test_reads_employees_with_and_without_term_date(make_csv: MakeCsv) -> None:
    path = make_csv(
        "e.csv",
        EMPLOYEE_HEADER + "1496,2012-08-27,KATHERINE,BUTLER,2015-02-21\n1009,2018-11-08,John,Sullivan,\n",
    )
    first, second = read_employees(path)
    assert first.term_date == date(2015, 2, 21)
    assert second.term_date is None


def test_header_is_flexible_and_extra_columns_are_ignored(make_csv: MakeCsv) -> None:
    text = " Last_Name ,FIRST_NAME,notes,application_date,applicant_id\n  Scott , Robert ,hello,2012-01-28, 1 \n"
    [applicant] = read_csv(Applicant, make_csv("a.csv", text))
    assert applicant == Applicant(
        applicant_id="1",
        first_name="Robert",
        last_name="Scott",
        application_date=date(2012, 1, 28),
    )


def test_optional_column_may_be_absent(make_csv: MakeCsv) -> None:
    path = make_csv("e.csv", "employee_id,hire_date,first_name,last_name\n1,2012-08-27,Ann,Lee\n")
    assert [e.term_date for e in read_employees(path)] == [None]


def test_header_only_file_yields_nothing(make_csv: MakeCsv) -> None:
    assert list(read_applicants(make_csv("a.csv", APPLICANT_HEADER))) == []


def test_utf8_bom_is_accepted(make_csv: MakeCsv) -> None:
    path = make_csv("a.csv", APPLICANT_HEADER + "1,2012-01-28,José,Núñez\n", encoding="utf-8-sig")
    [applicant] = read_applicants(path)
    assert (applicant.first_name, applicant.last_name) == ("José", "Núñez")


def test_blank_rows_are_skipped(make_csv: MakeCsv) -> None:
    path = make_csv("a.csv", APPLICANT_HEADER + "\r\n1,2012-01-28,Robert,Scott\r\n,,,\r\n  \r\n")
    assert [a.applicant_id for a in read_applicants(path)] == ["1"]


def test_quoted_fields_and_line_numbers_after_multiline_records(
    make_csv: MakeCsv,
) -> None:
    text = APPLICANT_HEADER + '1,2012-01-28,"Robert","Scott, Jr."\n2,2012-01-29,"Multi\nLine",Name\n3,bad-date,A,B\n'
    path = make_csv("a.csv", text)
    with pytest.raises(InputDataError, match=r"a\.csv:5: application_date='bad-date'"):
        list(read_applicants(path))
    assert next(read_applicants(path)).last_name == "Scott, Jr."


@pytest.mark.parametrize(
    ("text", "message"),
    [
        ("", "file is empty"),
        (
            "applicant_id,first_name,last_name\n",
            "missing required column(s): application_date",
        ),
        (
            "id,first,last,date\n",
            "missing required column(s): applicant_id, first_name, last_name, application_date",
        ),
        (
            "applicant_id,application_date,first_name,last_name,First_Name\n",
            "duplicate column(s) in header: first_name",
        ),
        (APPLICANT_HEADER + "1,2012-01-28,Robert\n", ":2: expected 4 fields, got 3"),
        (
            APPLICANT_HEADER + "1,2012-01-28,Robert,Scott,extra\n",
            ":2: expected 4 fields, got 5",
        ),
        (
            APPLICANT_HEADER + "1,2012-01-28,Robert,Scott\n2,2012-13-01,Ann,Lee\n",
            ":3: application_date='2012-13-01'",
        ),
        (
            APPLICANT_HEADER + "1,01/28/2012,Robert,Scott\n",
            "expected a date in YYYY-MM-DD format",
        ),
        (
            APPLICANT_HEADER + "1,2012-01-28,   ,Scott\n",
            ":2: first_name: value is required",
        ),
        (
            APPLICANT_HEADER + ",2012-01-28,Robert,Scott\n",
            ":2: applicant_id: value is required",
        ),
    ],
)
def test_invalid_applicant_files_raise_with_location(make_csv: MakeCsv, text: str, message: str) -> None:
    with pytest.raises(InputDataError) as excinfo:
        list(read_applicants(make_csv("a.csv", text)))
    assert "a.csv" in str(excinfo.value)
    assert message in str(excinfo.value)


def test_term_date_before_hire_date_is_reported_with_line(make_csv: MakeCsv) -> None:
    path = make_csv("e.csv", EMPLOYEE_HEADER + "1,2019-02-01,Ann,Lee,2019-01-31\n")
    with pytest.raises(
        InputDataError,
        match=r"e\.csv:2: .*term_date 2019-01-31 is before hire_date 2019-02-01",
    ):
        list(read_employees(path))


def test_non_utf8_file_is_reported(make_csv: MakeCsv) -> None:
    path = make_csv("a.csv", APPLICANT_HEADER + "1,2012-01-28,José,Scott\n", encoding="latin-1")
    with pytest.raises(InputDataError, match="not valid UTF-8"):
        list(read_applicants(path))


def test_oversized_field_is_reported_with_line(make_csv: MakeCsv) -> None:
    path = make_csv(
        "a.csv",
        APPLICANT_HEADER + f"1,2012-01-28,{'x' * (csv.field_size_limit() + 1)},Scott\n",
    )
    with pytest.raises(InputDataError, match=r"a\.csv:2: malformed CSV"):
        list(read_applicants(path))


def test_nonexistent_file_raises_os_error(tmp_path: Path) -> None:
    with pytest.raises(FileNotFoundError):
        list(read_applicants(tmp_path / "missing.csv"))


def test_valid_rows_before_a_bad_row_are_streamed(make_csv: MakeCsv) -> None:
    rows = read_applicants(make_csv("a.csv", APPLICANT_HEADER + "1,2012-01-28,Robert,Scott\n2,nope,Ann,Lee\n"))
    assert next(rows).applicant_id == "1"
    with pytest.raises(InputDataError, match=":3:"):
        next(rows)


def make_match(term: date | None) -> Match:
    applicant = Applicant(
        applicant_id="7",
        first_name="Ann",
        last_name="Lee",
        application_date=date(2019, 1, 1),
    )
    employee = Employee(
        employee_id="1",
        first_name="ANN",
        last_name="LEE",
        hire_date=date(2019, 2, 1),
        term_date=term,
    )
    return Match.from_pair(applicant, employee)


def test_write_matches_round_trip(tmp_path: Path) -> None:
    out = tmp_path / "matches.csv"
    assert write_matches([make_match(date(2020, 1, 1)), make_match(None)], out) == 2

    raw = out.read_bytes()
    assert raw.startswith(",".join(MATCH_COLUMNS).encode() + b"\r\n")
    with out.open(newline="", encoding="utf-8") as handle:
        rows = list(csv.DictReader(handle))
    assert rows[0] == {
        "employee_id": "1",
        "employee_first_name": "ANN",
        "employee_last_name": "LEE",
        "applicant_id": "7",
        "applicant_first_name": "Ann",
        "applicant_last_name": "Lee",
        "application_date": "2019-01-01",
        "employee_hire_date": "2019-02-01",
        "employee_term_date": "2020-01-01",
    }
    assert rows[1]["employee_term_date"] == ""


def test_write_matches_with_no_rows_writes_header_only(tmp_path: Path) -> None:
    out = tmp_path / "matches.csv"
    assert write_matches([], out) == 0
    assert out.read_bytes() == ",".join(MATCH_COLUMNS).encode() + b"\r\n"
