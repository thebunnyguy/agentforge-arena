def is_adult(age):
    """True for 18 <= age <= 120, False otherwise."""
    if age < 18:
        return False
    if age > 120:
        return False
    return True
