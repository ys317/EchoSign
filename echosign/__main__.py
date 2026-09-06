"""Desktop entry point: python -m echosign."""
from __future__ import annotations

import argparse
import os
import sys


def main(argv=None) -> int:
    from echosign.runtime import application_root

    os.chdir(application_root())
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] == "--sign":
        from echosign.browser_sign import main as sign_main

        return sign_main(args[1:])
    parser = argparse.ArgumentParser(prog="EchoSign")
    parser.add_argument("--check-runtime", metavar="REPORT", help=argparse.SUPPRESS)
    options = parser.parse_args(args)
    if options.check_runtime:
        from echosign.runtime import check_runtime

        return check_runtime(options.check_runtime)
    from echosign.gui import main as gui_main

    return gui_main()


if __name__ == "__main__":
    sys.exit(main())
