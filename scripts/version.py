"""
Spectra version generator.

Format: YYYY.MM.DD[.patch]
Examples: 2026.03.07, 2026.03.07.1

Usage:
    python version.py          # prints current date version
    python version.py --patch 2  # prints 2026.03.07.2
"""

import argparse
import datetime


def get_version(patch: int | None = None) -> str:
    """Generate a date-based version string."""
    today = datetime.date.today()
    base = f"{today.year}.{today.month:02d}.{today.day:02d}"
    if patch and patch > 0:
        return f"{base}.{patch}"
    return base


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate date-based version")
    parser.add_argument("--patch", type=int, default=None, help="Patch number suffix")
    args = parser.parse_args()
    print(get_version(args.patch))


if __name__ == "__main__":
    main()
