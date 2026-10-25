"""Unit tests for the data models and the pure matching logic (no file I/O)."""

import random
from collections.abc import Hashable, Iterator, Sequence
from datetime import date, timedelta
from typing import Any

import pytest
from pydantic import ValidationError

from applicant_employee_match import matching
from applicant_employee_match.matching import Applicant, Employee, Match, match_records, normalize_name


def make_applicant(
    applicant_id: str = "ABC",
    first: str = "Marianne",
    last: str = "Smith",
    applied: date = date(2019, 1, 1),
) -> Applicant:
    return Applicant(
        applicant_id=applicant_id,
        first_name=first,
        last_name=last,
        application_date=applied,
    )


def make_employee(
    employee_id: str = "1234",
    first: str = "Marianne",
    last: str = "Smith",
    hired: date = date(2019, 1, 15),
    term: date | None = None,
) -> Employee:
    return Employee(
        employee_id=employee_id,
        first_name=first,
        last_name=last,
        hire_date=hired,
        term_date=term,
    )


# --- models -----------------------------------------------------------------


def test_sample() -> None:
    "Sample test to ensure 'pytest' is working properly"
    applicant: dict[str, Any] = {
        "applicant_id": "123",
        "first_name": "Mary",
        "last_name": "Doe",
        "application_date": date(2020, 1, 1),
    }
    assert matching.Applicant(**applicant).model_dump() == applicant


def test_models_strip_whitespace() -> None:
    applicant = make_applicant(applicant_id=" 7 ", first="  Mary ", last=" Doe\t")
    assert (applicant.applicant_id, applicant.first_name, applicant.last_name) == (
        "7",
        "Mary",
        "Doe",
    )


@pytest.mark.parametrize("field", ["applicant_id", "first_name", "last_name"])
@pytest.mark.parametrize("blank", ["", "   "])
def test_applicant_rejects_blank_names_and_ids(field: str, blank: str) -> None:
    data = make_applicant().model_dump() | {field: blank}
    with pytest.raises(ValidationError):
        Applicant.model_validate(data)


@pytest.mark.parametrize("value", ["2012-01-28", " 2012-01-28 ", date(2012, 1, 28)])
def test_date_accepts_iso_strings_and_dates(value: object) -> None:
    applicant = Applicant.model_validate(
        {
            "applicant_id": "1",
            "first_name": "A",
            "last_name": "B",
            "application_date": value,
        }
    )
    assert applicant.application_date == date(2012, 1, 28)


@pytest.mark.parametrize(
    "value",
    ["01/28/2012", "28-01-2012", "2012-02-30", "1700000000", "2012-01-28T10:00:00", ""],
)
def test_date_rejects_non_iso_strings(value: str) -> None:
    with pytest.raises(ValidationError):
        Applicant.model_validate(
            {
                "applicant_id": "1",
                "first_name": "A",
                "last_name": "B",
                "application_date": value,
            }
        )


def test_term_date_is_optional() -> None:
    assert make_employee().term_date is None


def test_term_date_before_hire_date_is_rejected() -> None:
    with pytest.raises(ValidationError, match="before hire_date"):
        make_employee(hired=date(2019, 2, 1), term=date(2019, 1, 31))


def test_same_day_termination_is_allowed() -> None:
    assert make_employee(hired=date(2019, 2, 1), term=date(2019, 2, 1)).term_date == date(2019, 2, 1)


def test_models_are_frozen_and_hashable() -> None:
    applicant = make_applicant()
    assert hash(applicant) == hash(make_applicant())
    with pytest.raises(ValidationError, match="frozen"):
        applicant.__setattr__("first_name", "Other")


# --- name normalisation -----------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("Marianne", "marianne"),
        ("MARIANNE", "marianne"),
        ("  Mary \t  Ann ", "mary ann"),
        ("Price-Chavez", "price-chavez"),
        ("O'Brien", "o'brien"),
        ("Straße", "strasse"),  # casefold, not lower
        ("Ｍａｒｙ", "mary"),  # full-width letters (NFKC)
    ],
)
def test_normalize_name(raw: str, expected: str) -> None:
    assert normalize_name(raw) == expected


# --- matching ---------------------------------------------------------------


def test_no_matches() -> None:
    applicant = make_applicant(first="Marianne", last="Smith")
    employee = make_employee(first="Tara", last="Johnson", term=date(2019, 2, 2))

    result = match_records([applicant], [employee])

    assert result.matches == []
    assert (result.applicant_rows, result.employee_rows) == (1, 1)


def test_empty_inputs() -> None:
    assert match_records([], []).matches == []
    assert match_records([make_applicant()], []).matches == []
    assert match_records([], [make_employee()]).matches == []


def test_rehire_produces_one_match_per_hire() -> None:
    """Two hire rows for the same employee_id and name each match the applicant."""
    applicant = make_applicant()
    employee1 = make_employee(hired=date(2019, 1, 15), term=date(2019, 2, 2))
    employee2 = make_employee(hired=date(2019, 8, 3), term=date(2019, 12, 3))

    result = Match.match(applicants=[applicant], employees=[employee1, employee2])

    assert len(result) == 2
    assert {m.employee_first_name for m in result} | {m.applicant_first_name for m in result} == {"Marianne"}
    assert [m.employee_id for m in result] == ["1234", "1234"]
    assert [m.employee_hire_date for m in result] == [
        date(2019, 1, 15),
        date(2019, 8, 3),
    ]
    assert {m.applicant_id for m in result} == {"ABC"}


def test_same_id_different_name() -> None:
    """Rows of one employee_id are matched independently: a case variant matches, a nickname does not."""
    applicant = make_applicant(first="Katherine", last="Butler")
    upper = make_employee(first="KATHERINE", last="BUTLER", hired=date(2019, 1, 15))
    nickname = make_employee(first="Kathy", last="Butler", hired=date(2020, 1, 15))

    result = match_records([applicant], [upper, nickname])

    assert len(result.matches) == 1
    assert result.matches[0].employee_hire_date == date(2019, 1, 15)


def test_same_name_different_id() -> None:
    """Name-only matching cannot tell two employees with the same name apart: both match, and it is reported."""
    applicant = make_applicant()
    employee1 = make_employee(employee_id="1234", hired=date(2019, 1, 15), term=date(2019, 2, 2))
    employee2 = make_employee(employee_id="9988", hired=date(2019, 8, 3), term=date(2019, 12, 3))

    result = match_records([applicant], [employee1, employee2])

    assert [m.employee_id for m in result.matches] == ["1234", "9988"]
    assert {m.applicant_id for m in result.matches} == {"ABC"}
    assert result.applicants_matched_to_multiple_employees == 1


def test_matching_is_case_insensitive_and_output_keeps_input_spelling() -> None:
    applicant = make_applicant(first="Katherine", last="Butler")
    employee = make_employee(first="KATHERINE", last="BUTLER")

    [match] = match_records([applicant], [employee]).matches

    assert (match.employee_first_name, match.employee_last_name) == (
        "KATHERINE",
        "BUTLER",
    )
    assert (match.applicant_first_name, match.applicant_last_name) == (
        "Katherine",
        "Butler",
    )


@pytest.mark.parametrize(
    ("applicant_last", "employee_last"),
    [
        ("Price-Chavez", "Price-Chavez"),
        ("Price-Chavez", "PRICE-CHAVEZ"),
        ("Brown Alexander", "Brown Alexander"),
        ("Brown Alexander", "BROWN ALEXANDER"),
        ("O'Brien", "O'BRIEN"),
        ("McDonald", "MCDONALD"),
    ],
)
def test_compound_and_mixed_case_last_names_match(applicant_last: str, employee_last: str) -> None:
    """Regression: str.capitalize() turned 'Price-Chavez' into 'Price-chavez' and lost these matches."""
    result = match_records([make_applicant(last=applicant_last)], [make_employee(last=employee_last)])
    assert len(result.matches) == 1


def test_hyphen_and_space_are_different_names_by_default() -> None:
    result = match_records([make_applicant(last="Price-Chavez")], [make_employee(last="Price Chavez")])
    assert result.matches == []


def test_custom_name_key_can_add_fuzzier_rules() -> None:
    nicknames = {"kathy": "katherine"}

    def key(first: str, last: str) -> Hashable:
        first_key = normalize_name(first)
        return nicknames.get(first_key, first_key), normalize_name(last).replace("-", " ")

    applicant = make_applicant(first="Katherine", last="Price-Chavez")
    employee = make_employee(first="KATHY", last="Price Chavez")

    assert match_records([applicant], [employee]).matches == []
    assert len(match_records([applicant], [employee], name_key=key).matches) == 1


def test_tie_prefers_latest_application_on_or_before_hire_date() -> None:
    applicants = [
        make_applicant("early", applied=date(2018, 1, 1)),
        make_applicant("latest-before", applied=date(2019, 1, 15)),  # same day as hire still counts
        make_applicant("after", applied=date(2019, 6, 1)),
    ]
    result = match_records(applicants, [make_employee(hired=date(2019, 1, 15))])

    assert [m.applicant_id for m in result.matches] == ["latest-before"]
    assert result.ambiguous_matches == 1


def test_tie_falls_back_to_earliest_application_when_all_are_after_hire() -> None:
    applicants = [
        make_applicant("later", applied=date(2020, 1, 1)),
        make_applicant("sooner", applied=date(2019, 6, 1)),
    ]
    result = match_records(applicants, [make_employee(hired=date(2019, 1, 15))])
    assert [m.applicant_id for m in result.matches] == ["sooner"]


def test_tie_on_same_date_goes_to_smallest_applicant_id() -> None:
    applicants = [
        make_applicant("B", applied=date(2019, 1, 1)),
        make_applicant("A", applied=date(2019, 1, 1)),
    ]
    for ordering in (applicants, applicants[::-1]):
        result = match_records(ordering, [make_employee(hired=date(2019, 2, 1))])
        assert [m.applicant_id for m in result.matches] == ["A"]


def test_tie_detection_uses_normalised_names() -> None:
    applicants = [
        make_applicant("1", first="MARIANNE"),
        make_applicant("2", first="marianne", applied=date(2019, 1, 2)),
    ]
    result = match_records(applicants, [make_employee()])
    assert result.ambiguous_matches == 1
    assert [m.applicant_id for m in result.matches] == ["2"]


def test_exact_duplicate_applicant_rows_are_not_ambiguous() -> None:
    result = match_records([make_applicant(), make_applicant()], [make_employee()])
    assert len(result.matches) == 1
    assert result.ambiguous_matches == 0


def test_exact_duplicate_employee_rows_produce_one_match() -> None:
    result = match_records([make_applicant()], [make_employee(), make_employee()])
    assert len(result.matches) == 1
    assert result.duplicate_employee_rows == 1
    assert result.employee_rows == 2


def test_result_is_sorted_and_independent_of_input_order() -> None:
    applicants = [make_applicant(str(i), first=f"F{i}", last=f"L{i}") for i in range(20)]
    employees = [
        make_employee(str(100 - i), first=f"f{i}", last=f"l{i}", hired=date(2019, 1, 1 + i)) for i in range(20)
    ]
    expected = match_records(applicants, employees).matches

    rng = random.Random(20240101)
    for _ in range(5):
        shuffled_a, shuffled_e = applicants[:], employees[:]
        rng.shuffle(shuffled_a)
        rng.shuffle(shuffled_e)
        assert match_records(shuffled_a, shuffled_e).matches == expected
    assert [m.employee_id for m in expected] == sorted(m.employee_id for m in expected)


def test_employees_may_be_a_one_shot_iterator() -> None:
    consumed = []

    def stream() -> Iterator[Employee]:
        for i in range(3):
            consumed.append(i)
            yield make_employee(str(i))

    result = match_records(iter([make_applicant()]), stream())
    assert consumed == [0, 1, 2]
    assert (result.applicant_rows, result.employee_rows, len(result.matches)) == (
        1,
        3,
        3,
    )


def test_match_classmethod_is_backwards_compatible() -> None:
    applicants, employees = [make_applicant()], [make_employee()]
    assert Match.match(applicants, employees) == match_records(applicants, employees).matches


# --- differential test against a brute-force restatement of the rules ------


def reference_matches(applicants: Sequence[Applicant], employees: Sequence[Employee]) -> set[Match]:
    """O(A*E) restatement of the documented rules, written independently of the implementation."""

    def same_name(a: Applicant, e: Employee) -> bool:
        def norm(s: str) -> str:
            return " ".join(s.split()).lower()  # inputs below are ASCII, so lower() == casefold()

        return norm(a.first_name) == norm(e.first_name) and norm(a.last_name) == norm(e.last_name)

    result = set()
    for e in employees:
        candidates = [a for a in applicants if same_name(a, e)]
        if not candidates:
            continue
        before = [a for a in candidates if a.application_date <= e.hire_date]
        pool = before or candidates
        target = max(a.application_date for a in pool) if before else min(a.application_date for a in pool)
        chosen = min(
            (a for a in pool if a.application_date == target),
            key=lambda a: a.applicant_id,
        )
        result.add(Match.from_pair(chosen, e))
    return result


def random_name(rng: random.Random, pool: Sequence[str]) -> str:
    name = rng.choice(pool)
    name = rng.choice([name, name.upper(), name.lower(), name.title()])
    return " " * rng.randint(0, 1) + name.replace(" ", " " * rng.randint(1, 2)) + " " * rng.randint(0, 1)


def test_matches_brute_force_reference_on_random_data() -> None:
    rng = random.Random(1234)
    firsts = ["Ann", "Kathy", "Katherine", "Chris", "Jo", "Mary Ann"]
    lasts = [
        "Smith",
        "Price-Chavez",
        "Price Chavez",
        "O'Brien",
        "Lee",
        "Brown Alexander",
    ]
    start = date(2015, 1, 1)

    applicants = [
        make_applicant(
            str(i),
            random_name(rng, firsts),
            random_name(rng, lasts),
            start + timedelta(rng.randint(0, 1500)),
        )
        for i in range(150)
    ]
    applicants += rng.sample(applicants, 10)  # exact duplicate rows
    employees = []
    for i in range(300):
        hired = start + timedelta(rng.randint(0, 2000))
        term = hired + timedelta(rng.randint(0, 400)) if rng.random() < 0.5 else None
        employees.append(
            make_employee(
                str(1000 + i % 220),
                random_name(rng, firsts),
                random_name(rng, lasts),
                hired,
                term,
            )
        )
    employees += rng.sample(employees, 15)  # exact duplicate rows
    rng.shuffle(employees)

    result = match_records(applicants, employees)

    assert set(result.matches) == reference_matches(applicants, employees)
    assert len(result.matches) == len(set(result.matches))
    keys = [(m.employee_id, m.employee_hire_date, m.applicant_id) for m in result.matches]
    assert keys == sorted(keys)
    # Make sure the random data actually exercises the tie-break and de-duplication paths.
    assert result.ambiguous_matches > 0
    assert result.duplicate_employee_rows > 0
