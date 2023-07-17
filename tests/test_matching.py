from src.applicant_employee_match import matching
from datetime import date as dtdate

def test_sample():
    "Sample test to ensure 'pytest' is working properly"
    applicant = {
        'applicant_id': '123',
        'first_name': 'Mary',
        'last_name': 'Doe',
        'application_date': dtdate(2020, 1, 1)
    }
    assert matching.Applicant(**applicant).model_dump() == applicant

# def test_no_matches():
#     applicant = matching.Applicant(
#         applicant_id='ABC',
#         first_name='Marianne',
#         last_name='Smith',
#         application_date=date(2019, 1, 1),
#     )
#     employee1 = matching.Employee(
#         employee_id='1234',
#         hire_date=date(2019, 1, 15),
#         first_name='Tara',
#         last_name='Johnson',
#         term_date=date(2019, 2, 2),
#     )

#     result = matching.Match.match(
#         applicants=[applicant],
#         employees=[employee1],
#     )

#     assert len(result) == 0

# def test_same_name_different_id():
#     applicant = matching.Applicant(
#         applicant_id='ABC',
#         first_name='Marianne',
#         last_name='Smith',
#         application_date=date(2019, 1, 1),
#     )
#     employee1 = matching.Employee(
#         employee_id='1234',
#         hire_date=date(2019, 1, 15),
#         first_name='Marianne',
#         last_name='Smith',
#         term_date=date(2019, 2, 2),
#     )
#     employee2 = matching.Employee(
#         employee_id='9988',
#         hire_date=date(2019, 8, 3),
#         first_name='Marianne',
#         last_name='Smith',
#         term_date=date(2019, 12, 3),
#     )

#     result = matching.Match.match(
#         applicants=[applicant],
#         employees=[employee1, employee2],
#     ) 

#     assert len(result) == 1

#     assert result[0].name == "Marianne"
#     expected_first_names = {'Marianne'}
#     actual_first_names = {result[0].applicant_first_name, result[1].applicant_first_name}
#     assert expected_first_names == actual_first_names

#     assert result[0].employee_id == "1234"
#     assert result[1].employee_id == "1234"
    


def test_same_id_different_name():
    applicant = matching.Applicant(
        applicant_id='ABC',
        first_name='Marianne',
        last_name='Smith',
        application_date=dtdate(2019, 1, 1),
    )
    employee1 = matching.Employee(
        employee_id='1234',
        hire_date=dtdate(2019, 1, 15),
        first_name='Marianne',
        last_name='Smith',
        term_date=dtdate(2019, 2, 2),
    )
    employee2 = matching.Employee(
        employee_id='1234',
        hire_date=dtdate(2019, 8, 3),
        first_name='Marianne',
        last_name='Smith',
        term_date=dtdate(2019, 12, 3),
    )

    result = matching.Match.match(
        applicants=[applicant],
        employees=[employee1, employee2],
    ) 

    print(result)
    assert len(result) == 2

    expected_first_names = {'Marianne'}
    actual_first_names = {
        result[0].employee_first_name, 
        result[1].employee_first_name, 
        result[0].applicant_first_name, 
        result[1].applicant_first_name
    }
    assert expected_first_names == actual_first_names

    assert result[0].employee_id == "1234"
    assert result[1].employee_id == "1234"

