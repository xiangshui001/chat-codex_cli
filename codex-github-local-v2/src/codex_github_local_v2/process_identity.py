"""Verify process identity before recovering a task left by a dead worker."""
import os
from pathlib import Path
import signal
import time

from .mvp0_runner import MvpError


def identity(pid):
    try:
        raw=(Path('/proc')/str(pid)/'stat').read_text()
        fields=raw[raw.rfind(')')+2:].split()
        return {'pid':pid,'start':fields[19]} if fields[0]!='Z' else None
    except (OSError,IndexError):return None


def alive(lease):
    return isinstance(lease,dict) and bool(lease.get('start')) and identity(lease.get('pid'))==lease


def stop(lease):
    if not alive(lease):return
    # Child model/command/Git processes start a new group. Refuse the listener's own group.
    pid=lease['pid']
    if os.getpgid(pid)!=pid:raise MvpError('process_cleanup_unconfirmed')
    os.killpg(pid,signal.SIGTERM)
    end=time.monotonic()+3
    while alive(lease) and time.monotonic()<end:time.sleep(.1)
    if alive(lease):os.killpg(pid,signal.SIGKILL)
