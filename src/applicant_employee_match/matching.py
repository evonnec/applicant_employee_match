"""Match applicants (ATS data) to employees (HRIS data) by first and last name.

The module is organised in four layers, top to bottom:

1. Data models (``Applicant``, ``Employee``, ``Match``): validation only, no I/O.
2. Matching (``normalize_name``, ``default_name_key``, ``match_records``): pure functions.
3. CSV I/O (``read_csv``, ``read_applicants``, ``read_employees``, ``write_matches``).
4. The command-line interface (``main``).

Everything lives in one module so that ``python src/applicant_employee_match/matching.py``
keeps working without installing the package. ``python -m applicant_employee_match`` and the
``applicant-employee-match`` console script call the same ``main``.
"""

import argparse
import csv
import os
import re
import sys
import unicodedata
from collections import defaultdict
from collections.abc import Callable, Hashable, Iterable, Iterator, Sequence
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Annotated, Any, Self, TextIO

from pydantic import BaseModel, BeforeValidator, ConfigDict, Field, ValidationError, model_validator

# ---------------------------------------------------------------------------
# Data models
# ---------------------------------------------------------------------------

_ISO_DATE = re.compile(r"\d{4}-\d{2}-\d{2}", re.ASCII)


def _parse_date(value: Any) -> Any:
    """Accept only ``YYYY-MM-DD`` strings; pass ``date`` objects (and anything else) to pydantic."""
    if isinstance(value, str):
        text = value.strip()
        try:
            if _ISO_DATE.fullmatch(text):
                return date.fromisoformat(text)  # also rejects impossible dates
        except ValueError:
            pass
        raise ValueError(f"expected a date in YYYY-MM-DD format, got {value!r}")
    return value


# Pydantic's lax date parsing would also accept e.g. Unix timestamps ("1700000000"), and
# date.fromisoformat alone accepts "20120128" on Python 3.11+. The README promises YYYY-MM-DD,
# so string input is checked against that exact shape first. (This is also ~10x faster than
# datetime.strptime, which dominated the run time on large files.)
IsoDate = Annotated[date, BeforeValidator(_parse_date)]


class _Record(BaseModel):
    # frozen: records are hashable (used for de-duplication) and safe to share.
    # str_strip_whitespace + min_length=1 below: blank names and IDs are rejected.
    # extra="ignore": unknown CSV columns are allowed and dropped.
    model_config = ConfigDict(frozen=True, str_strip_whitespace=True, extra="ignore")


class Applicant(_Record):
    """One row of the applicant (ATS) file: a single application."""

    applicant_id: str = Field(min_length=1)
    first_name: str = Field(min_length=1)
    last_name: str = Field(min_length=1)
    application_date: IsoDate = Field(description="Date of application")


class Employee(_Record):
    """One row of the employee (HRIS) file: a single hire. Rehires repeat the employee_id."""

    employee_id: str = Field(min_length=1)
    first_name: str = Field(min_length=1)
    last_name: str = Field(min_length=1)
    hire_date: IsoDate = Field(description="Date of hire")
    term_date: IsoDate | None = Field(default=None, description="Date of termination; empty if still employed")

    @model_validator(mode="after")
    def _term_not_before_hire(self) -> Self:
        if self.term_date is not None and self.term_date < self.hire_date:
            raise ValueError(f"term_date {self.term_date} is before hire_date {self.hire_date}")
        return self


class Match(_Record):
    """An employee row paired with the applicant row it was matched to.

    Values are copied verbatim (after trimming surrounding whitespace) from the two input rows.
    """

    employee_id: str
    employee_first_name: str
    employee_last_name: str
    applicant_id: str
    applicant_first_name: str
    applicant_last_name: str
    application_date: date = Field(description="Date of application")
    employee_hire_date: date = Field(description="Date of hire")
    employee_term_date: date | None = Field(default=None, description="Date of termination")

    @classmethod
    def from_pair(cls, applicant: Applicant, employee: Employee) -> "Match":
        # Both inputs are already validated models, so validating again would only cost time.
        return cls.model_construct(
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

    @classmethod
    def match(cls, applicants: Iterable[Applicant], employees: Iterable[Employee]) -> list["Match"]:
        """Backwards-compatible shortcut for ``match_records(applicants, employees).matches``."""
        return match_records(applicants, employees).matches


MATCH_COLUMNS: tuple[str, ...] = tuple(Match.model_fields)

# ---------------------------------------------------------------------------
# Matching (pure)
# ---------------------------------------------------------------------------

NameKeyFunc = Callable[[str, str], Hashable]


def normalize_name(value: str) -> str:
    """Canonical form of one name part, used only for comparison.

    Unicode NFKC-normalised and case-folded, with surrounding whitespace removed and inner runs of
    whitespace collapsed to one space. Hyphens, apostrophes and accents are kept as-is, so
    ``"Price-Chavez"`` and ``"Price Chavez"`` are still different names.

    NFKC comes first because it can produce capitals that case-folding must then see ("ℍ" -> "H"),
    and again last because case-folding can leave text that is no longer NFKC.
    """
    folded = unicodedata.normalize("NFKC", value).casefold()
    return " ".join(unicodedata.normalize("NFKC", folded).split())


def default_name_key(first_name: str, last_name: str) -> tuple[str, str]:
    """The join key: ``(normalize_name(first_name), normalize_name(last_name))``."""
    return normalize_name(first_name), normalize_name(last_name)


@dataclass(frozen=True)
class MatchResult:
    """Matches plus the counters a caller needs to judge the quality of the run."""

    matches: list[Match]
    applicant_rows: int = 0
    employee_rows: int = 0
    ambiguous_matches: int = 0
    """Matches where several distinct applicants shared the employee's name (see ``_pick_applicant``)."""
    duplicate_employee_rows: int = 0
    """Employee rows skipped because an identical row had already produced the same match."""
    applicants_matched_to_multiple_employees: int = 0
    """Applicants paired with more than one distinct employee_id (likely a name collision)."""


def _pick_applicant(candidates: Sequence[Applicant], hire_date: date) -> Applicant:
    """Choose among applicants who share a name key.

    ``candidates`` must be sorted by ``(application_date, applicant_id, first_name, last_name)``. The
    rule is: the latest application on or before the hire date; if every application is after the
    hire date, the earliest one. Ties on the date go to the lexicographically smallest applicant_id,
    then name, so that the choice never depends on the order of the input rows.
    """
    chosen: Applicant | None = None
    for candidate in candidates:
        if candidate.application_date > hire_date:
            break
        if chosen is None or candidate.application_date > chosen.application_date:
            chosen = candidate
    return chosen if chosen is not None else candidates[0]


def _sort_key(match: Match) -> tuple[str, date, str, str, str, date]:
    # employee_id is an opaque string, so it sorts lexicographically ("10" < "9").
    return (
        match.employee_id,
        match.employee_hire_date,
        match.applicant_id,
        match.employee_first_name,
        match.employee_last_name,
        match.employee_term_date or date.max,
    )


def match_records(
    applicants: Iterable[Applicant],
    employees: Iterable[Employee],
    *,
    name_key: NameKeyFunc = default_name_key,
) -> MatchResult:
    """Pair every employee row with at most one applicant whose name has the same key.

    This is a hash join. ``applicants`` (the build side) is loaded into an index; ``employees``
    (the probe side) is consumed once, as a stream, so it can be a lazy iterator over a large file.
    Time is O(A + E + M log M) and memory O(A + M), for A applicants, E employee rows and M matches.

    * Names are compared through ``name_key`` (case/whitespace-insensitive by default). Pass a
      different function to plug in nickname tables, hyphen folding, etc.
    * Every employee row (hire) is matched on its own, so a rehire produces one match per hire.
    * Applicant rows that are exact duplicates count once. If distinct applicants share a key,
      ``_pick_applicant`` decides and the match is counted in ``ambiguous_matches``.
    * Exact duplicate employee rows produce a single match.
    * The returned matches are sorted by employee_id, hire date and applicant_id, so the output
      does not depend on input row order.
    """
    grouped: dict[Hashable, list[Applicant]] = defaultdict(list)
    applicant_rows = 0
    for applicant in applicants:
        applicant_rows += 1
        grouped[name_key(applicant.first_name, applicant.last_name)].append(applicant)
    index: dict[Hashable, list[Applicant]] = {
        key: sorted(dict.fromkeys(group), key=lambda a: (a.application_date, a.applicant_id, a.first_name, a.last_name))
        for key, group in grouped.items()
    }

    found: dict[Match, None] = {}  # insertion-ordered set
    employee_rows = ambiguous = duplicates = 0
    for employee in employees:
        employee_rows += 1
        candidates = index.get(name_key(employee.first_name, employee.last_name))
        if not candidates:
            continue
        match = Match.from_pair(_pick_applicant(candidates, employee.hire_date), employee)
        if match in found:
            duplicates += 1
            continue
        found[match] = None
        if len(candidates) > 1:
            ambiguous += 1

    employee_ids_by_applicant: dict[str, set[str]] = defaultdict(set)
    for match in found:
        employee_ids_by_applicant[match.applicant_id].add(match.employee_id)

    return MatchResult(
        matches=sorted(found, key=_sort_key),
        applicant_rows=applicant_rows,
        employee_rows=employee_rows,
        ambiguous_matches=ambiguous,
        duplicate_employee_rows=duplicates,
        applicants_matched_to_multiple_employees=sum(1 for ids in employee_ids_by_applicant.values() if len(ids) > 1),
    )


# ---------------------------------------------------------------------------
# CSV I/O
# ---------------------------------------------------------------------------


class InputDataError(ValueError):
    """An input file is missing, unreadable, malformed or fails validation.

    The message names the file and, where it applies, the line number.
    """


def _describe(exc: ValidationError) -> str:
    parts = []
    for error in exc.errors():
        field = ".".join(str(part) for part in error["loc"])
        if not field:  # model-level validator
            parts.append(error["msg"])
        elif error["type"] == "missing":
            parts.append(f"{field}: value is required")
        else:
            parts.append(f"{field}={error['input']!r}: {error['msg']}")
    return "; ".join(parts)


def read_csv[T: (Applicant, Employee)](cls: type[T], filename: str | os.PathLike[str]) -> Iterator[T]:
    """Lazily read and validate one CSV file into ``cls`` records.

    * The file must be UTF-8. A leading byte-order mark (as Excel writes) is tolerated.
    * The first row is the header. Header names are matched case-insensitively and with
      surrounding whitespace ignored. Columns can be in any order, and unknown columns are ignored.
    * A header-only file yields nothing. An empty file, missing required columns, duplicated
      columns, rows with the wrong number of fields and values that fail validation all raise
      ``InputDataError`` with the file name and line number.
    * Cell values are stripped, and an empty cell means "not provided" (for example, no term_date).
    * Rows whose cells are all empty are skipped.
    """
    path = Path(filename)
    try:
        with path.open(newline="", encoding="utf-8-sig") as handle:
            yield from _parse_rows(cls, path, handle)
    except UnicodeDecodeError as exc:
        raise InputDataError(_locate_invalid_utf8(path) or f"{path}: not valid UTF-8 ({exc.reason})") from None


def _locate_invalid_utf8(path: Path) -> str | None:
    """Describe the first byte of ``path`` that is not UTF-8, with its line and offset in the file.

    The ``UnicodeDecodeError`` raised while reading only knows its offset within one buffered chunk,
    so a regular file is scanned again. A pipe cannot be read twice, so for it this returns None.
    """
    if not path.is_file():
        return None
    offset = 0
    with path.open("rb") as handle:
        for line_number, line in enumerate(handle, start=1):
            try:
                line.decode("utf-8")
            except UnicodeDecodeError as exc:
                return f"{path}:{line_number}: not valid UTF-8 ({exc.reason} at byte {offset + exc.start})"
            offset += len(line)
    return None


def _parse_rows[T: (Applicant, Employee)](cls: type[T], path: Path, handle: TextIO) -> Iterator[T]:
    reader = csv.reader(handle)
    start = 1  # first line of the record being read: a quoted field can span lines
    try:
        header = next(reader, None)
        if header is None:
            raise InputDataError(f"{path}: file is empty; expected a header row")
        columns = _check_header(cls, path, header)
        known = set(cls.model_fields)
        start = reader.line_num + 1
        for row in reader:
            where, start = f"{path}:{start}", reader.line_num + 1
            if not any(cell.strip() for cell in row):
                continue
            if len(row) != len(columns):
                expected = len(columns)
                raise InputDataError(f"{where}: expected {expected} fields, got {len(row)}")
            values = {
                column: cell.strip()
                for column, cell in zip(columns, row, strict=True)
                if column in known and cell.strip()
            }
            try:
                yield cls.model_validate(values)
            except ValidationError as exc:
                raise InputDataError(f"{where}: {_describe(exc)}") from None
    except csv.Error as exc:
        raise InputDataError(f"{path}:{start}: malformed CSV: {exc}") from None


def _check_header(cls: type[BaseModel], path: Path, header: list[str]) -> list[str]:
    """Normalise header names and check them against the model; return the column names."""
    columns = [column.strip().lower() for column in header]
    # Unnamed columns (trailing commas, as Excel writes for stray cells) are ignored like any extra column.
    duplicated = sorted({column for column in columns if column and columns.count(column) > 1})
    if duplicated:
        raise InputDataError(f"{path}: duplicate column(s) in header: {', '.join(duplicated)}")
    fields = cls.model_fields.items()
    required = [name for name, field in fields if field.is_required()]
    missing = [column for column in required if column not in columns]
    if missing:
        raise InputDataError(f"{path}: missing required column(s): {', '.join(missing)} (found: {', '.join(columns)})")
    return columns


def read_applicants(filename: str | os.PathLike[str]) -> Iterator[Applicant]:
    return read_csv(Applicant, filename)


def read_employees(filename: str | os.PathLike[str]) -> Iterator[Employee]:
    return read_csv(Employee, filename)


def write_csv(matches: Iterable[Match], handle: TextIO) -> int:
    """Write the header and one row per match to an open text stream. Returns the row count."""
    writer = csv.DictWriter(handle, fieldnames=MATCH_COLUMNS)
    writer.writeheader()
    count = 0
    for match in matches:
        writer.writerow(match.model_dump())
        count += 1
    return count


def write_matches(matches: Iterable[Match], filename: str | os.PathLike[str]) -> int:
    """Write matches to ``filename`` as UTF-8 CSV with CRLF row endings (RFC 4180, as before)."""
    with Path(filename).open("w", newline="", encoding="utf-8") as handle:
        return write_csv(matches, handle)


# ---------------------------------------------------------------------------
# Command-line interface
# ---------------------------------------------------------------------------


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="A tool for matching HRIS (employee) and applicant (ATS) data. Applicants in the CSV file "
        "given by --applicant-csv will be matched to employees in the file given with --employee-csv, and the "
        "output will be written to --match-out-csv (standard output by default). The matching process uses "
        "employee and applicant first and last names, compared case-insensitively, to determine that an "
        "employee and applicant are the same person. Progress and warnings are printed to standard error."
    )
    parser.add_argument(
        "--applicant-csv",
        "-a",
        required=True,
        help="Path to a file containing applicant (ATS) data. The file should have the following headers: "
        f"{', '.join(Applicant.model_fields)}. The first_name, last_name, and applicant_id "
        "headers may contain arbitrary non-empty strings. The application_date header should be a date in "
        "YYYY-MM-DD format.",
    )
    parser.add_argument(
        "--employee-csv",
        "-e",
        required=True,
        help="Path to a file containing employee (HRIS) data. The file should have the following headers: "
        f"{', '.join(Employee.model_fields)}. The first_name, last_name, and employee_id "
        "headers may contain arbitrary non-empty strings. The hire_date and term_date should be a date in "
        "YYYY-MM-DD format; term_date may be empty.",
    )
    parser.add_argument(
        "--match-out-csv",
        "-o",
        default="-",
        help="Path to write matched employee/applicant data, or '-' for standard output (the default). The "
        f"file will have the following headers: {', '.join(MATCH_COLUMNS)}. Each row holds the data from "
        "one row in --applicant-csv and one row in --employee-csv, sorted by employee_id and hire date.",
    )
    return parser


def _same_file(a: str, b: str) -> bool:
    # samefile compares device and inode numbers, so it also sees through hard links and through
    # case-insensitive file systems (the macOS and Windows default), where A.CSV is a.csv.
    try:
        return os.path.samefile(a, b)
    except OSError:  # one of them does not exist (yet)
        return os.path.realpath(a) == os.path.realpath(b)


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI. Returns the process exit code: 0 on success, 1 on bad input, 2 on bad usage."""
    args = build_parser().parse_args(argv)
    applicant_csv: str = args.applicant_csv
    employee_csv: str = args.employee_csv
    out: str = args.match_out_csv

    def info(message: str) -> None:
        print(message, file=sys.stderr)

    try:
        for label, path in (("applicant", applicant_csv), ("employee", employee_csv)):
            # Not os.path.isfile: a pipe (`-a /dev/stdin`, `-a <(cmd)`) is a valid input too.
            if not os.path.exists(path) or os.path.isdir(path):
                raise InputDataError(f"{label} CSV not found (or not a file): {path}")
            if out != "-" and _same_file(out, path):
                raise InputDataError(f"refusing to overwrite the {label} input with the output: {out}")

        # Materialise the build side so it is fully validated before employees are streamed.
        applicants = list(read_applicants(applicant_csv))
        info(f"Read {len(applicants)} applicants from {applicant_csv}")
        result = match_records(applicants, read_employees(employee_csv))
        info(f"Read {result.employee_rows} employees from {employee_csv}")
        info(f"Found {len(result.matches)} matches")
        if result.ambiguous_matches:
            info(
                f"warning: {result.ambiguous_matches} matches were chosen among several applicants with the "
                "same name (latest application on or before the hire date wins)"
            )
        if result.duplicate_employee_rows:
            info(f"warning: ignored {result.duplicate_employee_rows} duplicate employee rows")
        if result.applicants_matched_to_multiple_employees:
            info(
                f"warning: {result.applicants_matched_to_multiple_employees} applicants matched more than one "
                "employee_id (possible name collision)"
            )

        # Output is opened only after every input row has been read and validated, so a bad input
        # never truncates an existing output file.
        if out == "-":
            write_csv(result.matches, sys.stdout)
        else:
            write_matches(result.matches, out)
            info(f"Wrote {len(result.matches)} matches to {out}")
    except BrokenPipeError:
        # The reader of stdout went away (e.g. `| head`). Point stdout at devnull so the interpreter's
        # final flush does not raise again, and exit quietly like other Unix tools.
        os.dup2(os.open(os.devnull, os.O_WRONLY), sys.stdout.fileno())
        return 1
    except (InputDataError, OSError) as exc:
        info(f"error: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
