"""Generic AST-based mutation testing (mission §8).

A small stdlib `ast` layer, not mutmut/cosmic-ray: mutmut drives pytest itself
and mutates files in place, which can't compose with the clean-room grade()
boundary (fresh tempdir copy + Diff application) without forking that logic,
and it would be the first third-party dependency in an otherwise stdlib-only
kernel+runner+integrity stack (see docs/agents/ORACLE.md).
"""
