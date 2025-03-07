import panel as pn
import param
import pandas as pd
import requests
from datetime import datetime, timedelta
from obspy import UTCDateTime
from obspy.core.event import Catalog, Event, Origin, Magnitude, ResourceIdentifier
import re
from bokeh.plotting import figure
from bokeh.models import ColumnDataSource, BoxEditTool, WMTSTileSource
import pyproj
import io
import zipfile
import time

class EQCatFetcher(pn.Column):
    def __init__(self, **params):
        super().__init__(**params)
        self.eqcat_fetcher = EQCatFetcherParam()
        self._update_layout()
    
    def _update_layout(self):
        self.extend(self.eqcat_fetcher.layout)

class EQCatFetcherParam(param.Parameterized):
    catalog = param.ClassSelector(class_=Catalog, default=None)
    earthquake_data = param.List(default=[])
    output_folder = param.String(default=None)
    status = param.String(default="Status: Waiting to start...")
    progress = param.Number(default=0)
    selected_rectangle = param.List(default=None)
    bot_lat = param.Number(-10, bounds=(-90, 90))
    top_lat = param.Number(6, bounds=(-90, 90))
    left_lon = param.Number(95, bounds=(-180, 180))
    right_lon = param.Number(141, bounds=(-180, 180))

    def __init__(self, **params):
        super().__init__(**params)
        # Transformer untuk konversi koordinat
        self.transformer_to_mercator = pyproj.Transformer.from_crs("EPSG:4326", "EPSG:3857", always_xy=True)
        self.transformer_to_latlon = pyproj.Transformer.from_crs("EPSG:3857", "EPSG:4326", always_xy=True)

        # Sumber data untuk kotak
        self.source = ColumnDataSource(data=self.get_box_data())

        self.create_controls()
        self.create_map()  # Tambahkan peta interaktif
        self.create_layout()
    
    def create_controls(self):
        
        self.map_controls = pn.Column(
            pn.widgets.FloatInput.from_param(self.param.bot_lat, name="Bottom Latitude"),
            pn.widgets.FloatInput.from_param(self.param.top_lat, name="Top Latitude"),
            pn.widgets.FloatInput.from_param(self.param.left_lon, name="Left Longitude"),
            pn.widgets.FloatInput.from_param(self.param.right_lon, name="Right Longitude"),
        )

        # Input fields
        self.start_date = pn.widgets.DatePicker(name="Start Date", value=datetime(2023, 1, 1))
        self.end_date = pn.widgets.DatePicker(name="End Date", value=datetime(2023, 6, 1))
        self.min_mag = pn.widgets.FloatInput(name="Min Magnitude", value=0)
        self.max_mag = pn.widgets.FloatInput(name="Max Magnitude", value=10)
        self.min_dep = pn.widgets.FloatInput(name="Min Depth", value=0)
        self.max_dep = pn.widgets.FloatInput(name="Max Depth", value=700)
        self.step_days = pn.widgets.IntInput(name="Step (days)", value=30)

        # Checkboxes
        self.rec_var = pn.widgets.Checkbox(name="Convert to XML", value=False)
        self.ef_var = pn.widgets.Checkbox(name="Convert to .events (fast loading)", value=True)

        # Status and progress
        self.status_pane = pn.pane.Markdown(self.status, styles={"color": "green"})
        self.progress_bar = pn.widgets.Progress(value=self.progress, sizing_mode="stretch_width")

        self.download_button = pn.widgets.FileDownload(
            callback=lambda: self.download_catalog(),
            filename="earthquake_catalog.zip",
            button_type="primary",
            label="Download Catalog (.zip)"
        )

    def create_map(self):
        # Membuat peta dengan OpenStreetMap (cara lama)
        self.plot = figure(
            x_range=(self.lon_to_mercator(self.left_lon), self.lon_to_mercator(self.right_lon)),
            y_range=(self.lat_to_mercator(self.bot_lat), self.lat_to_mercator(self.top_lat)),
            title="Gambar Kotak untuk Memilih Area",
            tools="pan, wheel_zoom, reset",
            x_axis_type="mercator",
            y_axis_type="mercator",
            width=800,
            height=500
        )

        # Tambahkan basemap OpenStreetMap
        tile_source = WMTSTileSource(url="https://a.tile.openstreetmap.org/{Z}/{X}/{Y}.png")
        self.plot.add_tile(tile_source)

        # Kotak seleksi
        self.rect = self.plot.quad(left="left", right="right", top="top", bottom="bottom", source=self.source, fill_alpha=0.3)

        # Alat gambar kotak
        self.box_tool = BoxEditTool(renderers=[self.rect], num_objects=1)
        self.plot.add_tools(self.box_tool)

        # Hubungkan perubahan input ke kotak
        self.param.watch(self.update_box, ['bot_lat', 'top_lat', 'left_lon', 'right_lon'])

        # Hubungkan perubahan kotak ke input
        self.source.on_change("data", self.update_inputs)

    def get_box_data(self):
        """Menghasilkan data kotak berdasarkan nilai input"""
        return dict(
            left=[self.lon_to_mercator(self.left_lon)],
            right=[self.lon_to_mercator(self.right_lon)],
            top=[self.lat_to_mercator(self.top_lat)],
            bottom=[self.lat_to_mercator(self.bot_lat)],
        )

    def get_box_data(self):
        """Menghasilkan data kotak berdasarkan nilai input"""
        left, bottom = self.lon_to_mercator(self.left_lon), self.lat_to_mercator(self.bot_lat)
        right, top = self.lon_to_mercator(self.right_lon), self.lat_to_mercator(self.top_lat)
        return dict(left=[left], right=[right], top=[top], bottom=[bottom])

    def lon_to_mercator(self, lon):
        """Konversi longitude ke koordinat Mercator menggunakan pyproj"""
        x, _ = self.transformer_to_mercator.transform(lon, 0)
        return x

    def lat_to_mercator(self, lat):
        """Konversi latitude ke koordinat Mercator menggunakan pyproj"""
        _, y = self.transformer_to_mercator.transform(0, lat)
        return y

    def mercator_to_lon(self, x):
        """Konversi dari Mercator ke Longitude menggunakan pyproj"""
        lon, _ = self.transformer_to_latlon.transform(x, 0)
        return lon

    def mercator_to_lat(self, y):
        """Konversi dari Mercator ke Latitude menggunakan pyproj"""
        _, lat = self.transformer_to_latlon.transform(0, y)
        return max(min(lat, 90), -90)  # Jaga agar tetap dalam rentang valid
    
    def update_box(self, *events):
        """Memperbarui kotak saat input berubah"""
        self.source.data = self.get_box_data()

    def update_inputs(self, attr, old, new):
        """Memperbarui input saat kotak diubah"""
        if len(new["left"]) > 0:
            self.left_lon = self.mercator_to_lon(new["left"][0])
            self.right_lon = self.mercator_to_lon(new["right"][0])
            self.bot_lat = self.mercator_to_lat(new["bottom"][0])
            self.top_lat = self.mercator_to_lat(new["top"][0])

    def create_layout(self):

        """Membuat layout utama Panel dengan input dan peta."""
        input_controls = pn.Card(pn.Row(
            pn.Column(
                self.start_date,
                self.end_date,
            ),
            pn.Column(
                self.min_mag,
                self.max_mag,
            ),
            pn.Column(
                self.min_dep,
                self.max_dep,
            ),
            pn.Column(
                self.step_days,
                self.rec_var,
                self.ef_var,
            ),
            sizing_mode="stretch_width"
        ))

        # Status and progress
        status_panel = pn.Column(
            self.status_pane,
            self.progress_bar,
            sizing_mode="stretch_width"
        )

        # Layout utama Panel
        self.layout = pn.Column(
            pn.Row(self.plot, pn.Column(self.map_controls, pn.VSpacer(), self.download_button, status_panel)),
            input_controls,
            sizing_mode="stretch_both"
        )
    
    def convert_to_dict(self, lines):
        catalog = []
        start = False
        for line in lines:
            if "DATA_TYPE EVENT_CATALOGUE" in line:
                start = True
                continue
            if start and line.strip() == "":
                break
            if start:
                # Parsing setiap baris data
                columns = re.split(r',\s*', line.strip())
                if len(columns) < 8:
                    continue  # Abaikan baris yang tidak sesuai format
                
                event_id = columns[0].strip()

                if event_id == "EVENTID": continue
                
                try:
                    # Pastikan data waktu memiliki format yang valid
                    event_date = columns[3].strip()  # Hapus spasi
                    event_time = columns[4].strip()  # Hapus spasi
                    datetime_str = f"{event_date}T{event_time}"  # Gabungkan tanggal dan waktu
                    event_time = UTCDateTime(datetime_str)  # Konversi ke UTCDateTime
                except Exception as e:
                    print(f"Error parsing time for event {event_id}: {e}")
                    continue  # Abaikan jika format tidak valid
                
                latitude = float(columns[5])
                longitude = float(columns[6])
                depth = float(columns[7]) if columns[7] else None
                magnitude_value = float(columns[11])
                magnitude_type = columns[10].strip()

                catalog.append({
                    "time": event_time,
                    "latitude": latitude,
                    "longitude": longitude,
                    "depth": depth,
                    "magnitude": magnitude_value,
                    "magnitude_type": magnitude_type
                })
        return catalog
    
    def convert_to_xml(self, catalog, lines):
        start = False
        for line in lines:
            if "DATA_TYPE EVENT_CATALOGUE" in line:
                start = True
                continue
            if start and line.strip() == "":
                break
            if start:
                # Parsing setiap baris data
                columns = re.split(r',\s*', line.strip())
                if len(columns) < 8:
                    continue  # Abaikan baris yang tidak sesuai format
                
                event_id = columns[0].strip()

                if event_id == "EVENTID": continue
                
                try:
                    # Pastikan data waktu memiliki format yang valid
                    event_date = columns[3].strip()  # Hapus spasi
                    event_time = columns[4].strip()  # Hapus spasi
                    datetime_str = f"{event_date}T{event_time}"  # Gabungkan tanggal dan waktu
                    event_time = UTCDateTime(datetime_str)  # Konversi ke UTCDateTime
                except Exception as e:
                    print(f"Error parsing time for event {event_id}: {e}")
                    continue  # Abaikan jika format tidak valid
                
                latitude = float(columns[5])
                longitude = float(columns[6])
                depth = float(columns[7]) if columns[7] else None
                magnitude_value = float(columns[11])
                magnitude_type = columns[10].strip()

                # Buat objek ObsPy Event
                event = Event(resource_id=ResourceIdentifier(event_id))
                origin = Origin(time=event_time, latitude=latitude, longitude=longitude, depth=depth * 1000)
                magnitude = Magnitude(mag=magnitude_value, magnitude_type=magnitude_type)
                
                event.origins.append(origin)
                event.magnitudes.append(magnitude)
                catalog.events.append(event)

    def build_url(self, params):
        base_url = "http://www.isc.ac.uk/cgi-bin/web-db-run"
        query = (
            f"?request=COMPREHENSIVE&out_format=CATCSV&searchshape=RECT"
            f"&bot_lat={params['bot_lat']}&top_lat={params['top_lat']}"
            f"&left_lon={params['left_lon']}&right_lon={params['right_lon']}"
            f"&start_year={params['start_date'].year}&start_month={params['start_date'].month}&start_day={params['start_date'].day}"
            f"&start_time=00%3A00%3A00"
            f"&end_year={params['end_date'].year}&end_month={params['end_date'].month}&end_day={params['end_date'].day}"
            f"&end_time=23%3A59%3A59"
            f"&min_dep={params['min_dep']}&max_dep={params['max_dep']}"
            f"&min_mag={params['min_mag']}&max_mag={params['max_mag']}"
        )
        return base_url + query
    
    def download_catalog(self):
        beginning = time.time()

        params = {
            "bot_lat": self.bot_lat,
            "top_lat": self.top_lat,
            "left_lon": self.left_lon,
            "right_lon": self.right_lon,
            "start_date": self.start_date.value,
            "end_date": self.end_date.value,
            "min_mag": self.min_mag.value,
            "max_mag": self.max_mag.value,
            "min_dep": self.min_dep.value,
            "max_dep": self.max_dep.value,
            "step_days": self.step_days.value,
        }

        self.progress = 0
        self.progress_bar.value = self.progress
        self.status = "Status: Downloading..."
        self.status_pane.object = self.status

        current_date = params["start_date"]
        end_date = params["end_date"]
        step = timedelta(days=params["step_days"])
        total_steps = (end_date - current_date).days // params["step_days"] + 1
        current_step = 0

        # Buat buffer untuk menyimpan file ZIP
        zip_buffer = io.BytesIO()
        with zipfile.ZipFile(zip_buffer, 'w', zipfile.ZIP_DEFLATED) as zip_file:
            if self.ef_var.value:
                csv_dict = []
                csv_name = f"{current_date.strftime('%Y-%m-%d')}_to_{end_date.strftime('%Y-%m-%d')}.events"

            if self.rec_var.value:
                catalog = Catalog()
                xml_name = f"{current_date.strftime('%Y-%m-%d')}_to_{end_date.strftime('%Y-%m-%d')}.xml"

            while current_date < end_date:
                next_date = min(current_date + step, end_date)
                file_name = f"{current_date.strftime('%Y-%m-%d')}_to_{next_date.strftime('%Y-%m-%d')}.txt"

                params["start_date"], params["end_date"] = current_date, next_date
                url = self.build_url(params)

                try:
                    response = requests.get(url)
                    response.raise_for_status()
                    text = response.text
                    idx = text.find("----EVENT-----")
                    if idx != -1:
                        # Simpan file ke dalam ZIP
                        zip_file.writestr(file_name, text)
                        self.status = f"Downloaded: {file_name}"
                        self.status_pane.object = self.status

                        if self.ef_var.value:
                            textlines = text.splitlines()
                            csv_dict += self.convert_to_dict(textlines)

                        if self.rec_var.value:
                            textlines = text.splitlines()
                            self.convert_to_xml(catalog, textlines)

                    else:
                        self.status = f"{file_name} doesn't have at least one event."
                        self.status_pane.object = self.status

                except requests.exceptions.RequestException as e:
                    self.status = f"Failed to download: {file_name}. Error: {e}"
                    self.status_pane.object = self.status

                current_date = next_date + timedelta(days=1)
                current_step += 1

                # Update progress
                self.progress = int((current_step / total_steps) * 100)
                self.progress_bar.value = self.progress

            if self.ef_var.value:
                df = pd.DataFrame(csv_dict)
                csv_buffer = io.StringIO()
                df.to_csv(csv_buffer, index=False, encoding="utf-8")
                zip_file.writestr(csv_name, csv_buffer.getvalue())
                self.status = f"Data successfully saved to {csv_name}"
                self.status_pane.object = self.status

            if self.rec_var.value:
                xml_buffer = io.StringIO()
                catalog.write(xml_buffer, format="QUAKEML")
                zip_file.writestr(xml_name, xml_buffer.getvalue())
                self.status = f"Data successfully saved to {xml_name}"
                self.status_pane.object = self.status

        # Siapkan FileDownload
        zip_buffer.seek(0)

        execution_time = time.time() - beginning

        self.progress = 100
        self.progress_bar.value = self.progress

        self.status = f"Status: Download complete! Duration {execution_time:.6f} s, Automatically downloading the ZIP file."
        self.status_pane.object = self.status

        return zip_buffer

# def calculate_bounds(layout):
#     """Hitung batas (west, east, south, north) dari mapbox.center & zoom"""
#     center = layout["mapbox"]["center"]
#     zoom = layout["mapbox"]["zoom"]

#     # Pastikan nilai tersedia
#     if center is None or zoom is None:
#         return None

#     center_lat, center_lon = center["lat"], center["lon"]

#     # Hitung span longitude & latitude berdasarkan zoom
#     lat_span = 360 / (2 ** zoom)
#     lon_span = 360 / (2 ** zoom * np.cos(np.radians(center_lat)))

#     # Hitung batas koordinat
#     bounds = {
#         "west": center_lon - lon_span / 2,
#         "east": center_lon + lon_span / 2,
#         "south": center_lat - lat_span / 2,
#         "north": center_lat + lat_span / 2
#     }
    
#     return bounds

# class EQCatFetcherParam(param.Parameterized):
#     catalog = param.ClassSelector(class_=Catalog, default=None)
#     earthquake_data = param.List(default=[])
#     output_folder = param.String(default=None)
#     status = param.String(default="Status: Waiting to start...")
#     progress = param.Number(default=0)
#     selected_rectangle = param.List(default=None)
#     bot_lat = param.Number(default=-10)
#     top_lat = param.Number(default=6)
#     left_lon = param.Number(default=95)
#     right_lon = param.Number(default=141)

#     def __init__(self, **params):
#         super().__init__(**params)
#         self.create_controls()
#         self.create_map()  # Tambahkan peta interaktif
#         self.create_layout()
    
#     def create_controls(self):
#         # Input fields
#         self.bot_lat_input = pn.widgets.FloatInput(name="Bottom Latitude", value=self.bot_lat)
#         self.top_lat_input = pn.widgets.FloatInput(name="Top Latitude", value=self.top_lat)
#         self.left_lon_input = pn.widgets.FloatInput(name="Left Longitude", value=self.left_lon)
#         self.right_lon_input = pn.widgets.FloatInput(name="Right Longitude", value=self.right_lon)
#         self.start_date = pn.widgets.DatePicker(name="Start Date", value=datetime(2023, 1, 1))
#         self.end_date = pn.widgets.DatePicker(name="End Date", value=datetime(2023, 6, 1))
#         self.min_mag = pn.widgets.FloatInput(name="Min Magnitude", value=0)
#         self.max_mag = pn.widgets.FloatInput(name="Max Magnitude", value=10)
#         self.min_dep = pn.widgets.FloatInput(name="Min Depth", value=0)
#         self.max_dep = pn.widgets.FloatInput(name="Max Depth", value=700)
#         self.step_days = pn.widgets.IntInput(name="Step (days)", value=30)

#         # Buttons
#         self.update_button = pn.widgets.Button(name="Update Map", button_type="primary", width=200)
#         self.update_button.on_click(self.update_from_input)
#         self.select_folder_button = pn.widgets.Button(name="Select Output Folder", button_type="primary")
#         # self.select_folder_button.on_click(self.select_output_folder)
#         self.download_button = pn.widgets.Button(name="Download Catalog", button_type="primary")
#         # self.download_button.on_click(self.start_download_thread)
#         self.load_button = pn.widgets.Button(name="Load Event Data", button_type="primary")
#         # self.load_button.on_click(self.load_quakeml_thread)
#         self.export_button = pn.widgets.Button(name="Export to Wave Fetcher", button_type="primary")
#         # self.export_button.on_click(self.export_quakeml)

#         # Checkboxes
#         self.rec_var = pn.widgets.Checkbox(name="Convert to XML", value=False)
#         self.ef_var = pn.widgets.Checkbox(name="Convert to .events (fast loading)", value=True)

#         # Status and progress
#         self.status_pane = pn.pane.Markdown(self.status, styles={"color": "green"})
#         self.progress_bar = pn.widgets.Progress(value=self.progress, sizing_mode="stretch_width")

#     def test(self, event):
#         print("yes")

#         pass

#     def create_map(self):
#         """Membuat peta interaktif"""
#         self.fig = go.Figure()

#         # Tambahkan OpenStreetMap sebagai basemap
#         self.fig.update_layout(
#             mapbox_style="open-street-map",
#             mapbox_center={"lat": (self.bot_lat + self.top_lat) / 2, "lon": (self.left_lon + self.right_lon) / 2},
#             mapbox_zoom=1,
#             dragmode="drawrect",  # Aktifkan fitur menggambar kotak
#             margin={"r": 0, "t": 0, "l": 0, "b": 0}
#         )

#         # Tambahkan kotak awal
#         self.add_rectangle()

#     def add_rectangle(self):
#         """Menambahkan kotak berdasarkan koordinat"""
#         self.fig.data = []  # Hapus data lama
#         self.fig.add_trace(go.Scattermapbox(
#             mode="lines",
#             lon=[self.left_lon, self.right_lon, self.right_lon, self.left_lon, self.left_lon],
#             lat=[self.bot_lat, self.bot_lat, self.top_lat, self.top_lat, self.bot_lat],
#             fill="none",
#             line=dict(color="red", width=2),
#             name="Selected Area"
#         ))

#     def update_from_input(self, event=None):
#         """Update peta jika input koordinat berubah"""
#         self.bot_lat = self.bot_lat_input.value
#         self.top_lat = self.top_lat_input.value
#         self.left_lon = self.left_lon_input.value
#         self.right_lon = self.right_lon_input.value
#         self.create_map()
#         self.add_rectangle()
#         self.map_pane.object = self.fig

#     def update_from_map(self, event):
#         print(self.fig.layout)
#         """Update input saat pengguna menggambar/memindahkan kotak di peta"""
#         if 'shapes' in event.new and len(event.new['shapes']) > 0:
#             shape = event.new['shapes'][-1]  # Ambil kotak terbaru

#             # Cek apakah shape berbentuk kotak (rect)
#             if shape.get("type") == "rect":
#                 # Ambil skala relatif
#                 x0, x1 = shape["x0"], shape["x1"]
#                 y0, y1 = shape["y0"], shape["y1"]

#                 # Hitung batas manual dari layout jika bounds tidak tersedia
#                 bounds = calculate_bounds(self.fig.layout)

#                 left_lon, right_lon = bounds["west"], bounds["east"]
#                 bot_lat, top_lat = bounds["south"], bounds["north"]

#                 # Konversi koordinat relatif ke longitude dan latitude dalam derajat
#                 lon_min = left_lon + x0 * (right_lon - left_lon)
#                 lon_max = left_lon + x1 * (right_lon - left_lon)
#                 lat_min = bot_lat + (1 - y1) * (top_lat - bot_lat)
#                 lat_max = bot_lat + (1 - y0) * (top_lat - bot_lat)

#                 # Update input fields
#                 self.left_lon_input.value = lon_min
#                 self.right_lon_input.value = lon_max
#                 self.bot_lat_input.value = lat_min
#                 self.top_lat_input.value = lat_max

#                 # Hapus kotak lama sebelum menggambar yang baru
#                 self.update_from_input()

#     def create_layout(self):
#         self.map_pane = pn.pane.Plotly(self.fig, sizing_mode="stretch_width")
#         # Update input otomatis saat kotak dipindahkan/dibuat ulang
#         self.map_pane.param.watch(self.update_from_map, 'relayout_data')

#         """Membuat layout utama Panel dengan input dan peta."""
#         input_controls = pn.Card(pn.Row(
#             pn.Column(
#                 self.bot_lat_input, 
#                 self.top_lat_input, 
#                 self.left_lon_input, 
#                 self.right_lon_input,
#             ),
#             pn.Column(
#                 self.start_date,
#                 self.end_date,
#                 self.min_mag,
#                 self.max_mag,
#             ),
#             pn.Column(
#                 self.min_dep,
#                 self.max_dep,
#                 self.step_days,
#                 self.rec_var,
#                 self.ef_var,
#             ),
#             pn.Column(
#                 self.select_folder_button,
#                 self.download_button,
#                 self.load_button,
#                 self.export_button,
#             ),
#             sizing_mode="stretch_width"
#         ))

#         # Status and progress
#         status_panel = pn.Column(
#             self.status_pane,
#             self.progress_bar,
#             sizing_mode="stretch_width"
#         )

#         # Layout utama Panel
#         self.layout = pn.Column(
#             self.map_pane,
#             pn.Row(self.update_button, sizing_mode="stretch_width"),
#             input_controls,
#             pn.Row(status_panel, sizing_mode="stretch_width"),
#             sizing_mode="stretch_both"
#         )

# def calculate_bounds(layout):
#     """Hitung batas (west, east, south, north) dari mapbox.center & zoom"""
#     center = layout["mapbox"]["center"]
#     zoom = layout["mapbox"]["zoom"]

#     # Pastikan nilai tersedia
#     if center is None or zoom is None:
#         return None

#     center_lat, center_lon = center["lat"], center["lon"]

#     # Hitung span longitude & latitude berdasarkan zoom
#     lat_span = 360 / (2 ** zoom)
#     lon_span = 360 / (2 ** zoom * np.cos(np.radians(center_lat)))

#     # Hitung batas koordinat
#     bounds = {
#         "west": center_lon - lon_span / 2,
#         "east": center_lon + lon_span / 2,
#         "south": center_lat - lat_span / 2,
#         "north": center_lat + lat_span / 2
#     }
    
#     return bounds
