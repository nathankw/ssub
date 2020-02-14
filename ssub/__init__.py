import os

LOG_DIR = "Logs_" + __package__.capitalize()

DEMUX_FOLDER_NAME = "demux"

#: The JSON Schema file that defines the properties of the configuration file.
CONF_SCHEMA = os.path.join(os.path.dirname(__file__), "schema.json")
