"""Backend package bootstrap.

Installs the lightweight sqlite3 connection guard early so direct sqlite users
inside service modules do not leak handles during strict tests or shutdown.
"""
from backend.utils.sqlite_connection_guard import install_sqlite_connection_guard

install_sqlite_connection_guard()
