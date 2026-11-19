from fastapi import HTTPException, status


def not_implemented(card: str) -> HTTPException:
    """Raise from a stub endpoint so callers can tell "not built yet" apart from a real error."""
    return HTTPException(
        status_code=status.HTTP_501_NOT_IMPLEMENTED,
        detail=f"Not implemented yet. See board card {card}.",
    )
