import os
from pathlib import Path

from create_dp import create_etl_pipeline
from data_pipeline.etl_pipeline import run_etl_on_folder
from data_pipeline.extract import read_from_aisr_csv
from data_pipeline.load import write_to_infinite_campus_csv
from data_pipeline.manifest_generator import log_etl_run
from data_pipeline.transform import transform_data_from_aisr_to_infinite_campus
from kivy.app import App
from kivy.graphics import Color, RoundedRectangle
from kivy.lang import Builder
from kivy.uix.boxlayout import BoxLayout
from kivy.uix.button import Button
from kivy.uix.filechooser import FileChooserIconView
from kivy.uix.label import Label
from kivy.uix.popup import Popup
from kivy.uix.textinput import TextInput

KV = """
BoxLayout:
    orientation: 'vertical'
    padding: [30, 30, 30, 30]
    spacing: 20
    size_hint: None, None
    width: 1200  # Fixed width for the container
    height: self.minimum_height  # Automatically adjusted height
    pos_hint: {"center_x": 0.5, "center_y": 0.5}

    Label:
        text: "ISD 197 Immunization Records Pipeline"
        font_size: '24sp'
        size_hint_y: None
        height: '40dp'
        halign: "center"
        bold: True
        color: 0.95, 0.95, 0.95, 1 # White text

    # Main content BoxLayout for form
    BoxLayout:
        orientation: 'vertical'
        spacing: 10
        size_hint_y: None
        height: self.minimum_height
        width: self.parent.width

        # Input Folder Box
        BoxLayout:
            orientation: 'horizontal'
            size_hint_y: None
            height: '50dp'
            spacing: 10

            TextInput:
                id: input_folder
                hint_text: "Input Folder"
                readonly: True
                size_hint_x: 0.7
                multiline: False
                padding: [10, 10]
                background_color: 1, 1, 1, 1  # Soft white background
                foreground_color: 0, 0, 0, 1  # Black text for contrast

            Button:
                text: "Select Input Folder"
                on_press: app.select_folder("input")
                size_hint_x: .3
                background_color: 0.2, 0.4, 0.8, 1  # Lighter blue background
                color: 0.95, 0.95, 0.95, 1  # White text

        # Output Folder Box
        BoxLayout:
            orientation: 'horizontal'
            size_hint_y: None
            height: '50dp'
            spacing: 10

            TextInput:
                id: output_folder
                hint_text: "Output Folder"
                readonly: True
                size_hint_x: 0.7
                multiline: False
                padding: [10, 10]
                background_color: 1, 1, 1, 1  # Soft white background
                foreground_color: 0, 0, 0, 1  # Black text for contrast

            Button:
                text: "Select Output Folder"
                on_press: app.select_folder("output")
                size_hint_x: .3
                background_color: 0.2, 0.4, 0.8, 1  # Lighter blue background
                color: 0.95, 0.95, 0.95, 1 # White text

        # Manifest Folder Box
        BoxLayout:
            orientation: 'horizontal'
            size_hint_y: None
            height: '50dp'
            spacing: 10

            TextInput:
                id: manifest_folder
                hint_text: "Manifest Folder"
                readonly: True
                size_hint_x: 0.7
                multiline: False
                padding: [10, 10]
                background_color: 1, 1, 1, 1  # Soft white background
                foreground_color: 0, 0, 0, 1  # Black text for contrast

            Button:
                text: "Select Manifest Folder"
                on_press: app.select_folder("manifest")
                size_hint_x: 0.3
                background_color: 0.2, 0.4, 0.8, 1  # Lighter blue background
                color: 0.95, 0.95, 0.95, 1 # White text

        Button:
            text: "Run Pipeline"
            on_press: app.run_pipeline()
            size_hint_y: None
            height: '50dp'
            background_color: 0.1, 0.3, 0.7, 1  # Darker blue background
            color: 0.95, 0.95, 0.95, 1 # White text

        Label:
            id: status_label
            text: ""
            size_hint_y: None
            height: '40dp'
            size_hint_x: 1  # Allow the label to adjust its width based on the parent
            text_size: self.width, None  # Wrap text to the width of the label
            halign: "center"
            valign: "middle"  # To vertically center the text
            bold: True
            color: 0.95, 0.95, 0.95, 1  # Softer white text
"""


class PipelineApp(App):
    def build(self):
        self.dialog = None
        root = Builder.load_string(KV)
        root.minimum_width = 600  # Minimum width for the window
        root.minimum_height = 500  # Minimum height for the window
        return root

    def on_start(self):
        """
        Set the default folder paths for input, output, and manifest after the app starts.
        """
        default_input = Path('./tests/unit/test_data').resolve()
        default_output = Path('./output').resolve()
        default_manifest = Path('./manifests').resolve()

        # Set default text in the text fields
        self.root.ids.input_folder.text = str(default_input)
        self.root.ids.output_folder.text = str(default_output)
        self.root.ids.manifest_folder.text = str(default_manifest)

    def select_folder(self, folder_type):
        """
        Open a folder chooser dialog for selecting folders.
        """
        chooser = FileChooserIconView()
        chooser.path = os.path.expanduser('~')  # Default path for folder chooser
        chooser.filters = ['*']  # Show all files and directories

        # Create the popup dialog with the folder chooser
        content = BoxLayout(orientation='vertical')
        content.add_widget(chooser)
        
        button_layout = BoxLayout(size_hint_y=None, height='50dp')
        cancel_btn = Button(text="Cancel", on_press=self.dismiss_dialog)
        ok_btn = Button(text="OK", on_press=lambda instance: self.set_folder(folder_type, chooser.path))
        button_layout.add_widget(cancel_btn)
        button_layout.add_widget(ok_btn)

        content.add_widget(button_layout)
        self.dialog = Popup(title="Select Folder", content=content, size_hint=(0.8, 0.8))
        self.dialog.open()

    def dismiss_dialog(self, instance):
        self.dialog.dismiss()

    def set_folder(self, folder_type, folder_path):
        """
        Set the selected folder path to the corresponding text field.
        """
        if not folder_path:
            return
        
        folder_input_map = {
            "input": self.root.ids.input_folder,
            "output": self.root.ids.output_folder,
            "manifest": self.root.ids.manifest_folder,
        }
        folder_input_map[folder_type].text = folder_path
        self.dialog.dismiss()

    def run_pipeline(self):
        """
        Trigger the ETL pipeline with the selected folders.
        """
        input_folder = Path(self.root.ids.input_folder.text)
        output_folder = Path(self.root.ids.output_folder.text)
        manifest_folder = Path(self.root.ids.manifest_folder.text)

        # Check if any folder is missing or invalid
        if not (input_folder.exists() and output_folder.exists() and manifest_folder.exists()):
            self.update_status("Please select valid folder paths.")
            return

        try:
            # Create and run the ETL pipeline
            etl_pipeline = create_etl_pipeline(
                extract=read_from_aisr_csv,
                transform=transform_data_from_aisr_to_infinite_campus,
                load=write_to_infinite_campus_csv,
            )
            etl_pipeline_with_logging = log_etl_run(manifest_folder)(etl_pipeline)

            # Running the ETL pipeline
            self.update_status("Transforming CSVs...")
            run_etl_on_folder(
                input_folder=input_folder,
                output_folder=output_folder,
                etl_fn=etl_pipeline_with_logging,
            )
            self.update_status(f"Data transformation successful, output saved to {Path(self.root.ids.output_folder.text)}")
        except Exception as e:
            # Error handling during ETL execution
            self.update_status(f"Error: {e}")

    def update_status(self, text):
        self.root.ids.status_label.text = text


if __name__ == '__main__':
    PipelineApp().run()
