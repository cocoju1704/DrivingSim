# Copyright (c) 2026 Kai Braun, Ozan Miguel Gündogdu, Yeri Jikong, Sven Winkelmann
#
# SPDX-License-Identifier: MIT
#
# Licensed under the MIT License. 
# See LICENSE file in the project root for full license information.
# Also consult our README to comply with Third-Party Licenses.

from pathlib import Path

FILE_DIR = Path(__file__).resolve().parent

from tkinter import *
from tkinter import ttk

class Weather:
    """A graphical user interface for real-time CARLA weather manipulation.

    This class creates a Tkinter-based window with sliders to dynamically 
    adjust environmental parameters in the simulation. It maps UI inputs 
    directly to the control methods of a provided CARLA client.

    Attributes:
        client: An instance of the CARLA client (e.g., CarlaClient) 
            responsible for executing weather updates.
        root (Tk): The main Tkinter window instance.
    """
    def __init__(self, client):
        """Initializes the Weather UI with a reference to the simulation client.

        Args:
            client: The client object containing `set_rain` and `set_wind` 
                methods to be controlled via the UI sliders.
        """
        self.client = client
        self.root = Tk()
        self.root.geometry("300x200")
        self._build_ui()
 
    def _build_ui(self):
        """Constructs the Tkinter grid layout, labels, and scale widgets.

        Sets up two horizontal sliders (0-100) that trigger callback 
        functions in the CARLA client whenever a user interacts with them.
        """
        frm = ttk.Frame(self.root, padding=10)
        frm.grid()
 
        ttk.Label(frm, text="Change the Weather in Carla").grid(column=0, row=0)
 
        Label(self.root, text="Set rain intensity").grid(column=0, row=1)
        Label(self.root, text="Set wind intensity").grid(column=1, row=1)
 
        Scale(self.root, from_=0, to=100,
              orient=HORIZONTAL,
              command=self.client.set_rain).grid(column=0, row=2)
 
        Scale(self.root, from_=0, to=100,
              orient=HORIZONTAL,
              command=self.client.set_wind).grid(column=1, row=2)
 
    def run(self):
        """Starts the Tkinter event loop to display the weather control window.

        This method blocks execution until the window is closed.
        """
        self.root.mainloop()