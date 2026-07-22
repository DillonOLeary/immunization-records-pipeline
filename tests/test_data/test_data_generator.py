"""
This module generates fake data for tests
"""

import random
import string

import pandas as pd
from faker import Faker

# Create an instance of Faker
fake = Faker()


def generate_test_data(num_rows: int, seed: int = 42) -> pd.DataFrame:
    """
    Function to generate fake data with the columns used by AISR
    """
    random.seed(seed)  # Seed the random number generator

    def random_string(length: int) -> str:
        """Generates a random string of uppercase letters"""
        return "".join(random.choices(string.ascii_uppercase, k=length))

    def random_alphanumeric(length: int) -> str:
        """Generates a random alphanumeric string"""
        return "".join(random.choices(string.ascii_uppercase + string.digits, k=length))

    def random_vaccine_group() -> str:
        """Generates a random vaccine group name"""
        return random.choice(["HepB", "Influenza", "MMR", "Tdap", "Polio", "Varicella"])

    data = {
        "id_1": [random.randint(10000, 99999) for _ in range(num_rows)],
        "id_2": [random.randint(100000, 999999) for _ in range(num_rows)],
        "id_3": [random.randint(1000000000000, 9999999999999) for _ in range(num_rows)],
        "id_4": [random.randint(10000, 99999) for _ in range(num_rows)],
        "id_5": [random.randint(10000, 99999) for _ in range(num_rows)],
        "id_6": [random.randint(10000, 99999) for _ in range(num_rows)],
        "miic_client_id": [random.randint(1000000, 9999999) for _ in range(num_rows)],
        "first_name": [fake.first_name().capitalize() for _ in range(num_rows)],
        "last_name": [fake.last_name().capitalize() for _ in range(num_rows)],
        "birth_date": [
            fake.date_of_birth(minimum_age=5, maximum_age=18).strftime("%Y-%m-%d")
            for _ in range(num_rows)
        ],
        "sex_code": [random.choice(["M", "F"]) for _ in range(num_rows)],
        "race_code": [
            random.choice(["A", "B", "C", "D", "E", "F"]) for _ in range(num_rows)
        ],  # Made-up race codes
        "ethnicity_code": [random.choice(["NH", "U"]) for _ in range(num_rows)],
        "immunization_id": [
            random.randint(10000000, 99999999) for _ in range(num_rows)
        ],
        "vaccine_group_name": [random_vaccine_group() for _ in range(num_rows)],
        "cpt_code": [random.randint(10000, 99999) for _ in range(num_rows)],
        "cvx_code": [random.randint(100, 999) for _ in range(num_rows)],
        "trademark_name": [fake.word() for _ in range(num_rows)],
        "vaccination_date": [
            fake.date_this_decade().strftime("%Y-%m-%d") for _ in range(num_rows)
        ],
        "administration_route_code": [
            random.choice(["IM", "SC", "PO"]) for _ in range(num_rows)
        ],
        "body_site_code": [random.choice(["L", "R", "C"]) for _ in range(num_rows)],
        "manufacturer_code": [random_string(3) for _ in range(num_rows)],
        "historical_ind": [
            random.choice(["00", random_string(3)]) for _ in range(num_rows)
        ],
        "historical_lot_number": [
            random.choice(["00", random_alphanumeric(6)]) for _ in range(num_rows)
        ],
    }
    return pd.DataFrame(data)
