"""Allow running ffcache as a module: python -m ffcache"""

import sys
from ffcache.cli import main

if __name__ == '__main__':
    sys.exit(main())
