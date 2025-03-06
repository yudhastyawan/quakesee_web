import panel as pn
import param
# from wave_loader import WaveLoader
from quakesee_web.wave_fetcher_web import WaveFetcher
# from station_loader import StationLoader
from quakesee_web.eqcat_fetcher_web import EQCatFetcher
from quakesee_web.about_web import About
from pathlib import Path

# pn.extension('terminal', template='bootstrap', sizing_mode="stretch_width")
pn.extension('terminal', 'plotly', 'tabulator', template='bootstrap', sizing_mode="stretch_width")

class MainApp(param.Parameterized):
    current_view = param.ClassSelector(class_=pn.layout.Panel, constant=True)
    
    def __init__(self, **params):
        super().__init__(**params)
        self.frames = self.create_frames()
        self.sidebar = self.create_sidebar()
        self.main_area = pn.Column(self.frames["Fetcher & Loader"], sizing_mode="stretch_both")
        self.tree_visible = True
    
    def create_frames(self):
        """Membuat semua frame yang diperlukan"""
        return {
            "Fetcher & Loader": WaveFetcher(),
            "Catalog Bulk Fetcher": EQCatFetcher(),
            # "HVSR": UnderConstruction("HVSR"),
            # "SPAC": UnderConstruction("SPAC"),
            # "MASW": UnderConstruction("MASW"),
            "About": About(),
            # Tambahkan frame lainnya sesuai kebutuhan
        }
    
    def create_sidebar(self):
        """Membuat sidebar navigasi"""
        # navigation = pn.Accordion(sizing_mode="stretch_width")
        # navigation = []
        self.accordion = pn.Accordion(sizing_mode="stretch_width")
        
        # Earthquake Category
        earthquake_items = pn.Column(
            pn.widgets.Button(name="Fetcher & Loader", button_type="primary", width=200),
            pn.widgets.Button(name="Catalog Bulk Fetcher", button_type="primary", width=200),
        )
        
        # Surface Wave Category
        # surface_wave_items = pn.Column(
        #     pn.widgets.Button(name="HVSR", button_type="primary", width=200),
        #     pn.widgets.Button(name="SPAC", button_type="primary", width=200),
        #     pn.widgets.Button(name="MASW", button_type="primary", width=200),
        # )
        
        # About
        about_item = pn.Column(
            pn.widgets.Button(name="About", button_type="primary", width=200)
        )

        # Tambahkan kategori ke Accordion sebagai tuple (title, content)
        self.accordion.extend([
            ("Earthquake", earthquake_items),
            # ("Surface Wave", surface_wave_items),
            ("About", about_item)
        ])
        
        # Set semua bagian Accordion terbuka secara default
        self.accordion.active = list(range(len(self.accordion.objects)))  # Buka semua bagian


        # Tambahkan event handler untuk tombol di dalam Accordion
        for content in self.accordion.objects:
            if isinstance(content, pn.Column):
                for item in content:
                    if isinstance(item, pn.widgets.Button):
                        item.on_click(self.navigate_handler)
            elif isinstance(content, pn.widgets.Button):
                content.on_click(self.navigate_handler)
        
        return pn.Column(
            # Menambahkan gambar dengan ukuran tertentu
            pn.pane.Image(Path(__file__).parent/"logo.png", width=220, height=150),
            self.accordion,  # Hanya menampilkan accordion tanpa tombol toggle
            sizing_mode="fixed",
            width=220,
            # styles={"background": "#f0f0f0"}
        )
    
    def navigate_handler(self, event):
        """Menangani navigasi menu"""
        page_name = event.obj.name
        self.main_area.objects = [self.frames.get(page_name, self.frames["About"])]
    
    def toggle_sidebar(self, event):
        """Toggle visibility sidebar"""
        self.sidebar.visible = not self.sidebar.visible
        self.sidebar.width = 300 if self.sidebar.visible else 0
    
    def view(self):
        """Mengembalikan tampilan utama"""
        # self.sidebar.objects[0].on_click(self.toggle_sidebar)
        return pn.Row(
            # self.sidebar,
            self.main_area,
            sizing_mode="stretch_width"
        )

# # Convert existing Tkinter components to Panel
# class WaveFetcher(pn.Column):
#     def __init__(self, **params):
#         super().__init__(**params)
#         self.progress = pn.widgets.Progress(active=False, width=300, visible=False)
#         self.info_label = pn.widgets.StaticText(value="Ready")
#         self.fetch_button = pn.widgets.Button(name="Fetch Data", button_type="primary")
#         self.fetch_button.on_click(self.start_fetch)
        
#         self.extend([
#             pn.pane.Markdown("## Wave Fetcher"),
#             self.progress,
#             self.info_label,
#             self.fetch_button
#         ])
    
#     def start_fetch(self, event):
#         self.progress.active = True
#         self.progress.visible = True
#         self.info_label.value = "Fetching data... Please wait."
#         self.fetch_button.disabled = True

# Lakukan konversi serupa untuk komponen lainnya...

class UnderConstruction(pn.Column):
    def __init__(self, page_name, **params):
        super().__init__(**params)
        self.extend([
            pn.pane.Alert(f"Oops! {page_name} is under construction, please check back later!", 
                        alert_type="warning")
        ])

def main():
    # Hapus template global jika ada
    pn.config.template = None

    # Inisialisasi aplikasi
    app = MainApp()

    MAX_SIZE_MB = 150

    template = pn.template.BootstrapTemplate(
        title="QuakeSee WebApp",
        header_background="#2c3e50",
        sidebar=[app.sidebar],  # Jika ingin menambahkan sidebar
        main=[app.view()],      # Area utama
        sidebar_width=250,      # Lebar sidebar
        header=[pn.Row(pn.pane.Markdown(""))]  # Custom header
    )

    # template.servable()

    # Jalankan aplikasi dengan pengaturan ukuran WebSocket & Buffer
    pn.serve(
        template, 
        # port=5006, 
        websocket_max_message_size=MAX_SIZE_MB*1024*1024,  # WebSocket buffer
        http_server_kwargs={'max_buffer_size': MAX_SIZE_MB*1024*1024}  # Tornado buffer
    )

if __name__ == "__main__":
    main()