import panel as pn
import param
import pandas as pd
import numpy as np
import plotly.express as px
from obspy import UTCDateTime
from obspy.clients.fdsn import Client
from obspy.clients.fdsn.header import FDSNNoServiceException
import datetime
from obspy.clients.fdsn import RoutingClient
import plotly.graph_objects as go
import io
from plotly.subplots import make_subplots
from obspy import read as obread
import matplotlib.dates as mdates
import zipfile
from obspy.core.inventory import read_inventory
from obspy.core.inventory import Inventory, Network, Station
import time

class WaveFetcher(pn.Column):
    def __init__(self, **params):
        super().__init__(**params)
        self.wave_fetcher = WaveFetcherParam()
        self._update_layout()
    
    def _update_layout(self):
        self.extend(self.wave_fetcher.layout)

class WaveFetcherParam(param.Parameterized):
    earthquake_data = param.List(default=[])
    selected_quake = param.Dict(default={})
    station_data = param.List(default=[])

    def __init__(self, **params):
        super().__init__(**params)

        self.waveform_data = None
        self.inventory = None

        # UI Components
        self.create_util_widgets()
        self.create_menubar()
        self.create_controls()
        self.create_station_controls()
        self.create_map()
        self.create_details_panel()
        self.create_table()
        self.create_station_table()
        self.create_tm_plot()
        self.create_seismogram_plot()
        self._update_layout()

    def create_util_widgets(self):
        self.status = pn.pane.Markdown("", width=500)

        self.tm_button = pn.widgets.Button(
            name='Time-Magnitude Plot',
            button_type='success',
            width=200
            )

        self.seis_plot_button = pn.widgets.Button(
            name='Plot Seismograms', 
            button_type='success',
            width=200
        )

        self.seis_plot_button.on_click(self.show_seismogram)
        self.tm_button.on_click(self.show_tm_plot)

    def _update_layout(self):
        self.layout = pn.Column(
            pn.Card(pn.pane.Markdown("1. File Options\n2. Map\n3. Status\n4. Settings and Running Programs\n5. Data and Figures"), title="Table of Contents"),
            pn.pane.Markdown("## File Options"),
            self.mbar,
            pn.pane.Markdown("## Map"),
            self.map_pane,
            pn.pane.Markdown("## Status"),
            self.details_pane,
            pn.pane.Markdown("## Settings and Running Programs"),
            pn.Tabs(
                ("Earthquake Parameters", self.control_panel),
                ("Station + Seismogram Parameters", self.station_control_panel),
            ),
            pn.pane.Markdown("## Data and Figures"),
            pn.Tabs(
                ("Earthquake Data", self.table_pane),
                ("Station Data", self.station_table_pane),
                ("Time Series", pn.Column(
                    self.tm_button,
                    self.tm_pane
                    )),
                ("Seismograms", pn.Column(
                    self.seis_plot_button,
                    self.seis_pane
                    )),
            ),
            sizing_mode='stretch_width'
        )
        return self.layout

    def create_menubar(self):
        # Fungsi untuk konversi DataFrame ke CSV dalam bentuk BytesIO
        def df_to_csv(df):
            io_buffer = io.BytesIO()
            df.to_csv(io_buffer, index=False)
            io_buffer.seek(0)
            return io_buffer
        
        def seis_to_file(seis):
            io_buffer = io.BytesIO()
            seis.write(io_buffer, format="MSEED")
            io_buffer.seek(0)
            return io_buffer
        
        def st_to_file(st, fmt):
            io_buffer = io.BytesIO()
            st.write(io_buffer, format=fmt)
            io_buffer.seek(0)
            return io_buffer
        
        def save_seisan_hyp(inv):
            io_buffer = io.BytesIO()
            stat_lis = []

            for netObj in inv:
                for stObj in netObj:
                    for chObj in stObj:
                        sta = stObj._code
                        if sta not in stat_lis:
                            stat_lis.append(sta)
                            if len(sta) > 5: continue
                            str_sta = f"  {sta:4}" if (len(sta) <= 4) else f" {sta:5}"
                            lat = chObj._latitude
                            slat = "N" if (np.sign(lat) >= 0) else "S"
                            lat = np.abs(lat)
                            dlat = int(lat)
                            mlat = 60 * (lat - dlat)
                            lon = chObj._longitude
                            slon = "E" if (np.sign(lon) >= 0) else "W"
                            lon = np.abs(lon)
                            dlon = int(lon)
                            mlon = 60 * (lon - dlon)
                            elev = chObj._elevation
                            elev = int(elev)
                            s_hyp = f"{str_sta}{dlat:2d}{mlat:5.2f}{slat:1}{dlon:3d}{mlon:5.2f}{slon:1}{elev:4d}\n"
                            io_buffer.write(s_hyp.encode())
            io_buffer.seek(0)
            return io_buffer
        
        def save_seisan_hyp2(station_data):
            io_buffer = io.BytesIO()
            stat_lis = []

            for entry in station_data:
                sta = entry['station']
                if sta not in stat_lis:
                    stat_lis.append(sta)
                    if len(sta) > 5:
                        continue

                    str_sta = f"  {sta:4}" if (len(sta) <= 4) else f" {sta:5}"
                    lat = entry['latitude']
                    slat = "N" if (np.sign(lat) >= 0) else "S"
                    lat = np.abs(lat)
                    dlat = int(lat)
                    mlat = 60 * (lat - dlat)

                    lon = entry['longitude']
                    slon = "E" if (np.sign(lon) >= 0) else "W"
                    lon = np.abs(lon)
                    dlon = int(lon)
                    mlon = 60 * (lon - dlon)

                    elev = int(entry['elevation'])

                    # Format SEISAN .hyp
                    s_hyp = f"{str_sta}{dlat:2d}{mlat:5.2f}{slat:1}{dlon:3d}{mlon:5.2f}{slon:1}{elev:4d}\n"
                    io_buffer.write(s_hyp.encode())

            io_buffer.seek(0)  # Reset ke awal
            return io_buffer
        
        # Fungsi untuk menyimpan data ke file SAC dan mengemasnya dalam ZIP
        def create_sac_zip(seis):
            zip_buffer = io.BytesIO()
            
            with zipfile.ZipFile(zip_buffer, "w", zipfile.ZIP_DEFLATED) as zipf:
                for i, tr in enumerate(seis):
                    sac_buffer = io.BytesIO()
                    tr.write(sac_buffer, format="SAC")  # Simpan tiap trace ke buffer
                    sac_buffer.seek(0)
                    
                    # Nama file berdasarkan network, station, channel, timestamp
                    filename = f"{tr.stats.network}_{tr.stats.station}_{tr.stats.channel}_{tr.stats.starttime.strftime('%Y%m%d_%H%M%S')}.sac"
                    zipf.writestr(filename, sac_buffer.getvalue())  # Tambahkan ke ZIP

            zip_buffer.seek(0)
            return zip_buffer

        # Tombol download data event
        self.download_event_button = pn.widgets.FileDownload(
            callback=lambda: df_to_csv(pd.DataFrame(self.earthquake_data)),
            filename="event_data.csv",
            button_type="primary",
            label="Download Event Data",
            width=200,
        )

        # Tombol download data event
        self.download_station_button = pn.widgets.FileDownload(
            callback=lambda: df_to_csv(pd.DataFrame(self.station_data)),
            filename="station_data.csv",
            button_type="primary",
            label="Download Station Data (.csv)",
            width=200,
        )

        self.download_station_seisan_button = pn.widgets.FileDownload(
            callback=lambda: save_seisan_hyp2(self.station_data),
            filename="station_data.hyp",
            button_type="primary",
            label="Download Station Data (.hyp)",
            width=200,
        )

        # Tombol download data event
        self.download_station_xml_button = pn.widgets.FileDownload(
            callback=lambda: st_to_file(self.inventory, "STATIONXML"),
            filename="station_data.xml",
            button_type="primary",
            label="Download Station Data (.xml)",
            width=200,
        )

        self.download_station_txt_button = pn.widgets.FileDownload(
            callback=lambda: st_to_file(self.inventory, "STATIONTXT"),
            filename="station_data.txt",
            button_type="primary",
            label="Download Station Data (.txt)",
            width=200,
        )

        self.download_station_pz_button = pn.widgets.FileDownload(
            callback=lambda: st_to_file(self.inventory, "SACPZ"),
            filename="station_data.pz",
            button_type="primary",
            label="Download Station Data (.pz)",
            width=200,
        )

        self.download_station_kml_button = pn.widgets.FileDownload(
            callback=lambda: st_to_file(self.inventory, "KML"),
            filename="station_data.kml",
            button_type="primary",
            label="Download Station Data (.kml)",
            width=200,
        )

        # Tombol download data event
        self.download_seis_button = pn.widgets.FileDownload(
            callback=lambda: seis_to_file(self.waveform_data),
            filename="waveforms.mseed",
            button_type="primary",
            label="Download Waveform Data (.mseed)",
            width=300,
        )

        # Widget Panel untuk download file
        self.download_seis_sac_button = pn.widgets.FileDownload(
            callback=lambda: create_sac_zip(self.waveform_data),
            filename="waveforms.zip",
            button_type="primary",
            label="Download SAC Data (.zip)",
            width=300,
        )

        self.upload_event = pn.widgets.FileInput(accept=".csv,.events")
        self.upload_station = pn.widgets.FileInput(accept=".csv")
        self.upload_station_xml = pn.widgets.FileInput(accept=".xml")
        self.upload_mseed = pn.widgets.FileInput(accept=".mseed")

        # Fungsi untuk menangani file yang diunggah
        def upload_event_callback(event):
            if self.upload_event.value:
                file = io.BytesIO(self.upload_event.value)
                self.event_data = pd.read_csv(file)
                self.earthquake_data = self.event_data.to_dict(orient="records")

        def convert_to_inventory(station_data):
            networks = {}

            for entry in station_data:
                net_code = entry['network']
                sta_code = entry['station']
                lat = entry['latitude']
                lon = entry['longitude']
                elev = entry['elevation']

                # Buat objek Station
                station = Station(
                    code=sta_code,
                    latitude=lat,
                    longitude=lon,
                    elevation=elev
                )

                # Tambahkan ke Network yang sesuai
                if net_code not in networks:
                    networks[net_code] = Network(code=net_code, stations=[])
                
                networks[net_code].stations.append(station)

            # Buat objek Inventory
            inventory = Inventory(networks=list(networks.values()), source="Converted from station_data")
            
            return inventory

        # Fungsi untuk menangani file yang diunggah
        def upload_station_callback(event):
            if self.upload_station.value:
                file = io.BytesIO(self.upload_station.value)
                self.st_data = pd.read_csv(file)
                self.station_data = self.st_data.to_dict(orient="records")
                self.inventory = convert_to_inventory(self.station_data)

        # Fungsi untuk menangani file yang diunggah
        def upload_station_xml_callback(event):
            if self.upload_station_xml.value:
                file = io.BytesIO(self.upload_station_xml.value)
                self.inventory = read_inventory(file)
                st_data = []
                for net in self.inventory:
                    for sta in net:
                        st_data.append({
                            'network': net.code,
                            'station': sta.code,
                            'latitude': sta.latitude,
                            'longitude': sta.longitude,
                            'elevation': sta.elevation
                        })
                self.station_data = st_data

        def upload_mseed_callback(event):
            if self.upload_mseed.value:
                file = io.BytesIO(self.upload_mseed.value)
                self.waveform_data = obread(file)

        # Pasang event handler
        self.upload_event.param.watch(upload_event_callback, 'value')
        self.upload_station.param.watch(upload_station_callback, 'value')
        self.upload_station_xml.param.watch(upload_station_xml_callback, 'value')
        self.upload_mseed.param.watch(upload_mseed_callback, 'value')

        self.mbar = pn.Tabs(
            ("Open...", pn.Card(
                pn.Row(
                    pn.Column(
                        "Event (.csv, .events)",
                        self.upload_event,
                        "Station (.xml)",
                        self.upload_station_xml,
                    ),
                    pn.Column(
                        "Station (.csv) (LIMITED FEATURES)",
                        self.upload_station,
                        "Waveforms (.mseed)",
                        self.upload_mseed,
                    ),
                ),
            )),
            ("Save...", pn.Card(pn.Row(
                pn.Column(
                    self.download_event_button,
                    pn.Spacer(),
                ),
                pn.Column(
                    self.download_station_button,
                    self.download_station_seisan_button,
                ),
                pn.Column(
                    self.download_station_xml_button,
                    self.download_station_txt_button,
                ),
                pn.Column(
                    self.download_station_pz_button,
                    self.download_station_kml_button,
                ),
                pn.Column(
                    self.download_seis_button,
                    self.download_seis_sac_button,
                ),
                pn.Spacer(),
            )))
        )
        pass
    
    def create_controls(self):
        # Date Inputs
        self.start_date = pn.widgets.DatePicker(
            name='Start Date', 
            value=datetime.date(2024, 1, 1)
        )
        self.end_date = pn.widgets.DatePicker(
            name='End Date', 
            value=datetime.date(2024, 6, 1)
        )
        
        # Magnitude Input
        self.min_mag = pn.widgets.FloatInput(
            name='Minimum Magnitude', 
            value=5.0, 
            step=0.1)
        
        # Limit Controls
        self.limit_check = pn.widgets.Checkbox(
            name="Don't Use Limit", 
            value=True)
        
        self.limit_input = pn.widgets.IntInput(
            name='Max Events', 
            value=100, 
            disabled=True)
        
        # Buttons
        self.fetch_button = pn.widgets.Button(
            name='Fetch Earthquake Data', 
            button_type='primary',
            width=200
            )
        
        # Progress
        self.progress = pn.indicators.Progress(
            active=False, 
            width=300)
        
        # Event Handlers
        self.limit_check.link(self.limit_input, value='disabled')
        self.fetch_button.on_click(self.fetch_earthquake_data)
        
        # Control Panel Layout
        self.control_panel = pn.Card(
            pn.Column(
                self.start_date,
                self.end_date,
                self.min_mag,
                self.limit_check,
                self.limit_input,
                pn.Row(
                        self.fetch_button,
                        pn.layout.Spacer(),
                        self.progress,
                    ),
                self.status,
                # sizing_mode='stretch_height'
            ),
            title='Search Parameters',
            styles={'background': '#f0f0f0'}
        )

        self.control_panel.collapsed = False

    def create_station_controls(self):
        """Membuat kontrol untuk pencarian stasiun"""
        self.min_radius = pn.widgets.FloatInput(
            name='Min Radius (degrees)', 
            value=0.0, 
            step=0.1
        )
        self.max_radius = pn.widgets.FloatInput(
            name='Max Radius (degrees)', 
            value=5.0, 
            step=0.1
        )
        self.start_offset = pn.widgets.IntInput(
            name='Start Before Event (s)', 
            value=-300
        )
        self.end_offset = pn.widgets.IntInput(
            name='End After Event (s)', 
            value=3600
        )
        self.channel = pn.widgets.TextInput(
            name='Channel', 
            value="BH?,EH?,HH?"
        )

        self.wave_limit = pn.widgets.IntInput(
            name='Total of Stations recorded', 
            value=-1
        )

        self.rest_check = pn.widgets.Checkbox(
            name="Reset stations", 
            value=True)

        # Seismogram
        self.seis_check = pn.widgets.Checkbox(
            name="+ Seismograms", 
            value=False)
        
        self.merge_check = pn.widgets.Checkbox(
            name="+ Merge the same traces", 
            value=True)
        
        self.statfilt_check = pn.widgets.Checkbox(
            name="+ Filter the stations", 
            value=True)
        
        self.search_button = pn.widgets.Button(
            name='Search!', 
            button_type='primary',
            width=200
        )

        self.search_button.disabled = True

        self.search_button.on_click(self.search_stations)
        
        self.station_control_panel = pn.Card(
            pn.Column(
                self.min_radius,
                self.max_radius,
                self.start_offset,
                self.end_offset,
                self.channel,
                self.wave_limit,
                pn.pane.Markdown("**Description:**\n1. **-1** : all - parallel version.\n2. **0** : all - serial version.\n3. **\>0** : limit wave number - serial version.", width=500),
                self.rest_check,
                self.seis_check,
                self.merge_check,
                self.statfilt_check,
                pn.Row(
                        self.search_button,
                        pn.layout.Spacer(),
                        self.progress,
                    ),
                self.status,
                sizing_mode='stretch_width'
            ),
            title='Station + Seismogram Search Parameters',
            styles={'background': '#f0f0f0'}
        )

        self.station_control_panel.collapsed = False

    def create_map(self):
        self.map_fig = px.scatter_geo(projection='natural earth')
        self.map_fig.update_geos(showcountries=True)
        self.map_pane = pn.pane.Plotly(
            self.map_fig, 
            height=600,
            # sizing_mode='stretch_both'
            )
        
        # Tambahkan event handler saat titik di peta diklik
        self.map_pane.param.watch(self.on_map_click, 'click_data')
        
    def create_details_panel(self):
        self.details = pn.pane.Markdown("", width=300)
        self.stat_counts = pn.pane.Markdown("", width=300)

        def refresh_counts(event):
            txt = "**Total:**\n"
            txt += f"{len(self.earthquake_data)} events, {len(self.station_data)} stations, {len(self.waveform_data) if self.waveform_data else 0} waveforms."
            self.stat_counts.object = txt

        refresh_counts(0)

        refresh_button = pn.widgets.Button(
            name='refresh number!', 
            button_type='success',
            width=200
        )
        refresh_button.on_click(refresh_counts)

        self.details_pane = pn.Card(
            pn.Row(self.details),
            pn.Row(self.stat_counts),
            refresh_button,
            title='Event Details',
            styles={'background': '#f0f0f0'}
        )

    def create_table(self):
        self.table = pn.widgets.Tabulator(
            page_size=10,
            pagination='local',  # Pagination di client
            sizing_mode='stretch_width',
        )

        self.table.disabled = True

        # Tambahkan event handler saat baris dipilih
        self.table.param.watch(self.on_table_select, 'selection')

        self.table_pane = pn.Card(
            self.table,
            title='Earthquake Data',
            styles={'background': '#f0f0f0'}
        )

    def create_station_table(self):
        """Membuat tabel untuk menampilkan data stasiun"""
        self.station_table = pn.widgets.Tabulator(
            pagination='local',
            page_size=10,
            sizing_mode='stretch_width'
        )
        self.station_table_pane = pn.Card(
            self.station_table,
            title='Station Data',
            styles={'background': '#f0f0f0'}
        )

    def create_tm_plot(self):
        self.tm_pane = pn.Card(
            pn.pane.Plotly(),
            title='Magnitude vs Time',
            styles={'background': '#f0f0f0'}
        )
        self.tm_pane.visible = False

    def create_seismogram_plot(self):
        self.seis_prev_button = pn.widgets.Button(name="Previous", button_type="primary", width=200)
        self.seis_next_button = pn.widgets.Button(name="Next", button_type="primary", width=200)
        
        self.seis_pane = pn.Card(
            pn.pane.Plotly(),
            pn.Row(
                pn.layout.Spacer(), 
                self.seis_prev_button, 
                self.seis_next_button
                ),
            title='Seismograms',
            styles={'background': '#f0f0f0'}
        )
        self.seis_pane.visible = False
    
    @param.depends('earthquake_data', watch=True)
    def update_map(self):
        if len(self.earthquake_data) > 0:
            df = pd.DataFrame(self.earthquake_data)
            self.map_fig = px.scatter_geo(
                df,
                lat='latitude',
                lon='longitude',
                size='magnitude',
                hover_name='time',
                color='depth',
                projection='natural earth'
            )
            self.details.object = f"total earthquake: {len(self.earthquake_data)}"
        else:
            self.map_fig = px.scatter_geo(projection='natural earth')
        
        self.map_fig.update_geos(showcountries=True)

        if self.station_data:
            station_df = pd.DataFrame(self.station_data)
            # Buat trace untuk stasiun dengan simbol segitiga
            station_trace = go.Scattergeo(
                lon=station_df['longitude'],
                lat=station_df['latitude'],
                mode='markers',
                marker=dict(
                    symbol='triangle-up',  # Simbol segitiga
                    size=10,  # Ukuran simbol
                    color='black',  # Warna simbol
                    line=dict(width=1, color='black')  # Garis tepi simbol
                ),
                text=station_df['network'] + ' - ' + station_df['station'],  # Teks hover
                hoverinfo='text',  # Tampilkan teks saat hover
                name='Stations'  # Nama legenda
            )
        
            # Tambahkan trace stasiun ke peta
            self.map_fig.add_trace(station_trace)

        self.map_pane.object = self.map_fig

    @param.depends('station_data', watch=True)
    def update_station_map(self):
        """Memperbarui peta dengan data gempa dan stasiun"""
        self.update_map()
        
    @param.depends('earthquake_data', watch=True)
    def update_table(self):
        if len(self.earthquake_data) > 0:
            df = pd.DataFrame(self.earthquake_data)
            self.table.value = df

    @param.depends('station_data', watch=True)
    def update_station_table(self):
        if len(self.station_data) > 0:
            df = pd.DataFrame(self.station_data)
            self.station_table.value = df

    @param.depends('selected_quake', watch=True)
    def update_details(self):
        """
        Memperbarui panel detail saat selected_quake berubah.
        """
        if self.selected_quake:
            text = f"""
            **Event Details**  
            Time: {self.selected_quake.get('time', '')}  
            Latitude: {self.selected_quake.get('latitude', '')}  
            Longitude: {self.selected_quake.get('longitude', '')}  
            Depth: {self.selected_quake.get('depth', '')} km  
            Magnitude: {self.selected_quake.get('magnitude', '')}
            """
            self.details.object = text
        else:
            self.details.object = "No earthquake selected."

    def update_selected_quake(self, index):
        """
        Memperbarui selected_quake berdasarkan indeks gempa yang dipilih.
        """
        if self.earthquake_data and 0 <= index < len(self.earthquake_data):
            self.selected_quake = self.earthquake_data[index]

    def on_table_select(self, event):
        """
        Handler saat baris di tabel dipilih.
        """
        if event.new:
            selected_index = event.new[0]  # Ambil indeks baris yang dipilih
            self.update_selected_quake(selected_index)
            self.search_button.disabled = False
    
    def on_map_click(self, event):
        """
        Handler saat titik di peta diklik.
        """
        if event.new:
            clicked_point = event.new['points'][0]
            latitude = clicked_point['lat']
            longitude = clicked_point['lon']
            
            # Cari gempa yang sesuai dengan koordinat yang diklik
            for index, quake in enumerate(self.earthquake_data):
                if quake['latitude'] == latitude and quake['longitude'] == longitude:
                    self.update_selected_quake(index)
                    self.search_button.disabled = False
                    break
    
    def fetch_earthquake_data(self, event):
        try:
            beginning = time.time()
            self.progress.active = True
            client = Client("IRIS")
            
            start = UTCDateTime(self.start_date.value)
            end = UTCDateTime(self.end_date.value)
            min_mag = self.min_mag.value
            limit = self.limit_input.value if not self.limit_check.value else None
            
            catalog = client.get_events(
                starttime=start,
                endtime=end,
                minmagnitude=min_mag,
                limit=limit
            )
            
            self.earthquake_data = [{
                "time": str(ev.origins[0].time),
                "latitude": ev.origins[0].latitude,
                "longitude": ev.origins[0].longitude,
                "depth": ev.origins[0].depth/1000,
                "magnitude": ev.magnitudes[0].mag,
                "magnitude_type": ev.magnitudes[0].magnitude_type
            } for ev in catalog]
            
        except FDSNNoServiceException:
            pn.state.notifications.error("Service Error: Unable to connect to FDSN service")
        except Exception as e:
            pn.state.notifications.error(f"Error fetching data: {str(e)}")
        finally:
            self.progress.active = False
            execution_time = time.time() - beginning
            txt = f"Finished! Duration {execution_time:.6f} s."
            self.status.object = txt

    def search_stations(self, event):
        """Mencari stasiun berdasarkan parameter yang dimasukkan"""
        # try:
        self.progress.active = True
        beginning = time.time()

        if not self.selected_quake:
            self.status.object = "Please select an earthquake first!"
            return
        
        # Dapatkan parameter dari kontrol
        client = RoutingClient("iris-federator")
        starttime = UTCDateTime(self.selected_quake['time']) + self.start_offset.value
        endtime = UTCDateTime(self.selected_quake['time']) + self.end_offset.value

        self.progress.active = True

        def seek_st():
            self.status.object = "search available stations . . ."
            
            # Lakukan pencarian stasiun
            return client.get_stations(
                network="*",
                station="*",
                channel=self.channel.value,
                starttime=starttime,
                endtime=endtime,
                latitude=self.selected_quake['latitude'],
                longitude=self.selected_quake['longitude'],
                minradius=self.min_radius.value,
                maxradius=self.max_radius.value,
                level="response"
            )
        
        if self.inventory is None:
            inventory = seek_st()
        else:
            if self.rest_check.value:
                inventory = seek_st()
            else:
                inventory = self.inventory

        if self.seis_check.value:
            self.waveform_data = None

            self.status.object = "search available waveforms . . ."

            if self.wave_limit.value == -1:
                net_code = ",".join(list(set([network.code for network in inventory])))
                stat_code = ",".join(list(set([station.code for network in inventory for station in network])))
                self.waveform_data = client.get_waveforms(
                                network=net_code, station=stat_code, location="*",
                                channel=self.channel.value, starttime=starttime, endtime=endtime
                            )

                strcode = []
                for network in inventory:
                    for station in network:
                        strcode.append(f"{network.code}.{station.code}")
                strcode = list(set(strcode))

                for tr in self.waveform_data:
                    if f"{tr.stats.network}.{tr.stats.station}" not in strcode:
                        self.waveform_data.remove(tr)

            else:
                tot = len([s for network in inventory for s in network])
                nn = 0
                ii = 0
                for network in inventory:
                    for station in network:
                        ii += 1
                        try:
                            # Download waveform
                            st = client.get_waveforms(
                                network=network.code, station=station.code, location="*",
                                channel=self.channel.value, starttime=starttime, endtime=endtime
                            )
                            if len(st) > 0:
                                if nn == 0:
                                    self.waveform_data = st
                                else:
                                    self.waveform_data += st

                                nn += 1
                                if self.wave_limit.value > 0:
                                    self.status.object = f"{nn}. {network.code}.{station.code}\ndownloaded ({int(100*nn/self.wave_limit.value)}%)"
                                else:
                                    self.status.object = f"{nn}. {network.code}.{station.code}\ndownloaded ({int(100*ii/tot)}%)"
                        except:
                            pass
                    
                        if self.wave_limit.value > 0:
                            if nn >= self.wave_limit.value: break
                    
                    if self.wave_limit.value > 0:
                        if nn >= self.wave_limit.value: break
        
            if self.merge_check.value:
                self.waveform_data.merge(method=1, interpolation_samples=-1, fill_value='interpolate')

            if self.statfilt_check.value:
                self.status.object = "select stations based on the waveforms . . ."

                net_code = list(set(tr.stats.network for tr in self.waveform_data))
                stat_code = list(set(tr.stats.station for tr in self.waveform_data))

                net_code = list(set(network.code for network in inventory if network.code not in net_code))
                for ncode in net_code:
                    inventory = inventory.remove(network=ncode)

                stat_code = list(set(station.code for network in inventory for station in network if station.code not in stat_code))
                for scode in stat_code:
                    inventory = inventory.remove(station=scode)
        
        def update_st():
            st_data = []
            for net in inventory:
                for sta in net:
                    st_data.append({
                        'network': net.code,
                        'station': sta.code,
                        'latitude': sta.latitude,
                        'longitude': sta.longitude,
                        'elevation': sta.elevation
                    })
            self.station_data = st_data
            self.inventory = inventory
        
        # Format data stasiun
        if self.inventory is None:
            update_st()
        else:
            if self.rest_check.value:
                update_st()
        
        # Update UI
        # if self.station_data:
        #     self.station_table.value = pd.DataFrame(self.station_data)
        #     self.update_station_map()
            # pn.state.notifications.success(f"Found {len(self.station_data)} stations!")
            
        # except Exception as e:
        #     msg = e
        #     pn.state.notifications.error(f"Station search failed: {str(msg)}")

        self.progress.active = False
        execution_time = time.time() - beginning
        txt = f"search finished! {len(self.station_data)} stations"
        if self.seis_check.value: txt += f" and {len(self.waveform_data)} waveforms"
        txt += f" downloaded. Duration {execution_time:.6f} s."
        self.status.object = txt
    
    def show_tm_plot(self, event):
        if len(self.earthquake_data) > 0:
            df = pd.DataFrame(self.earthquake_data)
            df['time'] = pd.to_datetime(df['time'])
            fig = px.scatter(
                df,
                x='time',
                y='magnitude',
                labels={'magnitude': 'Magnitude', 'time': 'Time'}
            )
            self.tm_pane[0].object = fig
            self.tm_pane.visible = True

    def show_seismogram(self, event):
        if self.waveform_data is not None:
            st = self.waveform_data

            # 2. Dapatkan daftar stasiun unik
            stations = sorted(set(tr.stats.station for tr in st))
            self.station_index = 0  # Mulai dari stasiun pertama

            # 3. **Optimasi: Simpan hasil filtering di dictionary**
            station_dict = {station: [tr for tr in st if tr.stats.station == station] for station in stations}

            def plot_seismogram(station):
                filtered_st = station_dict.get(station, [])  # Ambil dari dictionary
                
                if not filtered_st:
                    return go.Figure(layout={"title": f"Tidak ada data untuk stasiun {station}"})

                fig = make_subplots(rows=len(filtered_st), cols=1, shared_xaxes=True, vertical_spacing=0.05)

                for i, tr in enumerate(filtered_st):
                    time = mdates.num2date(tr.times("matplotlib"))  # Konversi waktu ke datetime
                    data = tr.data  # Amplitudo
                    
                    fig.add_trace(
                        go.Scatter(x=time, y=data, mode="lines", name=f"{tr.stats.network}.{tr.stats.station}.{tr.stats.channel}"),
                        row=i+1, col=1
                    )

                fig.update_layout(
                    title=f"Seismogram untuk Stasiun {station}",
                    height=300 * len(filtered_st),
                    xaxis_title="Time",
                    yaxis_title="Amplitude"
                )

                for i in range(1, len(filtered_st) + 1):
                    fig.update_xaxes(row=i, col=1, tickformat="%H:%M:%S")
                    fig.update_yaxes(row=i, col=1, tickformat=".2e")

                return fig
            
            self.seis_pane[0].object = plot_seismogram(stations[self.station_index])
            
            # 5. Fungsi untuk tombol navigasi
            def previous_station(event):
                self.station_index = (self.station_index - 1) % len(stations)
                self.seis_pane[0].object = plot_seismogram(stations[self.station_index])

            def next_station(event):
                self.station_index = (self.station_index + 1) % len(stations)
                self.seis_pane[0].object = plot_seismogram(stations[self.station_index])

            # 6. Tombol navigasi
            self.seis_prev_button.on_click(previous_station)
            self.seis_next_button.on_click(next_station)

            self.seis_pane.visible = True

            # st = self.waveform_data[0:5]
            # fig = make_subplots(
            #     rows=len(st), cols=1, 
            #     shared_xaxes=True,  # Semua subplot pakai sumbu x yang sama
            #     vertical_spacing=0.05  # Spasi antar subplot
            # )

            # for i, tr in enumerate(st):
            #     # time = tr.times("matplotlib")  # Waktu dalam format matplotlib
            #     time = mdates.num2date(tr.times("matplotlib"))
            #     data = tr.data  # Amplitudo
                
            #     # 4. Tambahkan Trace ke subplot yang sesuai
            #     fig.add_trace(
            #         go.Scatter(
            #             x=time, y=data,
            #             mode="lines",
            #             name=f"{tr.stats.network}.{tr.stats.station}.{tr.stats.channel}"
            #         ),
            #         row=i+1, col=1  # Sesuai nomor subplot
            #     )

            # fig.update_layout(
            #     title="Seismogram Plot (Setiap Trace di Subplot Berbeda)",
            #     height=300 * len(st),  # Sesuaikan tinggi berdasarkan jumlah trace
            #     xaxis_title="Time",
            #     yaxis_title="Amplitude"
            # )

            # for i in range(1, len(st) + 1):
            #     fig.update_xaxes(
            #         row=i, col=1,
            #         tickformat="%H:%M:%S",  # Format waktu: Jam:Menit:Detik
            #     )
            #     fig.update_yaxes(
            #         row=i, col=1,
            #         tickformat=".2e"  # Format notasi saintifik
            #     )

            # self.seis_pane[0].object = fig
            # self.seis_pane.visible = True