"""Install the eval fake in harness child processes."""
import subprocess

import fake_mac

_run, _popen = subprocess.run, subprocess.Popen


def run(args, **kwargs):
    return fake_mac.run(args, **kwargs) or _run(args, **kwargs)


def popen(args, **kwargs):
    return fake_mac.popen(args, **kwargs) or _popen(args, **kwargs)


subprocess.run, subprocess.Popen = run, popen
