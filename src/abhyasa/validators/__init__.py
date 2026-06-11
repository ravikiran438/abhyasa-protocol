# Copyright 2026 Ravi Kiran Kadaboina
# Licensed under the Apache License, Version 2.0.

"""Runtime validators for obligations received over the wire."""

from abhyasa.validators.admissibility import (
    AdmissibilityError,
    require_admissible,
)

__all__ = [
    "AdmissibilityError",
    "require_admissible",
]
