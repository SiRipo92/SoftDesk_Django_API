"""
Users app models.

Defines SoftDesk Support's custom User model (extends Django's AbstractUser),
including RGPD-related fields and metadata timestamps.

Business rule (double lock):
- API boundary: enforced by serializer validation
- Model boundary: enforced by `clean()` + `save()` calling `full_clean()`
"""

from __future__ import annotations

from typing import Any

from django.contrib.auth.models import AbstractUser
from django.core.exceptions import ValidationError
from django.db import models
from django.utils import timezone

from common.validators import calculate_age, validate_birth_date_min_age


class User(AbstractUser):
    """
    Custom User for SoftDesk Support.

    RGPD fields:
        - birth_date: must not be in the future, and must imply age >= 15
        - can_be_contacted: consent to be contacted
        - can_data_be_shared: consent for data sharing

    Notes:
        - The serializer can decide whether birth_date is required for a given endpoint
          (signup requires it, PATCH may treat it as optional),
          BUT when provided it must always respect model validation.
        - `save()` calls `full_clean()` so the rule applies outside the API too.
    """

    email = models.EmailField(unique=True, null=True, blank=True)
    birth_date = models.DateField(null=False, blank=False)

    can_be_contacted = models.BooleanField(default=False)
    can_data_be_shared = models.BooleanField(default=False)

    created_at = models.DateTimeField(default=timezone.now, editable=False)
    updated_at = models.DateTimeField(auto_now=True)

    # Used by createsuperuser flow (Django management command), not by DRF.
    REQUIRED_FIELDS: list[str] = ["email", "birth_date"]

    @property
    def age(self) -> int | None:
        """
        Compute the user's age in years.

        Returns:
            int | None: Age if birth_date is set, otherwise None.
        """
        if not self.birth_date:
            return None
        return calculate_age(self.birth_date)

    def clean(self) -> None:
        """
        Model-level validation

        Runs via full_clean() (called inside save()).
        """
        super().clean()

        if self.birth_date is None:
            raise ValidationError({"birth_date": "La date de naissance est requise."})

        try:
            validate_birth_date_min_age(self.birth_date)
        except ValueError as exc:
            raise ValidationError({"birth_date": str(exc)}) from exc

    def save(self, *args: Any, **kwargs: Any) -> None:
        """
        Ensure model validation always runs on save().

        This guarantees `clean()` is applied for:
        - API creates/updates
        - Django admin
        - manage.py shell
        - any internal code path that saves a User
        """
        self.full_clean()
        return super().save(*args, **kwargs)
