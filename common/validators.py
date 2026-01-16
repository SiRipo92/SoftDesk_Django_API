"""
Common validation helpers shared across apps.

Keep these functions framework-agnostic (no DRF / no Django imports),
so they can be reused in:
- Django model clean()
- DRF serializers
- pure unit tests
"""

from __future__ import annotations

from datetime import date
from typing import Any, Final

MIN_SIGNUP_AGE_YEARS: Final[int] = 15


def calculate_age(birth_date: date, *, today: date | None = None) -> int:
    """
    Calculate age in years from a birth date.

    Args:
        birth_date (date): Birth date.
        today (date | None): Override "today" for deterministic tests.

    Returns:
        int: Age in full years.
    """
    if today is None:
        today = date.today()

    return today.year - birth_date.year - (
        (today.month, today.day) < (birth_date.month, birth_date.day)
    )


def validate_birth_date_min_age(
    birth_date: date,
    *,
    min_age_years: int = MIN_SIGNUP_AGE_YEARS,
    today: date | None = None,
) -> None:
    """
    Enforce birth_date business rules:
    - not in the future
    - age >= min_age_years

    Args:
        birth_date (date): Birth date to validate.
        min_age_years (int): Minimum allowed age.
        today (date | None): Override "today" for deterministic tests.

    Raises:
        ValueError: If the birth_date violates a rule.
    """
    if today is None:
        today = date.today()

    if birth_date > today:
        raise ValueError("La date de naissance ne peut pas être dans le futur.")

    if calculate_age(birth_date, today=today) < min_age_years:
        raise ValueError("Vous devez avoir au moins 15 ans pour vous inscrire.")

# Validation logic for accepting contributors
# based on either a provided Email OR Username

def validate_exactly_one_provided(**fields: Any) -> None:
   """
   Ensure exactly one field among the provided kwargs is truthy.


   Example:
       validate_exactly_one_provided(username="bob", email=None) (Possible)
       validate_exactly_one_provided(username=None, email=None)  (Impossible)
       validate_exactly_one_provided(username="bob", email="x")  (Impossible)


   Raises:
       ValueError: if zero or more than one field is provided.
   """
   provided = [name for name, value in fields.items() if value]
   if len(provided) != 1:
       names = " / ".join(fields.keys())
       raise ValueError(f"Fournir exactement un champ: {names}.")
