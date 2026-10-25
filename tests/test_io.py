"""Tests for CSV reading (validation, malformed input) and writing."""

import csv
import os
import stat
from collections.abc import Callable, Iterator
from datetime import date
from pathlib import Path

import pytest

from applicant_employee_match.matching import (
    MATCH_COLUMNS,
    Applicant,
    Employee,
    InputDataError,
    Match,
    check_writable,
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


def test_unnamed_trailing_columns_are_ignored(make_csv: MakeCsv) -> None:
    """Excel often saves stray empty columns as trailing commas; blank header names are not duplicates."""
    text = "applicant_id,application_date,first_name,last_name,,\n1,2012-01-28,Robert,Scott,,\n"
    assert [a.applicant_id for a in read_applicants(make_csv("a.csv", text))] == ["1"]


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


def test_error_in_a_multiline_record_reports_the_line_where_it_starts(make_csv: MakeCsv) -> None:
    text = APPLICANT_HEADER + '1,2012-01-28,Robert,Scott\n2,2012-13-01,"Mary\nAnn\nJo",Lee\n3,2012-01-29,A,B\n'
    with pytest.raises(InputDataError, match=r"a\.csv:3: application_date='2012-13-01'"):
        list(read_applicants(make_csv("a.csv", text)))


def test_unterminated_quote_reports_the_line_where_the_record_starts(make_csv: MakeCsv) -> None:
    """A stray quote swallows the rest of the file into one field; the error should point at the quote's line."""
    rows = "".join(f"{i},2012-01-28,Robert,Scott\n" for i in range(3, 50))
    text = APPLICANT_HEADER + '1,2012-01-28,Robert,Scott\n2,2012-01-28,"Ann,Lee\n' + rows
    with pytest.raises(InputDataError, match=r"a\.csv:3: expected 4 fields, got 3"):
        list(read_applicants(make_csv("a.csv", text)))


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


def test_non_utf8_byte_deep_in_a_file_is_located_by_line_and_file_offset(make_csv: MakeCsv) -> None:
    """The decoder reads in chunks, so its offset is relative to a chunk; the error must locate the byte in the file."""
    rows = "".join(f"{i},2012-01-28,Robert,Scott\r\n" for i in range(1, 5000))
    path = make_csv("a.csv", APPLICANT_HEADER + rows + "5000,2012-01-28,José,Scott\r\n", encoding="latin-1")
    offset = path.read_bytes().index("é".encode("latin-1"))
    with pytest.raises(InputDataError, match=rf"a\.csv:5001: not valid UTF-8 \(.* at byte {offset}\)"):
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


def test_write_matches_failure_part_way_keeps_previous_output(tmp_path: Path) -> None:
    out = tmp_path / "matches.csv"
    out.write_text("previous run\n")

    def failing_rows() -> Iterator[Match]:
        yield make_match(date(2020, 1, 1))
        raise RuntimeError("disk full")

    with pytest.raises(RuntimeError, match="disk full"):
        write_matches(failing_rows(), out)
    assert out.read_text() == "previous run\n"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["matches.csv"]  # no temporary file left behind


@pytest.mark.skipif(os.name != "posix", reason="POSIX permission bits")
def test_write_matches_keeps_mode_of_existing_file(tmp_path: Path) -> None:
    out = tmp_path / "matches.csv"
    out.write_text("previous run\n")
    out.chmod(0o640)
    write_matches([make_match(None)], out)
    assert stat.S_IMODE(out.stat().st_mode) == 0o640


@pytest.mark.skipif(os.name != "posix", reason="POSIX permission bits")
def test_write_matches_new_file_follows_umask(tmp_path: Path) -> None:
    umask = os.umask(0o022)
    try:
        write_matches([], tmp_path / "matches.csv")
    finally:
        os.umask(umask)
    assert stat.S_IMODE((tmp_path / "matches.csv").stat().st_mode) == 0o644


def test_write_matches_writes_through_a_symlink(tmp_path: Path) -> None:
    target = tmp_path / "real.csv"
    target.write_text("previous run\n")
    link = tmp_path / "link.csv"
    link.symlink_to(target)
    write_matches([], link)
    assert link.is_symlink()
    assert target.read_bytes() == ",".join(MATCH_COLUMNS).encode() + b"\r\n"


@pytest.mark.skipif(os.name != "posix", reason="needs /dev/null")
def test_write_matches_to_a_device_writes_in_place() -> None:
    assert write_matches([make_match(None)], os.devnull) == 1
    assert Path(os.devnull).is_char_device()


@pytest.mark.skipif(os.name != "posix" or os.geteuid() == 0, reason="POSIX permissions; root ignores them")
def test_write_matches_refuses_read_only_output(tmp_path: Path) -> None:
    out = tmp_path / "matches.csv"
    out.write_text("previous run\n")
    out.chmod(0o444)
    with pytest.raises(PermissionError, match="output file is not writable"):
        write_matches([], out)
    assert out.read_text() == "previous run\n"


@pytest.mark.parametrize(
    ("relative", "error", "message"),
    [
        ("no-such-dir/out.csv", FileNotFoundError, "output directory not found"),
        (".", IsADirectoryError, "output path is a directory"),
    ],
)
def test_check_writable_rejects_impossible_paths(
    tmp_path: Path, relative: str, error: type[OSError], message: str
) -> None:
    with pytest.raises(error, match=message):
        check_writable(tmp_path / relative)


def test_check_writable_accepts_new_and_existing_files(tmp_path: Path) -> None:
    check_writable(tmp_path / "new.csv")
    (tmp_path / "old.csv").write_text("x")
    check_writable(tmp_path / "old.csv")
