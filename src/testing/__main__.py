"""Allow ``python -m src.testing`` to execute the framework CLI."""

import sys

from .cli import main

if __name__ == "__main__":
    sys.exit(main())
