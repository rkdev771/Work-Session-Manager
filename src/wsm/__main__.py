"""Allow Work Session Manager to run with ``python -m wsm``."""

from wsm.cli import main


if __name__ == "__main__":
    raise SystemExit(main())

