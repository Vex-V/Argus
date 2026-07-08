"""Argus shared library — schemas, ORM models, config and utilities.

Every service imports from this package so that the wire contracts
(Pydantic schemas) and the storage contracts (SQLAlchemy models) stay
in exactly one place.
"""
