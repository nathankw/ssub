import os

LOG_DIR = "Logs_" + __package__.capitalize()

if not os.path.exists(LOG_DIR):
    os.mkdir(LOG_DIR)  

DEMUX_FOLDER_NAME = "demux"

#: The JSON Schema file that defines the properties of the configuration file.
CONF_SCHEMA = os.path.join(os.path.dirname(__file__), "schema.json")
