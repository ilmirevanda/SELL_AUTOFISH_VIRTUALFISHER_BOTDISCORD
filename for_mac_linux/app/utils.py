#------------------------ IMPORTS --------------------------#
from __future__ import annotations
from dataclasses import dataclass, field
from time import time
from typing import Callable, Any
from inspect import stack, trace
from datetime import datetime
from re import sub
import sys
import os

# Platform specific imports
if sys.platform == 'win32':
    import msvcrt
else:
    import termios
    import tty
    import select

#------------------------- FUNCTIONS ---------------------------#
def get_resource_path(relative_path: str) -> str:
    """ Get absolute path to resource, works for dev and for PyInstaller """
    try:
        # PyInstaller creates a temp folder and stores path in _MEIPASS
        base_path = sys._MEIPASS
    except Exception:
        base_path = os.path.abspath(".")

    return os.path.join(base_path, relative_path)

def convert_time(epoch_time: float) -> str:
    '''Converts a given epoch time to readable format.'''
    if not epoch_time:
        return '-'
    date: datetime = datetime.fromtimestamp(epoch_time)
    return date.strftime('%H:%M - %D')

def sanitize(raw_string: str) -> str:
    '''Sanitizes a given string to a safe-to-use format.'''
    emojiless = sub(r':.+?:', '', sub(r'<.+?> ', '', raw_string)) #Removes emotes
    return sub(r'[*_`]', '', sub('[\n\b\t]', ' ', emojiless)) #Removes markdown

def dumper(fn: str, content: Any, path: str = './dumps', mode: str = 'w'):
    '''Writes content to the disk.'''
    with open(f'{path}/{fn}', mode, encoding='utf-8', errors='replace') as f:
        f.write(content)

def make_command(cmd: str, name: str, value: str, type: int = 3) -> tuple:
    '''Builds a tuple containing the command (str) and the 'options' parameter (dict).'''
    parameters = {
        "type": type,
        "name": name,
        "value": value
    }
    return (cmd, parameters)

#------------------------- CLASSES ---------------------------#
@dataclass
class Debugger:
    '''Logs errors and exceptions.'''
    enabled: bool = False
    errors: int = 0
    
    def setup(self, switch : bool) -> None:
        self.enabled = switch
    
    def log(self, event : any = None, id : str = 'Unk') -> None:
        self.errors += 1
        if self.enabled:
            log_data = f'\n[{convert_time(time())}] {id} | [Traceback] {trace()} | [Event] {event} | [Stack] {stack()}\n'
            dumper('debug.log', log_data, '.', 'a')

class KBHit:
    """
    Cross-platform keyboard hit detection.
    Simulates msvcrt.kbhit() and msvcrt.getch() on Unix-like systems.
    """
    def __init__(self):
        self.fd = None
        self.old_term = None
        if sys.platform != 'win32':
            self.fd = sys.stdin.fileno()
            self.old_term = termios.tcgetattr(self.fd)
            # We don't set raw mode here immediately to avoid messing up the console
            # unless we are actively checking/reading. 
            # But typically for kbhit loop, we might need to set it or use select.

    def set_normal_term(self):
        """Restores normal terminal settings."""
        if sys.platform != 'win32' and self.old_term:
            termios.tcsetattr(self.fd, termios.TCSAFLUSH, self.old_term)

    def kbhit(self) -> bool:
        """Returns True if a keypress is waiting to be read."""
        if sys.platform == 'win32':
            return msvcrt.kbhit()
        else:
            # Unix implementation
            try:
                # Set raw mode to read input without waiting for enter
                tty.setcbreak(self.fd)
                dr, dw, de = select.select([sys.stdin], [], [], 0)
                # Restore settings immediately
                termios.tcsetattr(self.fd, termios.TCSAFLUSH, self.old_term)
                return bool(dr)
            except Exception:
                return False

    def getch(self) -> bytes:
        """Reads a single character from input."""
        if sys.platform == 'win32':
            return msvcrt.getch()
        else:
            try:
                tty.setraw(self.fd)
                ch = sys.stdin.read(1)
                termios.tcsetattr(self.fd, termios.TCSAFLUSH, self.old_term)
                return ch.encode('utf-8')
            except Exception:
                return b''

    def __del__(self):
        self.set_normal_term()

#------------------------- INIT ---------------------------#
debugger = Debugger()