"""
Sample data generation for mock AISR server
"""

from datetime import datetime, timedelta
import random


def get_sample_vaccination_data(school_id: str) -> str:
    """
    Generate sample vaccination data in AISR format (pipe-delimited).
    Different schools get different sample data.
    
    Args:
        school_id: School identifier to generate data for
        
    Returns:
        CSV content in AISR format
    """
    # Header
    header = "id_1|id_2|name|dob|vaccine_group_name|vaccination_date\n"
    
    # Sample data varies by school
    if school_id == "2542":  # Friendly Hills Mid
        students = [
            {"id_1": "123", "id_2": "456", "name": "John Doe", "dob": "2010-01-01"},
            {"id_1": "789", "id_2": "101", "name": "Jane Smith", "dob": "2011-02-02"},
            {"id_1": "112", "id_2": "131", "name": "Bob Johnson", "dob": "2012-03-03"},
            {"id_1": "415", "id_2": "161", "name": "Alice Brown", "dob": "2009-04-04"},
        ]
    elif school_id == "2543":  # Garlough Elementary (example second school)
        students = [
            {"id_1": "234", "id_2": "567", "name": "Charlie Wilson", "dob": "2013-05-05"},
            {"id_1": "345", "id_2": "678", "name": "Diana Davis", "dob": "2014-06-06"},
            {"id_1": "456", "id_2": "789", "name": "Edward Miller", "dob": "2015-07-07"},
        ]
    else:  # Default/other schools
        students = [
            {"id_1": "999", "id_2": "888", "name": "Test Student", "dob": "2010-01-01"},
            {"id_1": "777", "id_2": "666", "name": "Sample Child", "dob": "2011-02-02"},
        ]
    
    # Generate vaccination records
    vaccines = ["COVID-19", "Flu", "MMR", "DTaP", "Polio", "Hepatitis B"]
    records = []
    
    for student in students:
        # Each student gets 2-4 random vaccines
        num_vaccines = random.randint(2, 4)
        selected_vaccines = random.sample(vaccines, num_vaccines)
        
        for vaccine in selected_vaccines:
            # Generate random vaccination date within last 2 years
            days_ago = random.randint(30, 730)
            vax_date = datetime.now() - timedelta(days=days_ago)
            
            record = f"{student['id_1']}|{student['id_2']}|{student['name']}|{student['dob']}|{vaccine}|{vax_date.strftime('%m/%d/%Y')}\n"
            records.append(record)
    
    return header + "".join(records)


def get_sample_query_data(school_id: str) -> str:
    """
    Generate sample query data for bulk uploads.
    
    Args:
        school_id: School identifier
        
    Returns:
        CSV content for student queries
    """
    header = "student_id,first_name,last_name,dob\n"
    
    if school_id == "2542":  # Friendly Hills Mid
        students = [
            "123,John,Doe,2010-01-01",
            "789,Jane,Smith,2011-02-02", 
            "112,Bob,Johnson,2012-03-03",
            "415,Alice,Brown,2009-04-04",
        ]
    elif school_id == "2543":  # Garlough Elementary
        students = [
            "234,Charlie,Wilson,2013-05-05",
            "345,Diana,Davis,2014-06-06",
            "456,Edward,Miller,2015-07-07",
        ]
    else:  # Default
        students = [
            "999,Test,Student,2010-01-01",
            "777,Sample,Child,2011-02-02",
        ]
    
    return header + "\n".join(students) + "\n"