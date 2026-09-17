def is_adult(age):
    """Spec: True for 18 <= age <= 120, False otherwise.

    BUG: off-by-one on the LOWER bound — excludes exactly 18.
    """
    if age < 19:
        return False
    if age > 120:
        return False
    return True
