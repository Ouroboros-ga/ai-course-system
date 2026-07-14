"""P1-05 Graph platform: GraphStore protocol and fake implementation.

This package provides the abstract GraphStore protocol (consumed by domain code)
and an in-memory fake implementation for testing and prototyping.

Ownership boundary (per plan SS4):
- ``protocol.py`` and ``fakes.py`` are P1-05 owned.
- ORM/migration/endpoint implementations belong to P1-09.
- ``conftest.py`` and shared fakes belong to P1-10.
"""
