"""One entry point for the desktop, command-line tools and frozen executable."""
from __future__ import annotations

import argparse
import os
import sys


def main(argv=None) -> int:
    from echosign.runtime import application_root

    os.chdir(application_root())
    args = list(sys.argv[1:] if argv is None else argv)
    if args and args[0] == "--sign":
        from echosign.browser import sign

        return sign(args[1:])
    if args and args[0] in ("devices", "run", "test", "demo", "code", "webhook-test"):
        from echosign.monitor import main as monitor_main

        return monitor_main(args)
    parser = argparse.ArgumentParser(
        prog="EchoSign", description="不带参数启动桌面界面。",
        epilog="命令行：devices · run · test · demo · code · webhook-test；使用 <命令> --help 查看选项。")
    from echosign import __version__

    parser.add_argument("--version", action="version", version=f"EchoSign v{__version__}")
    parser.add_argument("--login", action="store_true", help="打开浏览器，登录上课啦")
    parser.add_argument("--check-runtime", metavar="REPORT", help=argparse.SUPPRESS)
    options = parser.parse_args(args)
    if options.check_runtime:
        from echosign.runtime import check_runtime

        return check_runtime(options.check_runtime)
    if options.login:
        from echosign.browser import login

        return login()
    from echosign.gui import main as gui_main

    return gui_main()


if __name__ == "__main__":
    sys.exit(main())
