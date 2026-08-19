from importlib.metadata import PackageNotFoundError, version

__author__ = "Nicholas Gray"
__copyright__ = "Copyright 2026, The Plasma Foundation Inc."
__credits__ = ["Nicholas Gray"]
__license__ = "Apache-2.0"
__email__ = "Nicholas Gray <nicholas@tier2.tech>"
__status__ = "Development"

try:
    __version__ = version("cylutils")
except PackageNotFoundError:  # pragma: no cover
    __version__ = "unknown"

from .simple_store import Store
