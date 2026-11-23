"""エラーと、結果の do の文（スクリプトの仕様の 1.3、1.5）。"""
import os
import shutil

SCRIPTS_DIR = os.path.dirname(os.path.dirname(os.path.realpath(__file__)))
REVDOC_PY = os.path.join(SCRIPTS_DIR, "revdoc.py")
TEMPLATES_DIR = os.path.join(os.path.dirname(SCRIPTS_DIR), "templates")


class Fail(Exception):
    """1.3 のエラー。extra は、結果の JSON に足す値（missing_packages の packages など）。"""

    def __init__(self, error, message, **extra):
        super().__init__(message)
        self.error = error
        self.message = message
        self.extra = extra


def python_cmd():
    if os.name == "nt":
        return "py -3" if shutil.which("py") else "python"
    return "python3" if shutil.which("python3") else "python"


def cmd(sub, out):
    """1.5 の CMD(sub)。"""
    return "%s '%s' %s --out '%s'" % (python_cmd(), REVDOC_PY, sub, out)


def error_do(fail):
    if fail.error == "missing_packages":
        names = " ".join('"%s"' % n for n in fail.extra["packages"])
        return ("Tell the user in Japanese that these Python packages are missing and that they should run this"
                " themselves: %s -m pip install %s. Then stop. Running the same skill command again starts the work."
                % (python_cmd(), names))
    if fail.error == "no_output":
        return ("Tell the user in Japanese that the subagents wrote no files and that they should check that"
                " subagents can write files in the output folder. Then stop. Running the same skill command again"
                " resumes the work.")
    if fail.error == "input_changed":
        return ("Tell the user in Japanese what the message says and that they can either restore the input and run"
                " the same skill command again, or choose a new output folder to start over. Then stop.")
    return "Tell the user in Japanese what the message says. Then stop."
