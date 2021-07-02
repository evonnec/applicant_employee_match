from datetime import date

import matching

def test_sample():
    "Sample test to ensure 'pytest' is working properly"
    applicant = {
        'applicant_id': '123',
        'first_name': 'Mary',
        'last_name': 'Doe',
        'application_date': date(2020, 1, 1)
    }
    assert matching.Applicant(**applicant).dict() == applicant
