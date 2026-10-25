"""Property-based tests (hypothesis): normalisation, matching rules, CSV round trips and fuzzed input."""

import csv
import io
import random
import re
import tempfile
import unicodedata
from collections.abc import Sequence
from datetime import date, timedelta
from pathlib import Path

import pytest
from hypothesis import HealthCheck, given, settings
from hypothesis import strategies as st

from applicant_employee_match.matching import (
    MATCH_COLUMNS,
    Applicant,
    Employee,
    InputDataError,
    Match,
    main,
    match_records,
    normalize_name,
    read_applicants,
    read_employees,
)

# Generated data is small, but CI machines are slow and noisy: no per-example deadline.
settings.register_profile("default", deadline=None, suppress_health_check=[HealthCheck.too_slow])
settings.load_profile("default")

# --- strategies ---------------------------------------------------------------

# Names are drawn as spellings of a few base names, so keys collide often. Spellings of one base differ
# only in what the README says to ignore (case, whitespace, NFKC); different bases must not match, even
# near misses such as "jose"/"jos\u00e9" (accent) and "price-chavez"/"price chavez" (hyphen).
FIRST_NAMES = ["ann", "mary ann", "jose", "jos\u00e9", "\ufb01ona"]  # \ufb01 is the "fi" ligature
LAST_NAMES = ["lee", "price-chavez", "price chavez", "strau\u00df"]


def spellings(base: str) -> st.SearchStrategy[str]:
    variants = [base, base.upper(), base.title(), f" {base}\t", base.replace(" ", "\u00a0 ")]
    return st.sampled_from([*variants, unicodedata.normalize("NFD", base)])


first_names = st.sampled_from(FIRST_NAMES).flatmap(spellings)
last_names = st.sampled_from(LAST_NAMES).flatmap(spellings)
ids = st.sampled_from(["1", "10", "A"])  # few values, so IDs repeat
days = st.integers(min_value=0, max_value=3).map(lambda n: date(2020, 1, 1) + timedelta(days=n))

applicants = st.builds(Applicant, applicant_id=ids, first_name=first_names, last_name=last_names, application_date=days)


@st.composite
def employees(draw: st.DrawFn) -> Employee:
    hired = draw(days)
    term = draw(st.none() | st.integers(min_value=0, max_value=3).map(lambda n: hired + timedelta(days=n)))
    return Employee(
        employee_id=draw(ids),
        first_name=draw(first_names),
        last_name=draw(last_names),
        hire_date=hired,
        term_date=term,
    )


# --- name normalisation -------------------------------------------------------


@given(st.text())
def test_normalize_name_is_idempotent(value: str) -> None:
    assert normalize_name(normalize_name(value)) == normalize_name(value)


@given(st.text())
def test_compatibility_and_canonical_equivalents_share_a_key(value: str) -> None:
    """The README promises NFKC: two spellings with the same NFKC (or NFC/NFD) form are the same name."""
    key = normalize_name(value)
    for form in ("NFKC", "NFC", "NFD"):
        assert normalize_name(unicodedata.normalize(form, value)) == key


@given(st.text(alphabet=st.characters(codec="ascii")))
def test_ascii_names_match_case_and_whitespace_insensitively(value: str) -> None:
    assert normalize_name(value.upper()) == normalize_name(value.lower()) == " ".join(value.lower().split())


# --- matching rules -----------------------------------------------------------


def reference_key(name: str) -> str:
    # Compatibility caseless form as the Python docs spell it, plus the README's whitespace rule.
    return " ".join(unicodedata.normalize("NFKD", unicodedata.normalize("NFKD", name).casefold()).split())


def reference_matches(applicants: Sequence[Applicant], employees: Sequence[Employee]) -> set[Match]:
    """O(A*E) restatement of README rules 1-4, independent of the implementation."""
    result = set()
    for e in employees:
        key = (reference_key(e.first_name), reference_key(e.last_name))
        candidates = {a for a in applicants if (reference_key(a.first_name), reference_key(a.last_name)) == key}
        if not candidates:
            continue
        before = [a for a in candidates if a.application_date <= e.hire_date]
        target = max(a.application_date for a in before) if before else min(a.application_date for a in candidates)
        tied = [a for a in candidates if a.application_date == target]
        # Smallest applicant_id; rows that also share the id are told apart by name, never by input order.
        chosen = min(tied, key=lambda a: (a.applicant_id, a.first_name, a.last_name))
        result.add(Match.from_pair(chosen, e))
    return result


@given(st.lists(applicants, max_size=12), st.lists(employees(), max_size=12))
def test_matches_follow_the_documented_rules(applicants: list[Applicant], employees: list[Employee]) -> None:
    result = match_records(applicants, employees)
    assert set(result.matches) == reference_matches(applicants, employees)
    assert len(result.matches) == len(set(result.matches))
    keys = [(m.employee_id, m.employee_hire_date, m.applicant_id) for m in result.matches]
    assert keys == sorted(keys)


@given(st.lists(applicants, max_size=12), st.lists(employees(), max_size=12), st.randoms(use_true_random=False))
def test_output_does_not_depend_on_input_row_order(
    applicants: list[Applicant], employees: list[Employee], rnd: random.Random
) -> None:
    expected = match_records(applicants, employees)
    shuffled_a, shuffled_e = applicants[:], employees[:]
    rnd.shuffle(shuffled_a)
    rnd.shuffle(shuffled_e)
    assert match_records(shuffled_a, shuffled_e) == expected


# --- CSV round trip and fuzzing -----------------------------------------------

# Any text that UTF-8 can encode (no lone surrogates), with CSV's special characters made likely.
cells = st.text(alphabet=st.characters(exclude_categories=["Cs"]) | st.sampled_from('\r\n",'), max_size=12)
visible_cells = cells.filter(lambda s: s.strip() != "")


@given(st.lists(st.tuples(visible_cells, visible_cells, visible_cells, days), max_size=8))
def test_any_cell_text_survives_a_csv_round_trip(rows: list[tuple[str, str, str, date]]) -> None:
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer)
    writer.writerow(["applicant_id", "first_name", "last_name", "application_date"])
    writer.writerows(rows)
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp, "a.csv")
        path.write_bytes(buffer.getvalue().encode("utf-8"))
        read = [(a.applicant_id, a.first_name, a.last_name, a.application_date) for a in read_applicants(path)]
    assert read == [(i.strip(), f.strip(), last.strip(), d) for i, f, last, d in rows]


@given(
    st.lists(st.tuples(visible_cells, visible_cells, visible_cells, days), max_size=6),
    visible_cells,
    st.sampled_from(["\n", "\r\n"]),
)
def test_errors_cite_the_line_where_the_bad_record_starts(
    rows: list[tuple[str, str, str, date]], bad_name: str, eol: str
) -> None:
    """Valid rows then one bad row; quoted cells in any of them, the bad one included, may hold line breaks."""
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator=eol)
    writer.writerow(["applicant_id", "first_name", "last_name", "application_date"])
    writer.writerows(rows)
    # Count line breaks as a file opened with newline="" does: \r\n, \r and \n.
    bad_line = len(re.findall(r"\r\n|\r|\n", buffer.getvalue())) + 1
    writer.writerow(["x", bad_name, "B", "not-a-date"])
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp, "a.csv")
        path.write_bytes(buffer.getvalue().encode("utf-8"))
        with pytest.raises(InputDataError, match=rf"a\.csv:{bad_line}: application_date='not-a-date'"):
            list(read_applicants(path))


@given(st.lists(st.tuples(ids, days), min_size=1, max_size=40), st.data())
def test_invalid_utf8_is_located_by_line_and_byte(rows: list[tuple[str, date]], data: st.DataObject) -> None:
    lines = [b"applicant_id,application_date,first_name,last_name\n"]
    lines += [f"{i},{d},Ann,Lee\n".encode() for i, d in rows]
    line_index = data.draw(st.integers(min_value=1, max_value=len(lines) - 1))
    column = data.draw(st.integers(min_value=0, max_value=len(lines[line_index]) - 1))
    lines[line_index] = lines[line_index][:column] + b"\xff" + lines[line_index][column:]
    offset = sum(len(line) for line in lines[:line_index]) + column
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp, "a.csv")
        path.write_bytes(b"".join(lines))
        with pytest.raises(InputDataError, match=rf"a\.csv:{line_index + 1}: not valid UTF-8 \(.* at byte {offset}\)"):
            list(read_applicants(path))


APPLICANT_CSV = b"applicant_id,application_date,first_name,last_name\n1,2019-01-01,Ann,Lee\n"
EMPLOYEE_CSV = b"employee_id,hire_date,first_name,last_name,term_date\n10,2019-02-01,ANN,LEE,\n"


@settings(max_examples=300)
@given(st.binary(max_size=200), st.integers(min_value=0, max_value=len(EMPLOYEE_CSV)), st.booleans())
def test_reading_fuzzed_bytes_never_raises_anything_but_input_data_error(
    junk: bytes, position: int, replace: bool
) -> None:
    """Splice random bytes into a valid file: it parses, or fails with a clean InputDataError."""
    data = EMPLOYEE_CSV[:position] + junk + EMPLOYEE_CSV[position + (len(junk) if replace else 0) :]
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp, "e.csv")
        path.write_bytes(data)
        try:
            list(read_employees(path))
        except InputDataError as exc:
            assert str(path) in str(exc)


@settings(max_examples=50)
@given(st.binary(max_size=120), st.integers(min_value=0, max_value=len(APPLICANT_CSV)))
def test_cli_on_fuzzed_input_exits_0_or_1_without_a_traceback(junk: bytes, position: int) -> None:
    with tempfile.TemporaryDirectory() as tmp:
        applicants_path, employees_path, out = Path(tmp, "a.csv"), Path(tmp, "e.csv"), Path(tmp, "out.csv")
        applicants_path.write_bytes(APPLICANT_CSV[:position] + junk + APPLICANT_CSV[position:])
        employees_path.write_bytes(EMPLOYEE_CSV)
        code = main(["-a", str(applicants_path), "-e", str(employees_path), "-o", str(out)])
        assert code in (0, 1)
        if code == 0:
            assert out.read_text(encoding="utf-8").startswith(",".join(MATCH_COLUMNS))
        else:
            assert not out.exists()
