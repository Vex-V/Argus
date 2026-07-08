"""Shared pytest fixtures.

The provider and analyzer tests exercise the real modules / ASGI apps
in-process. They are self-contained and do not require the Dockerized
PostgreSQL (providers and analyzers are stateless); services that call an
external tool/API degrade gracefully offline, and those paths are skipped or
asserted-empty rather than hitting the network.
"""
