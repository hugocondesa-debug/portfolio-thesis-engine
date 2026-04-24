"""HTTP Basic Auth dependency.

Single-user model — credentials sourced from :class:`APISettings`. Uses
:func:`secrets.compare_digest` to defeat trivial timing attacks even
though the user count is one.
"""

from __future__ import annotations

import secrets
from typing import Annotated

from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from api.config import settings

security = HTTPBasic()


def verify_credentials(
    credentials: Annotated[HTTPBasicCredentials, Depends(security)],
) -> str:
    """Return ``credentials.username`` on success; raise 401 otherwise."""
    correct_user = secrets.compare_digest(
        credentials.username.encode(), settings.user.encode()
    )
    correct_pass = secrets.compare_digest(
        credentials.password.encode(), settings.password.encode()
    )
    if not (correct_user and correct_pass):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid credentials",
            headers={"WWW-Authenticate": "Basic"},
        )
    return credentials.username


# Type alias for use in route signatures: `_: AuthDep`.
AuthDep = Annotated[str, Depends(verify_credentials)]
