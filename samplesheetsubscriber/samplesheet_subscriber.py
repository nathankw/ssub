import argparse
import json
import logging
import os
import subprocess
import sys
import time

import sruns_monitor as srm
import samplesheetsubscriber as sss
from sruns_monitor import logging_utils
from sruns_monitor  import gcstorage_utils
from sruns_monitor import utils

from google.cloud import firestore
from google.cloud import pubsub_v1
import google.api_core.exceptions

"""
howdy

pip install google-cloud-pubsub
GCP documentation for creating a notification configuration at https://cloud.google.com/storage/docs/pubsub-notifications.
GCP documentation for synchronous pull at https://cloud.google.com/pubsub/docs/pull#synchronous_pull.
"""


class Poll:

    def __init__(self, subscription_name, conf_file, gcp_project_id=""):
        """
        Args:
            gcp_project_id: `str`. The ID of the GCP project. If left blank, it will be extracted from
                the standard environment variable GCP_PROJECT.
        """
        self.subscription_name = subscription_name
        self.logger = self._set_logger()
        self.conf = utils.validate_conf(conf_file, schema_file=sss.CONF_SCHEMA)
        self.gcp_project_id = gcp_project_id
        if not self.gcp_project_id:
            try:
                self.gcp_project_id = os.environ["GCP_PROJECT"]
            except KeyError:
                msg = "You must set the GCP_PROJECT environment variable when the 'gcp_project_id' argument is not set."
                self.logger.critical(msg)
                sys.exit(-1)
        self.basedir = self.conf.get(sss.C_ANALYSIS_DIR, "demultiplexing")
        if not os.path.exists(self.basedir):
            self.logger.info("Creating directory " + os.path.join(os.getcwd(), self.basedir))
            os.makedirs(self.basedir)
        #: When an analysis directory in the directory specified by `self.basedir` is older than
        #: this many seconds, remove it.
        #: If not specified in configuration file, defaults to 604800 (1 week).
        self.sweep_age_sec = self.conf.get(srm.C_SWEEP_AGE_SEC, 604800)
        self.subscriber = pubsub_v1.SubscriberClient()
        self.subscription_path = self.subscriber.subscription_path(self.gcp_project_id, self.subscription_name)
        self.logger.info(f"Subscription path: {self.subscription_path}")
        self.firestore_collection_name = self.conf.get(srm.C_FIRESTORE_COLLECTION)
        self.firestore_coll = firestore.Client().collection(self.firestore_collection_name)

    def _set_logger(self):
        logger = logging.getLogger("SampleSheetSubscriber")
        logger.setLevel(logging.DEBUG)
        ch = logging.StreamHandler(stream=sys.stdout)
        ch.setLevel(logging.DEBUG)
        ch.setFormatter(logging_utils.FORMATTER)
        logger.addHandler(ch)
        # Add debug file handler to the logger:
        logging_utils.add_file_handler(logger=logger, log_dir=srm.LOG_DIR, level=logging.DEBUG, tag="debug")
        # Add error file handler to the logger:
        logging_utils.add_file_handler(logger=logger, log_dir=srm.LOG_DIR, level=logging.ERROR, tag="error")
        return logger

    def get_firestore_document(self, run_name):
        """
        Args:
            run_name: `str`. The name of the sequencing run at hand. Used to query Firestore for a
                document having the 'name' attribute set to this.

        Returns: `google.cloud.firestore_v1.document.DocumentReference`
        """

        self.logger.info(f"Querying Firestore for a document with name '{run_name}'")
        return self.firestore_coll.document(run_name)

    def get_msg_data(self, rcv_msg):
        """
        Args:
            rcv_msg: `google.cloud.pubsub_v1.types.ReceivedMessage`.

        Example:
            At the heart of the received messages is the data that can be loaded as JSON, which will give
            us something like this:

            > jdata = json.loads(rcv_msg.message.data)
            > print(json.dumps(jdata), indent=4)

            {
                "kind": "storage#object",
                "id": "mysamplesheets/191022_A00737_0011_BHNLYYDSXX.csv/1576441248192471",
                "selfLink": "https://www.googleapis.com/storage/v1/b/mysamplesheets/o/191022_A00737_0011_BHNLYYDSXX.csv",
                "name": "191022_A00737_0011_BHNLYYDSXX.csv",
                "bucket": "mysamplesheets",
                "generation": "1576441248192471",
                "metageneration": "1",
                "contentType": "text/csv",
                "timeCreated": "2019-12-15T20:20:48.192Z",
                "updated": "2019-12-15T20:20:48.192Z",
                "storageClass": "STANDARD",
                "timeStorageClassUpdated": "2019-12-15T20:20:48.192Z",
                "size": "768",
                "md5Hash": "263ptiIm6ZYJ5u1KahDHzw==",
                "mediaLink": "https://www.googleapis.com/download/storage/v1/b/mysamplesheets/o/191022_A00737_0011_BHNLYYDSXX.csv?generation=1576441248192471&alt=media",
                "crc32c": "kgzmwA==",
                "etag": "CNev7qS9uOYCEAE="
            }
        """
        #: msg is a `google.cloud.pubsub_v1.types.PubsubMessage`
        msg = rcv_msg.message
        #: msg.data is a `bytes` object.
        jdata = json.loads(msg.data)
        return jdata

    def pull(self):
        """
        Returns:
            `list` of 0 or more `google.cloud.pubsub_v1.types.ReceivedMessage` instances.
        """
        try:
            #: response is a PullResponse instance; see
            #: https://googleapis.dev/python/pubsub/latest/types.html#google.cloud.pubsub_v1.types.PullResponse
            response = self.subscriber.pull(self.subscription_path, max_messages=1)
        except google.api_core.exceptions.DeadlineExceeded:
            self.logger.info("Nothing for now!")
            return []
        return response.received_messages[0]

    def process_message(self, received_message):
        """
        Args:
            received_message: A `google.cloud.pubsub_v1.types.ReceivedMessage` instance.
        """
        # Get JSON form of data
        jdata = self.get_msg_data(received_message)
        self.logger.info(f"Processing message for {jdata['selfLink']}")
        run_name = jdata[srm.FIRESTORE_ATTR_RUN_NAME].split(".")[0]
        # Query Firestore for the run metadata to grab the location in Google Storage of the raw run.
        #: docref is a `google.cloud.firestore_v1.document.DocumentReference` object.
        docref = self.get_firestore_document(run_name=run_name)
        doc = docref.get().to_dict() # dict
        if not doc:
            msg = f"No Firestore document exists for run '{run_name}'."
            raise Exception(msg)
        # Get path to raw run data in Google Storage. Has bucket name as prefix, i.e.
        # mybucket/path/to/obj
        raw_run_path = doc.get(srm.FIRESTORE_ATTR_STORAGE)
        if not raw_run_path:
            msg = f"Firestore document '{run_name}' doesn't have the storage path attribute '{srm.FIRESTORE_ATTR_STORAGE}' set!"
            msg += f" Did the sequencing run finish uploading to Google Storeage yet?"
            raise Exception(msg)
        run_bucket_name, raw_run_path = raw_run_path.split("/", 1)
        run_bucket = gcstorage_utils.get_bucket(run_bucket_name)
        # Check if we have a previous sample sheet message that we stored in the Forestore
        # document.
        samplesheet_pubsub_data = doc.get(srm.FIRESTORE_ATTR_SS_PUBSUB_DATA)
        if not samplesheet_pubsub_data:
            docref.update({srm.FIRESTORE_ATTR_SS_PUBSUB_DATA: jdata})
        else:
            # Check if generation number is the same.
            # If same, then we got a duplicate message from pubsub and can ignore. But if
            # different, then the SampleSheet was re-uploaded and we should process it again
            # (i.e. maybe the original SampleSheet had an incorrect barcode assignment).
            prev_gen = samplesheet_pubsub_data["generation"]
            current_gen = jdata["generation"]
            print(f"Current generation number: {current_gen}")
            if prev_gen == current_gen:
                self.logger.info(f"Duplicate message with generation {current_gen}; skipping.")
                # duplicate message sent. Rare, but possible occurrence.
                # Acknowledge the received message so it won't be sent again.
                self.subscriber.acknowledge(self.subscription_path, ack_ids=[received_message.ack_id])
                return
            else:
                # Overwrite previous value for srm.FIRESTORE_ATTR_SS_PUBSUB_DATA with most
                # recent pubsub message data.
                docref.update({srm.FIRESTORE_ATTR_SS_PUBSUB_DATA: jdata})
                # Acknowledge the received message so it won't be sent again.
                self.subscriber.acknowledge(self.subscription_path, ack_ids=[received_message.ack_id])
        # Download raw run data
        download_dir = os.path.join(self.basedir, run_name, jdata["generation"])
        storage_path = gcstorage_utils.download(bucket=run_bucket, object_path=raw_run_path, download_dir=download_dir)
        ss_bucket = gcstorage_utils.get_bucket(jdata["bucket"])
        samplesheet_path = gcstorage_utils.download(bucket=ss_bucket, object_path=jdata["name"], download_dir=download_dir)
        # Extract tarball
        utils.extract(storage_path, where=download_dir)
        # Launch bcl2fastq
        self.run_bcl2fastq(rundir=os.path.join(download_dir, run_name, samplesheet=samplesheet_path)

    def run_bcl2fastq(self, rundir=storage_path, samplesheet=samplesheet_path):
        """
        Args:
            rundir: `str`. Directory path to the sequencing run.
            samplesheet_path: `str`. Directory path to the SampleSheet. 
        """
        self.logger.info("Starting bcl2fastq for run {rundir} and SampleSheet {samplesheet}.")
        outdir = os.path.join(rundir, "demux")
        cmd = f"docker run -v {rundir}:{rundir} nathankw/bcl2fastq2:latest bcl2fastq" 
        cmd += f" --sample-sheet {samplesheet} -R {rundir} --ignore-missing-bcls --ignore-missing-filter"
        cmd += f" --ignore-missing-positions --output-dir {outdir}"
        self.logger.info(cmd)
        popen = subprocess.Popen(cmd, shell=True)

    def start(self):
        interval = self.conf.get(srm.C_CYCLE_PAUSE_SEC, 60)
        try:
            while True:
                received_message = self.pull()
                if received_message:
                    self.process_message(received_message)
                deleted_dirs = utils.clean_completed_runs(basedir=self.basedir, limit=self.sweep_age_sec)
                if deleted_dirs:
                    for d_path in deleted_dirs:
                        self.logger.info("Deleted directory {}".format(d_path))
                time.sleep(interval)
        except Exception:
            self.logger.debug("Oh la la")
            raise


