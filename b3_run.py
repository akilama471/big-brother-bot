__author__ = 'KilerZack'
__version__ = '3.11'

import sys

if sys.version_info < (3,):
    raise SystemExit("Sorry, Python Version Not Compatible!")

import b3.run


def main():
    b3.run.main()


if __name__ == '__main__':
    main()
