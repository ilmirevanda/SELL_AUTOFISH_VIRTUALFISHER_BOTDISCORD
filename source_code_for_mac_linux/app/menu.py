#------------------------ IMPORTS --------------------------#
from __future__ import annotations

if __name__ == '__main__':
    from autofishbot import Dispatcher
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Optional

from .config import ConfigManager
from .profile import Profile
from .scheduler import Scheduler, SchStatus, Commands
from .utils import convert_time, debugger, KBHit

if TYPE_CHECKING:
    from autofishbot import Dispatcher

from time import sleep
from math import ceil
from threading import Thread
from os import path
import os
from re import sub
import json
import sys
from datetime import datetime

# RICH IMPORTS
try:
    from rich.console import Console
    from rich.layout import Layout
    from rich.panel import Panel
    from rich.text import Text
    from rich.table import Table
    from rich.live import Live
    from rich.align import Align
    from rich import box
    from rich.style import Style
    RICH_AVAILABLE = True
except ImportError:
    RICH_AVAILABLE = False
    print("RICH LIBRARY NOT FOUND! PLEASE INSTALL IT: pip install rich")

#------------------------ CONSTANTS --------------------------#

DEFAULT_KEYBINDS = {
    'pause': 'P',
    'quit': 'Q',
    'back_to_live_log': 'L',
    'update_leaderboards': '1',
    'show_charms': '2',
    'update_inventory': '3',
    'show_buffs': '4',
}

class NotificationPriority:
    '''Specifies the display time of each notification prio.'''
    VERY_LOW = 1
    LOW: int = 3
    NORMAL: int = 5
    HIGH: int = 10
    VERY_HIGH: int = 30

@dataclass(slots=True)
class Keybinder:
    '''Keybinder class is responsible to load/create/validate keybinds information to be used in menus.'''
    file: str = 'keybinds.json'
    
    keybinds: dict = field(init=False, repr=False)
    _list: list[tuple] = field(default_factory=list)
    
    @property
    def name(self) -> str:
        '''Returns the class name in the correct format.'''
        return f'{self.__class__.__name__}'
    
    @property
    def list(self) -> list[tuple]:
        '''Returns the list of keybinds in a tupled format: key, action (name).'''
        if self._list == []:
            for key, value in self.keybinds.items():
                action = sub('_', ' ', key).title()
                self._list.append((value, action))
        return self._list

    def get_file_path(self) -> str:
        '''Returns the absolute path for the keybinds file.'''
        if getattr(sys, 'frozen', False):
            base_path = path.dirname(sys.executable)
        else:
            base_path = os.getcwd() 
        return path.join(base_path, self.file)

    def loader(self) -> dict:
        '''Loads and validates the stored keybinds.json file.'''
        file_path = self.get_file_path()
        
        if not path.exists(file_path):
            try:
                with open(file_path, 'w') as f:
                    f.write(json.dumps(DEFAULT_KEYBINDS))
                self.keybinds = DEFAULT_KEYBINDS
                return True
            except Exception as e:
                print(f'[E] Failed to create keybinds file: {e}')
                self.keybinds = DEFAULT_KEYBINDS
                return False
        else:
            try:
                with open(file_path, 'r') as f:
                    self.keybinds = json.loads(f.read())
            except json.decoder.JSONDecodeError as e:
                print(f'Menu ({self.name}) - Err: {e}')
                return False
            
            try:
                if self.keybinds.keys() == DEFAULT_KEYBINDS.keys():
                    # Legacy check: if update_inventory is '4' (old default), force reset
                    if self.keybinds.get('update_inventory') == '4':
                        return False
                    return True
                else:
                    return False
            except AttributeError as e:
                print(f'[E] Menu ({self.name}) - Err: {e}')
                return False
    
    def __post_init__(self) -> None:
        if self.loader():
            if DEFAULT_KEYBINDS != self.keybinds:
                print('[*] Custom menu keybinds loaded.')
        else:
            print('[!] Invalid or old keybinds file, loading default.')
            self.keybinds = DEFAULT_KEYBINDS
            try:
                with open(self.get_file_path(), 'w') as f:
                    f.write(json.dumps(DEFAULT_KEYBINDS, indent=4))
            except Exception as e:
                print(f'[E] Failed to update keybinds file: {e}')

@dataclass(slots=True)
class BaseMenu:
    '''Core menu class, contains all basics to elaborate a new Afb menu (GUI/CLI)'''
    
    #Pointers
    config: ConfigManager = field(init=False, repr=False)
    profile: Profile = field(init=False, repr=False)
    dispatcher: object = field(init=False, repr=False)
    sch: Scheduler = field(init=False, repr=False)

    #Attributes
    _items: list[str] = field(default_factory=list)
    current_notification: str = ''
    notification_queue: list[tuple] = field(default_factory=list)
    keybinds: Keybinder = field(default_factory=Keybinder)
    
    @property
    def items(self) -> list[str]:
        return self._items
    
    @items.setter
    def items(self, value: list[str]) -> None:
        self._items = value
        self._on_items_update(value)
        
    def _on_items_update(self, new_items: list[str]) -> None:
        pass
    
    #Flags
    autorun: bool = False
    is_alive: bool = False
    
    #Counters
    rcv_streak: int = 0
    rcv_bypasses: int = 0
        
    #Backend
    _config_list: list[tuple] = field(default_factory=list)
    
    def __post_init__(self) -> None:
        pass
    
    @property
    def name(self) -> str:
        '''Returns the class name in the correct format.'''
        return f'{self.__class__.__name__}'
    
    @property
    def app_list(self) -> list[tuple]:
        '''Constructs and returns the content (in list format) of the app status.'''
        cd = self.dispatcher.cooldown.last
        sch_message = f'{self.sch.status.name} ({len(self.sch.queue)})'
        dsp_message = 'PAUSED' if self.dispatcher.paused else 'FISHING'
        
        if self.sch.status == SchStatus.BREAK:
            sch_message = f'{self.sch.status.name} ({round(self.sch._break_remaining, 1)}s)'
            dsp_message = 'SCH PAUSE'
        elif self.sch.status == SchStatus.BUSY:
            dsp_message = 'WAITING'

        return [
            ('STREAK', self.rcv_streak),
            ('BYPASSES', self.rcv_bypasses),
            ('COOLDOWN', round(cd, 4) if cd else ''),
            ('SCHEDULER', sch_message),
            ('DISPATCHER', dsp_message)
        ]
    
    @property
    def config_list(self) -> list[tuple]:
        '''Constructs and returns the content (in list format) of the config options.'''
        if self._config_list == []:
            def switcher(val: bool) -> str:
                return 'ON' if val else 'OFF'

            self._config_list = [
                ('MORE FISH', switcher(self.config.more_fish)),
                ('MORE TREASURES', switcher(self.config.more_fish)),
                ('AUTO DAILY', switcher(self.config.auto_daily)),
                ('AUTO SELL', switcher(self.config.auto_sell)),
                ('AUTO UPDATE INV', switcher(self.config.auto_update_inventory)),
                ('AUTO BUY BAITS', switcher(self.config.auto_buy_baits)),
                ('FISH ON EXIT', switcher(self.config.fish_on_exit)),
            ]
        return self._config_list
    
    #------------------------ NOTIFICATIONS --------------------------#
    def notify(self, message: str, display_time: float = NotificationPriority.NORMAL, delimiter: str = '...') -> None:
        '''Adds a new notification to the notifications queue.'''
        message = str(message)
        # Simplified for Rich: No strict length limit like curses, but good to keep it sane
        if len(message) > 100:
            message = message[:97] + delimiter
        
        if display_time in [NotificationPriority.HIGH, NotificationPriority.VERY_HIGH]:
            self.notification_queue = [(message, display_time)] + self.notification_queue
        else:
            self.notification_queue.append((message, display_time))
        
    def notifications_thread(self) -> None:
        '''Controls the notification queue and manage its display time.'''
        while True:
            if self.notification_queue != []:
                message, display_time = self.notification_queue.pop(0)
                self.current_notification = message
                sleep(display_time)
                self.current_notification = ''
            else:
                sleep(self.config.refresh_rate)
                
    def run(self, config: ConfigManager, dispatcher: Dispatcher, profile: Profile, scheduler: Scheduler, 
            threads: list[Thread]) -> None:
        """Placeholder for override"""
        pass

    def kill(self) -> None:
        '''Kills the menu activity.'''
        self.is_alive = False

@dataclass(slots=True)
class MainMenu(BaseMenu):
    right_panel_mode: str = 'logs'
    
    def run(self, config: ConfigManager, dispatcher: Dispatcher, profile: Profile, scheduler: Scheduler, 
            threads: list[Thread]) -> None:
        '''Override run to use Rich UI'''
        #Setup class pointers.
        self.config = config
        self.dispatcher = dispatcher
        self.profile = profile
        self.sch = scheduler
        
        notifications_server = Thread(target=self.notifications_thread, daemon=True, name='Notifications server')
        notifications_server.start()

        # Run with Rich
        self.__run__(threads)
    
    def get_header(self) -> Panel:
        """Returns the header panel with the title."""
        return Panel(
            Align.center("[bold magenta]AUTOFISHBOT[/bold magenta] [cyan]v3.3 [/cyan] | [green]PREMIUM EDITION[/green]"),
            style="bold white on black",
            box=box.DOUBLE
        )

    def get_session_info_panel(self) -> Panel:
        config_name = self.config.loaded_config_name if self.config.loaded_config_name else "Unknown"
        username = self.dispatcher.session.username if self.dispatcher and self.dispatcher.session and self.dispatcher.session.username else "Loading..."
        
        grid = Table.grid(expand=True, padding=(0, 1))
        grid.add_column(justify="left", style="white")
        grid.add_column(justify="left", style="white")
        
        grid.add_row("Config :", f"[bold cyan]{config_name}[/bold cyan]")
        grid.add_row("User ID:", f"[bold green]{username}[/bold green]")
        
        return Panel(grid, title="[bold]USER INFO[/bold]", border_style="white", box=box.ROUNDED)

    def get_status_panel(self) -> Panel:
        current_app_list = self.app_list
        grid = Table.grid(expand=True, padding=(0, 1))
        grid.add_column(justify="left", style="white", ratio=1)
        grid.add_column(justify="right", style="green", ratio=1)

        for label, value in current_app_list:
            grid.add_row(str(label), str(value))
        
        return Panel(grid, title="[bold]STATUS[/bold]", border_style="green", box=box.ROUNDED)

    def get_controls_panel(self) -> Panel:
        table = Table(box=None, expand=True, show_header=False, padding=(0,1))
        table.add_column("Key", style="yellow", max_width=6, no_wrap=True)
        table.add_column("Action", style="white")

        # Static controls list
        controls = [
            ("[P]", "Pause"),
            ("[Q]", "Quit"),
            ("[L]", "Back To Live Log"),
            ("[1]", "Update Leaderboards"),
            ("[2]", "Show Charms"),
            ("[3]", "Update Inventory"),
            ("[4]", "Show Buffs"),
        ]
        
        for key, action in controls:
            table.add_row(key, action)
            
        return Panel(table, title="[bold]CONTROLS[/bold]", border_style="yellow", box=box.ROUNDED)

    def get_logs_panel(self) -> Panel:
        log_text = Text()
        max_logs = 20
        current_logs = self.items[-max_logs:] if len(self.items) > max_logs else self.items
        
        if not current_logs:
            log_text.append("Waiting for fish...", style="dim italic")
        else:
            for log in current_logs:
                # Sanitize log to avoid markup errors if log contains brackets
                # But we want to colorize specific keywords, so we apply style manually
                s_log = str(log)
                style = "white"
                
                if "Legendary" in s_log:
                    style = "bold gold1"
                elif "Mythic" in s_log:
                    style = "bold red"
                elif "Exotic" in s_log:
                    style = "bold purple"
                elif "Rare" in s_log:
                    style = "cyan"
                
                # Escape generic brackets to prevent rich markup errors, 
                # but we can't easily escape only 'unsafe' brackets. 
                # Simple approach: render as Text with style
                log_text.append(f"> {s_log}\n", style=style)
        
        return Panel(log_text, title="[bold]LIVE LOGS[/bold]", border_style="cyan", box=box.ROUNDED)

    def get_charms_panel(self) -> Panel:
        table = Table(box=box.SIMPLE, expand=True)
        table.add_column("Charm", style="cyan")
        table.add_column("Quantity", style="white", justify="right")
        
        if self.profile.charms.list:
            for name, quantity in self.profile.charms.list:
                table.add_row(str(name), str(quantity))
        else:
            table.add_row("No Charms data", "Update first!")

        return Panel(table, title="[bold]CHARMS (Press L for Logs)[/bold]", border_style="magenta", box=box.ROUNDED)

    def get_buffs_panel(self) -> Panel:
        table = Table(box=box.SIMPLE, expand=True)
        table.add_column("Buff", style="cyan")
        table.add_column("Value", style="green", justify="right")
        
        if self.profile.buffs.list:
            for name, value in self.profile.buffs.list:
                table.add_row(str(name), str(value))
        else:
            table.add_row("No Buffs data", "Update first!")
            
        return Panel(table, title="[bold]BUFFS (Press L for Logs)[/bold]", border_style="magenta", box=box.ROUNDED)

    def get_leaderboards_panel(self) -> Panel:
        table = Table(box=box.SIMPLE, expand=True)
        table.add_column("Category", style="cyan")
        table.add_column("Rank", style="gold1", justify="right")
        
        if self.profile.leaderboard.list:
            for category, rank in self.profile.leaderboard.list:
                table.add_row(str(category), f"#{rank}")
        else:
            table.add_row("No Leaderboard data", "Update first!")
            
        return Panel(table, title="[bold]LEADERBOARDS (Press L for Inventory)[/bold]", border_style="gold1", box=box.ROUNDED)
    
    def get_inventory_panel(self) -> Panel:
        # Create a main grid to hold everything
        main_grid = Table.grid(expand=True, padding=(0, 0))
        
        # 1. Profile Stats Table
        stats_table = Table(box=None, expand=True, show_header=False, padding=(0, 1))
        stats_table.add_column("Key", style="cyan")
        stats_table.add_column("Value", style="white", justify="right")
        
        if self.profile.list:
            for label, value in self.profile.list:
                stats_table.add_row(str(label), str(value))
        else:
            stats_table.add_row("No Profile Data", "Update first!")
            
        main_grid.add_row(stats_table)
        main_grid.add_row(Text("-" * 30, style="dim white", justify="center")) # Separator

        # 2. Inventory Items Table
        inv_table = Table(box=box.SIMPLE_HEAD, expand=True)
        inv_table.add_column("Item", style="white")
        inv_table.add_column("Amount", style="cyan", justify="right")
        
        if self.profile.inventory.list:
            for amount, name in self.profile.inventory.list:
                inv_table.add_row(str(name), str(amount))
        else:
             inv_table.add_row("Empty Inventory", "-")
             
        main_grid.add_row(inv_table)

        return Panel(main_grid, title="[bold]INVENTORY[/bold]", border_style="blue", box=box.ROUNDED)
        
    def get_quests_panel(self) -> Panel:
        table = Table(box=box.SIMPLE, expand=True)
        table.add_column("Quest", style="cyan")
        table.add_column("Progress", style="green", justify="right")
        if self.profile.quests.list:
            for name, progress in self.profile.quests.list:
                table.add_row(str(name), str(progress))
        else:
            table.add_row("No Quests data", "Update first!")
        return Panel(table, title="[bold]QUESTS[/bold]", border_style="green", box=box.ROUNDED)
        
    def get_exotic_panel(self) -> Panel:
        table = Table(box=box.SIMPLE, expand=True)
        table.add_column("Fish", style="cyan")
        table.add_column("Count", style="green", justify="right")
        if self.profile.exotic_fish.list:
            for name, count in self.profile.exotic_fish.list:
                table.add_row(str(name), str(count))
        else:
            table.add_row("No Exotic data", "Update first!")
        return Panel(table, title="[bold]EXOTIC FISH[/bold]", border_style="purple", box=box.ROUNDED)

    def get_content_panel(self) -> Panel:
        if self.right_panel_mode == 'charms':
            return self.get_charms_panel()
        elif self.right_panel_mode == 'buffs':
            return self.get_buffs_panel()
        elif self.right_panel_mode == 'leaderboards':
            return self.get_leaderboards_panel()
        elif self.right_panel_mode == 'quests':
            return self.get_quests_panel()
        elif self.right_panel_mode == 'exotic':
            return self.get_exotic_panel()
        else:
            return self.get_inventory_panel()

    def get_footer(self) -> Panel:
        grid = Table.grid(expand=True)
        grid.add_column(ratio=1, justify="center")
        grid.add_column(justify="right")
        
        notification = self.current_notification if self.current_notification else "Running smoothly..."
        grid.add_row(
            Text(notification, style="italic white"),
            Text("DISCORD : ilmirevanda", style="bold yellow")
        )
        return Panel(grid, style="blue", box=box.HEAVY_EDGE)

    def __run__(self, threads: list[Thread]) -> None:
        '''
        Redesigned Main Menu with Rich Library for Modern UI.
        '''
        if not RICH_AVAILABLE:
            print("ERROR: Rich library not installed. Cannot run modern UI.")
            sys.exit(1)

        console = Console()
        console.show_cursor(False)
        console.clear()
        
        # Initial Layout
        layout = Layout()
        layout.split(
            Layout(name="header", size=3),
            Layout(name="main_area", ratio=10),
            Layout(name="footer", size=3)
        )
        
        layout["main_area"].split_row(
            Layout(name="left_col", ratio=3),
            Layout(name="right_col", ratio=7)
        )
        
        layout["left_col"].split_column(
            Layout(name="status", size=10),
            Layout(name="session_info", size=4),
            Layout(name="controls", ratio=1)
        )
        
        layout["right_col"].split_column(
            Layout(name="logs", ratio=4),
            Layout(name="dynamic", ratio=6)
        )

        self.is_alive = True
        self.right_panel_mode = 'inventory' # Default to inventory

        # Prepare for input handling
        kb = KBHit()

        # Pre-render static panels to reduce overhead and flickering
        layout["header"].update(self.get_header())
        layout["session_info"].update(self.get_session_info_panel())
        layout["controls"].update(self.get_controls_panel())

        with Live(layout, refresh_per_second=4, screen=True) as live:
            while self.is_alive:
                # 1. Check threads
                for thread in threads:
                    if not thread.is_alive():
                        self.is_alive = False
                        try:
                            with open('debug_exit.log', 'a') as f:
                                f.write(f"[{datetime.now()}] [CRITICAL] Exiting due to THREAD DEATH: {thread.name}\n")
                        except: pass
                        # Exit loop to allow cleanup
                        break
                
                if not self.is_alive:
                    break

                # 2. Update Dynamic UI Components only
                layout["footer"].update(self.get_footer())
                
                # Left Column
                layout["status"].update(self.get_status_panel())
                # config_name and controls are static, no need to update every frame
                
                # Right Column
                layout["logs"].update(self.get_logs_panel())
                layout["dynamic"].update(self.get_content_panel())
                
                # 3. Handle Input (Non-blocking)
                if kb.kbhit():
                    key = kb.getch()
                    try:
                        key_char = key.decode('utf-8').lower()
                    except Exception:
                        key_char = None
                    
                    if key_char:
                        for bind_key, action in self.keybinds.list:
                            if str(bind_key).lower() == key_char:
                                match action:
                                    case 'Pause':
                                        self.dispatcher.pause
                                        self.notify("Toggled Pause", 2)
                                    case 'Quit':
                                        self.kill()
                                    case 'Back To Live Log':
                                        self.right_panel_mode = 'inventory'
                                        self.notify("Back to Inventory", 1)
                                    case 'Sell Inventory':
                                        self.sch.schedule(self.sch.commands.sell)
                                        self.notify("Selling Inventory...", 2)
                                    case 'Update Inventory':
                                        self.sch.schedule(self.sch.commands.profile)
                                        self.right_panel_mode = 'inventory'
                                        self.notify("Updating Inventory...", 2)
                                    case 'Update Leaderboards':
                                        self.sch.schedule(self.sch.commands.pos)
                                        self.notify("Updating Leaderboards...", 2)
                                        self.right_panel_mode = 'leaderboards'
                                    case 'Buy Morefish':
                                        self.sch.schedule(self.sch.commands.morefish)
                                        self.notify("Buying MoreFish...", 2)
                                    case 'Buy Moretreasures':
                                        self.sch.schedule(self.sch.commands.moretreausre)
                                        self.notify("Buying MoreTreasures...", 2)
                                    case 'Claim Daily':
                                        self.sch.schedule(self.sch.commands.daily)
                                        self.notify("Claiming Daily...", 2)
                                    case 'Show Charms':
                                        self.sch.schedule(self.sch.commands.charms)
                                        self.right_panel_mode = 'charms'
                                        self.notify("Showing Charms...", 2)
                                    case 'Show Buffs':
                                        self.sch.schedule(self.sch.commands.buffs)
                                        self.right_panel_mode = 'buffs'
                                        self.notify("Showing Buffs...", 2)
                                    # Show Quests removed as per previous instructions to avoid errors
                                    case 'Show Current Inv':
                                        self.sch.schedule(self.sch.commands.profile)
                                        self.right_panel_mode = 'inventory'
                                        self.notify("Showing Inventory...", 2)
                                    case 'Show Exotic Fishes':
                                        self.sch.schedule(self.sch.commands.profile)
                                        self.right_panel_mode = 'exotic'
                                        self.notify("Showing Exotic Fish...", 2)
                                    case _:
                                        pass
                
                # Sleep a bit to prevent 100% CPU usage
                sleep(0.1)
