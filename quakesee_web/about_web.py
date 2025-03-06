import panel as pn
import sys
import obspy
import numpy as np
import requests
import pandas as pd
import plotly

class About(pn.Column):
    def __init__(self, **params):
        super().__init__(**params)
        self.create_widgets()

    def create_widgets(self):
        # Header dengan nama program
        header = pn.pane.Markdown(
            "## QuakeSee - Seismic Event Viewer\n"
            "QuakeSee is an application for visualizing earthquake data, including event locations, "
            "instrument response, and waveforms from various seismic station networks.\n",
            styles={"font-size": "16pt", "font-family": "Segoe UI", "padding": "10px"}
        )

        # Deskripsi program
        description = pn.pane.Markdown(
            "**Disclaimer:**\n\n"
            "We are not responsible for any data processing errors that may occur in this program. "
            "Users are encouraged to verify processing results before making decisions based on the "
            "information provided.\n\n"
            "**About the Program:**\n\n"
            "QuakeSee is an application designed to visualize earthquake data with features such as displaying "
            "earthquake event locations, instrument responses, and waveforms obtained from various seismic station "
            "networks worldwide.\n\n"
            "**Developer Information:**\n\n"
            "This program was developed by:\n\n"
            "The QuakeSee Development Team - Yudha Styawan\n\n"
            "Lecturer, Geophysics Engineering - Institut Teknologi Sumatera\n\n"
            "Contact: yudhastyawan26@gmail.com",
            styles={"font-size": "12pt", "font-family": "Segoe UI", "padding": "10px", "width": "350px"}
        )

        # Tabel informasi versi library
        version_data = {
            "Library": ["Python", "Obspy", "Panel", "Plotly", "Numpy", "Requests"],
            "Version": [
                sys.version.split()[0],
                obspy.__version__,
                pn.__version__,
                plotly.__version__,
                np.__version__,
                requests.__version__
            ],
            "Description": [
                "Interpreter used to run the program",
                "Library for seismic data processing",
                "Library for web application",
                "Library for creating graphics",
                "Library for numerical computation",
                "HTTP library for web requests"
            ]
        }

        # Konversi ke DataFrame
        version_df = pd.DataFrame(version_data).set_index("Library")

        # Buat tabel menggunakan DataFrame
        version_table = pn.widgets.DataFrame(
            version_df, 
            name='DataFrame'
            )

        # Susun layout
        self.extend([
            header,
            description,
            pn.pane.Markdown("### Library Versions:", styles={"padding": "10px"}),
            version_table
        ])