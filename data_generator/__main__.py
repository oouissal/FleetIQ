"""Allow running the generator as `python -m data_generator`."""

from data_generator.cli import main

if __name__ == "__main__":
    raise SystemExit(main())
