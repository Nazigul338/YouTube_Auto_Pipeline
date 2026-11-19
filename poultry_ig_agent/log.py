"""Бир жерден лог: консолго жана out/logs/agent.log файлына."""
import logging
import os

from . import config

_done = False


def get(name="poultry"):
    global _done
    lg = logging.getLogger(name)
    if not _done:
        lg.setLevel(logging.INFO)
        fmt = logging.Formatter("%(asctime)s %(levelname)s %(message)s")
        sh = logging.StreamHandler()
        sh.setFormatter(fmt)
        lg.addHandler(sh)
        try:
            os.makedirs(os.path.join(config.OUT_DIR, "logs"), exist_ok=True)
            fh = logging.FileHandler(os.path.join(config.OUT_DIR, "logs", "agent.log"), encoding="utf-8")
            fh.setFormatter(fmt)
            lg.addHandler(fh)
        except OSError:
            pass
        _done = True
    return lg
