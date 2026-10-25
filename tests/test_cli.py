"""End-to-end tests for the command-line interface."""

import os
import subprocess
import sys
from collections.abc import Callable
from pathlib import Path

import pytest

from applicant_employee_match.matching import MATCH_COLUMNS, main

MakeCsv = Callable[..., Path]  # the `make_csv` fixture from conftest.py

APPLICANTS = "applicant_id,application_date,first_name,last_name\n1,2019-01-01,Ann,Lee\n2,2019-03-01,Bob,Price-Chavez\n"
EMPLOYEES = (
    "employee_id,hire_date,first_name,last_name,term_date\n"
    "10,2019-02-01,ANN,LEE,\n"
    "11,2019-04-01,Bob,Price-Chavez,2020-01-01\n"
)


def normalised_bytes(path: Path) -> bytes:
    return path.read_bytes().replace(b"\r\n", b"\n")


def test_end_to_end_reproduces_committed_output(repo_root: Path, tmp_path: Path) -> None:
    """data/output/matches.csv must be exactly what the CLI produces from data/input."""
    out = tmp_path / "matches.csv"
    code = main(
        [
            "--applicant-csv", str(repo_root / "data/input/applicants.csv"),
            "--employee-csv", str(repo_root / "data/input/employees.csv"),
            "--match-out-csv", str(out),
        ]
    )  # fmt: skip
    assert code == 0
    # Line endings are normalised so a checkout with core.autocrlf cannot break the comparison.
    assert normalised_bytes(out) == normalised_bytes(repo_root / "data/output/matches.csv")


def test_summary_goes_to_stderr(make_csv: MakeCsv, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    out = tmp_path / "out.csv"
    assert (
        main(
            [
                "-a",
                str(make_csv("a.csv", APPLICANTS)),
                "-e",
                str(make_csv("e.csv", EMPLOYEES)),
                "-o",
                str(out),
            ]
        )
        == 0
    )
    captured = capsys.readouterr()
    assert captured.out == ""
    assert "Read 2 applicants" in captured.err
    assert "Read 2 employees" in captured.err
    assert "Found 2 matches" in captured.err
    assert f"Wrote 2 matches to {out}" in captured.err
    assert "warning" not in captured.err


@pytest.mark.parametrize("extra_args", [[], ["-o", "-"]])
def test_stdout_is_the_default_output(
    make_csv: MakeCsv, capsys: pytest.CaptureFixture[str], extra_args: list[str]
) -> None:
    args = [
        "-a",
        str(make_csv("a.csv", APPLICANTS)),
        "-e",
        str(make_csv("e.csv", EMPLOYEES)),
        *extra_args,
    ]
    assert main(args) == 0
    lines = capsys.readouterr().out.splitlines()
    assert lines[0] == ",".join(MATCH_COLUMNS)
    assert lines[1:] == [
        "10,ANN,LEE,1,Ann,Lee,2019-01-01,2019-02-01,",
        "11,Bob,Price-Chavez,2,Bob,Price-Chavez,2019-03-01,2019-04-01,2020-01-01",
    ]


def test_data_quality_warnings(make_csv: MakeCsv, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    applicants = make_csv("a.csv", APPLICANTS + "3,2019-01-15,Ann,Lee\n")  # second "Ann Lee"
    employees = make_csv("e.csv", EMPLOYEES + "10,2019-02-01,ANN,LEE,\n12,2019-05-01,Ann,Lee,\n")
    assert (
        main(
            [
                "-a",
                str(applicants),
                "-e",
                str(employees),
                "-o",
                str(tmp_path / "out.csv"),
            ]
        )
        == 0
    )
    err = capsys.readouterr().err
    assert "warning: 2 matches were chosen among several applicants with the same name" in err
    assert "warning: ignored 1 duplicate employee rows" in err
    assert "warning: 1 applicants matched more than one employee_id" in err


def test_missing_input_file(tmp_path: Path, make_csv: MakeCsv, capsys: pytest.CaptureFixture[str]) -> None:
    code = main(["-a", str(tmp_path / "nope.csv"), "-e", str(make_csv("e.csv", EMPLOYEES))])
    assert code == 1
    assert "error: applicant CSV not found" in capsys.readouterr().err


def test_input_that_is_a_directory(tmp_path: Path, make_csv: MakeCsv, capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["-a", str(make_csv("a.csv", APPLICANTS)), "-e", str(tmp_path)]) == 1
    assert "error: employee CSV not found (or not a file)" in capsys.readouterr().err


def test_invalid_input_fails_without_touching_existing_output(
    make_csv: MakeCsv, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    out = tmp_path / "out.csv"
    out.write_text("previous run\n")
    employees = make_csv("e.csv", EMPLOYEES + "12,2019-99-01,Cy,Ng,\n")
    assert (
        main(
            [
                "-a",
                str(make_csv("a.csv", APPLICANTS)),
                "-e",
                str(employees),
                "-o",
                str(out),
            ]
        )
        == 1
    )
    assert "e.csv:4: hire_date='2019-99-01'" in capsys.readouterr().err
    assert out.read_text() == "previous run\n"


def test_refuses_to_overwrite_an_input(make_csv: MakeCsv, capsys: pytest.CaptureFixture[str]) -> None:
    applicants, employees = make_csv("a.csv", APPLICANTS), make_csv("e.csv", EMPLOYEES)
    assert main(["-a", str(applicants), "-e", str(employees), "-o", str(employees)]) == 1
    assert "refusing to overwrite the employee input" in capsys.readouterr().err
    assert employees.read_text() == EMPLOYEES


def test_refuses_to_overwrite_an_input_through_a_hard_link(
    make_csv: MakeCsv, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    applicants, employees = make_csv("a.csv", APPLICANTS), make_csv("e.csv", EMPLOYEES)
    link = tmp_path / "link.csv"
    os.link(applicants, link)
    assert main(["-a", str(applicants), "-e", str(employees), "-o", str(link)]) == 1
    assert "refusing to overwrite the applicant input" in capsys.readouterr().err
    assert applicants.read_text() == APPLICANTS


def test_refuses_to_overwrite_an_input_spelled_in_another_case(
    make_csv: MakeCsv, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """On a case-insensitive file system (the macOS and Windows default) A.CSV is the same file as a.csv."""
    applicants, employees = make_csv("a.csv", APPLICANTS), make_csv("e.csv", EMPLOYEES)
    if not (tmp_path / "A.CSV").exists():
        pytest.skip("file system is case-sensitive")
    assert main(["-a", str(applicants), "-e", str(employees), "-o", str(tmp_path / "A.CSV")]) == 1
    assert "refusing to overwrite the applicant input" in capsys.readouterr().err
    assert applicants.read_text() == APPLICANTS


def test_unwritable_output_location(make_csv: MakeCsv, tmp_path: Path, capsys: pytest.CaptureFixture[str]) -> None:
    out = tmp_path / "no-such-dir" / "out.csv"
    assert (
        main(
            [
                "-a",
                str(make_csv("a.csv", APPLICANTS)),
                "-e",
                str(make_csv("e.csv", EMPLOYEES)),
                "-o",
                str(out),
            ]
        )
        == 1
    )
    assert "error:" in capsys.readouterr().err


@pytest.mark.parametrize(
    ("relative", "message"),
    [("no-such-dir/out.csv", "output directory not found"), (".", "output path is a directory")],
)
def test_unwritable_output_fails_before_reading_inputs(
    make_csv: MakeCsv, tmp_path: Path, capsys: pytest.CaptureFixture[str], relative: str, message: str
) -> None:
    # The employee file is invalid too: the output error must win because inputs are never read.
    employees = make_csv("e.csv", EMPLOYEES + "12,2019-99-01,Cy,Ng,\n")
    code = main(["-a", str(make_csv("a.csv", APPLICANTS)), "-e", str(employees), "-o", str(tmp_path / relative)])
    err = capsys.readouterr().err
    assert code == 1
    assert message in err
    assert "Read " not in err
    assert "hire_date" not in err


def test_missing_required_argument_is_a_usage_error(
    capsys: pytest.CaptureFixture[str],
) -> None:
    with pytest.raises(SystemExit) as excinfo:
        main(["-a", "applicants.csv"])
    assert excinfo.value.code == 2
    assert "--employee-csv" in capsys.readouterr().err


# --- the module as a program (subprocesses) ---------------------------------


def run(args: list[str], cwd: Path) -> subprocess.CompletedProcess[str]:
    env = os.environ | {"PYTHONPATH": str(cwd / "src")}
    return subprocess.run(
        [sys.executable, *args],
        cwd=cwd,
        env=env,
        capture_output=True,
        text=True,
        check=False,
    )


def test_broken_pipe_on_stdout_exits_quietly(repo_root: Path, make_csv: MakeCsv) -> None:
    """The reader of stdout is gone before anything is written (e.g. `| true`). Small outputs sit in the
    stdout buffer until exit, so the error must be raised (and handled) by an explicit flush."""
    read_end, write_end = os.pipe()
    os.close(read_end)
    args = ["src/applicant_employee_match/matching.py", "-a", str(make_csv("a.csv", APPLICANTS))]
    with os.fdopen(write_end, "wb") as closed_pipe:
        proc = subprocess.run(
            [sys.executable, *args, "-e", str(make_csv("e.csv", EMPLOYEES))],
            cwd=repo_root,
            stdout=closed_pipe,
            stderr=subprocess.PIPE,
            text=True,
            check=False,
        )
    assert proc.returncode == 1
    assert "Found 2 matches" in proc.stderr
    assert "BrokenPipeError" not in proc.stderr
    assert "Exception ignored" not in proc.stderr


@pytest.mark.skipif(not os.path.exists("/dev/stdin"), reason="needs /dev/stdin")
def test_input_can_be_a_pipe(repo_root: Path, make_csv: MakeCsv) -> None:
    """`-a /dev/stdin` and process substitution (`-a <(cmd)`) pass a pipe, not a regular file."""
    proc = subprocess.run(
        [sys.executable, "src/applicant_employee_match/matching.py", "-a", "/dev/stdin"]
        + ["-e", str(make_csv("e.csv", EMPLOYEES))],
        cwd=repo_root,
        input=APPLICANTS,
        capture_output=True,
        text=True,
        check=False,
    )
    assert proc.returncode == 0, proc.stderr
    assert "Found 2 matches" in proc.stderr


def test_stdout_is_utf8_whatever_the_locale(repo_root: Path, make_csv: MakeCsv, tmp_path: Path) -> None:
    """Standard output gets exactly the bytes -o would write, even where Python's stdout is not UTF-8
    (a Windows console code page, or a Latin-1 locale)."""
    applicants = make_csv("a.csv", APPLICANTS + "3,2019-01-01,Łukasz,Nowak\n")
    employees = make_csv("e.csv", EMPLOYEES + "12,2019-02-01,Łukasz,Nowak,\n")
    out = tmp_path / "out.csv"
    command = [sys.executable, "src/applicant_employee_match/matching.py", "-a", str(applicants), "-e", str(employees)]
    env = os.environ | {"PYTHONIOENCODING": "latin-1"}
    proc = subprocess.run(command, cwd=repo_root, env=env, capture_output=True, check=False)
    assert proc.returncode == 0, proc.stderr
    assert subprocess.run([*command, "-o", str(out)], cwd=repo_root, capture_output=True, check=False).returncode == 0
    assert proc.stdout == out.read_bytes()


def test_importing_the_module_has_no_side_effects(repo_root: Path) -> None:
    proc = run(["-c", "import applicant_employee_match.matching"], repo_root)
    assert (proc.returncode, proc.stdout, proc.stderr) == (0, "", "")


@pytest.mark.parametrize(
    "entry",
    [["src/applicant_employee_match/matching.py"], ["-m", "applicant_employee_match"]],
)
def test_documented_invocations_work(repo_root: Path, tmp_path: Path, entry: list[str]) -> None:
    out = tmp_path / "matches.csv"
    proc = run(
        [
            *entry,
            "-a",
            "data/input/applicants.csv",
            "-e",
            "data/input/employees.csv",
            "-o",
            str(out),
        ],
        repo_root,
    )
    assert proc.returncode == 0, proc.stderr
    assert "Found 600 matches" in proc.stderr
    assert normalised_bytes(out) == normalised_bytes(repo_root / "data/output/matches.csv")
