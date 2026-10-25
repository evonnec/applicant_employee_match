"""Match applicants (ATS data) to employees (HRIS data) by name; see ``.matching``.

Keep this file even though it holds no code. It makes ``applicant_employee_match`` a regular
package. Without it, the directory becomes an implicit namespace package (PEP 420), and this
project's uv_build backend stops with "Expected a Python module at:
src/applicant_employee_match/__init__.py". Because ``uv sync`` installs the project with that
backend, ``uv build``, ``uv sync`` and therefore every ``uv run`` command (tests, ruff, mypy) fail.
Plain pytest with ``pythonpath = ["src"]`` would still pass, so the test suite alone would not catch it.
"""
