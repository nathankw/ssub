# -*- coding: utf-8 -*-

###
# Nathaniel Watson
# nathanielwatson@stanfordhealthcare.org
###

# For some useful documentation, see
# https://docs.python.org/2/distutils/setupscript.html.
# This page is useful for dependencies:
# http://python-packaging.readthedocs.io/en/latest/dependencies.html.

# PSF tutorial for packaging up projects:
# https://packaging.python.org/tutorials/packaging-projects/

import glob
import os
from setuptools import setup, find_packages

with open("README.rst", "r") as fh:
    long_description = fh.read()

SCRIPTS_DIR = os.path.join("samplesheetsubscriber", "scripts")
scripts = glob.glob(os.path.join(SCRIPTS_DIR,"*.py"))
scripts.remove(os.path.join(SCRIPTS_DIR,"__init__.py"))
#scripts.append("sruns_monitor/tests/monitor_integration_tests.py")

setup(
  author = "Nathaniel Watson",
  author_email = "nathan.watson86@gmail.com",
  classifiers = [
      "Programming Language :: Python :: 3",
      "License :: OSI Approved :: MIT License",
      "Operating System :: OS Independent",
  ],
  description = "Polls a GCP Pub/Sub topic for new SampleSheet notification messages in order to initiate bcl2fastq.",
  entry_points = {
      "console_scripts": [
          "ss-mon=samplesheetsubscriber.scripts.launch_samplesheetsubscriber:main"
      ]
  },
  keywords = "bcl2fastq sequencing samplesheet monitor",
  install_requires = [
    "sruns-monitor"
  ],
  long_description = long_description,
  long_description_content_type = "text/x-rst",
  name = "samplesheetmonitor",
  packages = find_packages(),
  package_data = {
      "samplesheetmonitor": ["schema.json"],
  },
  project_urls = {
      "Read the Docs": "https://samplesheetmonitor.readthedocs.io/en/latest"
  },
  scripts = scripts,
  url = "https://pypi.org/project/samplesheetmonitor/",
  version = "0.1.0"
)
