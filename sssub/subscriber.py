import argparse
import json
import logging
import os
from pprint import pformat
import subprocess
import sys
import time
import traceback

import sruns_monitor as srm
from sruns_monitor import exceptions as srm_exceptions
from sruns_monitor.firestore_utils import FirestoreCollection
from sruns_monitor import logging_utils
from sruns_monitor  import gcstorage_utils
from sruns_monitor import utils as srm_utils

import sssub

from google.cloud import pubsub_v1
import google.api_core.exceptions

"""
GCP documentation for creating a notification configuration at https://cloud.google.com/storage/docs/pubsub-notifications.
GCP documentation for synchronous pull at https://cloud.google.com/pubsub/docs/pull#synchronous_pull.
"""

logger = logging.getLogger(__name__)
logger.setLevel(logging.DEBUG)
ch = logging.StreamHandler(stream=sys.stdout)
ch.setLevel(logging.DEBUG)
ch.setFormatter(logging_utils.FORMATTER)
logger.addHandler(ch)


class FirestoreMissingPubSubMessage(Exception):
    """
    Raised when an attempt is made to access `srm.FIRESTORE_ATTR_SS_PUBSUB_DATA` in a Firestore Document, but the attribute
    isn't set.
    """

def get_basedir():
    basedir = os.path.join(os.getcwd(), "sssub_demultiplexing")
    if not os.path.exists(basedir):
        logger.info("Creating directory " + os.path.join(os.getcwd(), self.basedir))
        os.makedirs(self.basedir)
    return basedir

class Poll:

    def __init__(self, subscription_name, conf_file, gcp_project_id="", demuxtest=False):
        """
        Creates a sub directory named sssub_demultiplexing within the calling directory.

        Args:
            subscription_name: `str`. The name of the Pub/Sub subscription.
            conf_file: `str`. Path to the JSON configurationn file. 
            gcp_project_id: `str`. The ID of the GCP project in which the subscription identified by
                the 'subscription_name` parameter was created. If left blank, it will be extracted from
                the standard environment variable GCP_PROJECT.
            demuxtest: `bool`. True means to demultiplex only a single tile (s_1_1101) - handy when developing/testing. 
        """
        self.logger = self._set_logger()
        self.demuxtest = demuxtest
        self.subscription_name = subscription_name
        self.conf_file = conf_file
        self.conf = srm_utils.validate_conf(conf_file, schema_file=sssub.CONF_SCHEMA)
        #: The name of the subscriber client. The name will appear in the subject line if email notification
        #: is configured, as well as in other places, i.e. log messages.
        self.client_name = self.conf[srm.C_MONITOR_NAME]
        self.gcp_project_id = gcp_project_id
        if not self.gcp_project_id:
            try:
                self.gcp_project_id = os.environ["GCP_PROJECT"]
            except KeyError:
                msg = "You must set the GCP_PROJECT environment variable when the 'gcp_project_id' argument is not set."
                self.logger.critical(msg)
                sys.exit(-1)
        #: Path to the base directory in which all further actions take place, i.e. downloads, 
        #: and running bcl2fastq. Will be created if the path does not yet exist.
        self.basedir = get_basedir()
        #: When an analysis directory in the directory specified by `self.basedir` is older than
        #: this many seconds, remove it.
        #: If not specified in configuration file, defaults to 604800 (1 week).
        self.sweep_age_sec = self.conf.get(srm.C_SWEEP_AGE_SEC, 604800)
        self.subscriber = pubsub_v1.SubscriberClient()
        self.subscription_path = self.subscriber.subscription_path(self.gcp_project_id, self.subscription_name)
        self.logger.info(f"Subscription path: {self.subscription_path}")
        self.firestore_collection_name = self.conf[srm.C_FIRESTORE_COLLECTION]
        self.firestore_coll = FirestoreCollection(self.firestore_collection_name)

    def _set_logger(self):
        # Add debug file handler to the logger:
        logging_utils.add_file_handler(logger=logger, log_dir=srm.LOG_DIR, level=logging.DEBUG, tag="debug")
        # Add error file handler to the logger:
        logging_utils.add_file_handler(logger=logger, log_dir=srm.LOG_DIR, level=logging.ERROR, tag="error")
        return logger

    def get_mail_params(self):
        return self.conf.get(srm.C_MAIL)

    def send_mail(self, subject, body):
        """
        Sends an email if the mail parameters are provided in the configuration.
        Prior to sending an email, the subject and body of the email will be logged.

        Args:
            subject: `str`. The email's subject. Note that the subject will be mangled a bit -
                it will be prefixed with `self.monitor_Name` plus a colon and a space.
            body: `str`. The email body w/o any markup.

        Returns: `None`.
        """
        subject = self.client_name + ": " + subject
        mail_params = self.get_mail_params()
        if not mail_params:
            return
        from_addr = mail_params["from"]
        host = mail_params["host"]
        tos = mail_params["tos"]
        self.logger.info("""
            Sending mail
            Subject: {}
            Body: {}
            """.format(subject, body))
        srm_utils.send_mail(from_addr=from_addr, to_addrs=tos, subject=subject, body=body, host=host)

    def get_msg_data(self, rcv_msg):
        """
        Loads a google.cloud.pubsub_v1.types.ReceivedMessage as JSON.

        Args:
            rcv_msg: `google.cloud.pubsub_v1.types.ReceivedMessage`.

        Returns:
            `dict`.

        Example:
            At the heart of a received message is the data that can be loaded as JSON, which will give
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
        jdata = json.loads(msg.data) # msg.data is a bytes object.
        return jdata

    def pull(self):
        """
        Returns:
            `list` of 0 or 1 `google.cloud.pubsub_v1.types.ReceivedMessage` instance.
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

        Raises:
            `sruns_monitor.exceptions.FirestoreDocumentMissing`: A corresponding Firestore document
                could not be found for the provided message.
            `sruns_monitor.exceptions.FirestoreDocumentMissingStoragePath`: The provided message's
                corresponding Firestore document is missing the storage location while it is expected.
        """
        # Get JSON form of data
        jdata = self.get_msg_data(received_message)
        self.logger.info(f"Processing message for {jdata['selfLink']}")
        run_name = jdata[srm.FIRESTORE_ATTR_RUN_NAME].split(".")[0]
        # Query Firestore for the run metadata to grab the location in Google Storage of the raw run.
        # The below line raises a sruns_monitor.exceptions.FirestoreDocumentMissing` Exception if 
        # a Firestore Document doesn't exist with an ID of $run_name.
        doc = self.firestore_coll.get(docid=run_name) # dict
        # Check if we have a previous sample sheet message that we stored in the Firestore
        # document.
        samplesheet_pubsub_data = doc.get(srm.FIRESTORE_ATTR_SS_PUBSUB_DATA)
        if samplesheet_pubsub_data:
            # Check if generation number is the same.
            # If same, then we got a duplicate message from pubsub and can ignore it. But if
            # different, then the SampleSheet was re-uploaded and we should process it again
            # (i.e. maybe the original SampleSheet had an incorrect barcode assignment).
            prev_gen = samplesheet_pubsub_data["generation"]
            current_gen = jdata["generation"]
            print(f"Current generation number: {current_gen}")
            if prev_gen == current_gen:
                self.logger.info(f"Duplicate message with generation {current_gen}; skipping.")
                # duplicate message sent. Rare, but possible occurrence.
                self.subscriber.acknowledge(self.subscription_path, ack_ids=[received_message.ack_id])
                return
        # Overwrite previous value (or set initial value) for srm.FIRESTORE_ATTR_SS_PUBSUB_DATA with most
        # recent pubsub message data.
        self.firestore_coll.update(docid=run_name, payload={srm.FIRESTORE_ATTR_SS_PUBSUB_DATA: jdata})
        # Acknowledge the received message so it won't be sent again.
        self.subscriber.acknowledge(self.subscription_path, ack_ids=[received_message.ack_id])
        msg = f"Processing SampleSheet for run name {run_name}"
        self.logger.info(msg)
        self.send_mail(subject=f"ssub: {run_name}", body=msg)
        # Download raw run and SampleSheet and demultiplex
        wf = Workflow(conf_file=self.conf_file, run_name=run_name, demuxtest=self.demuxtest)
        wf.run()

    def start(self):
        interval = self.conf.get(srm.C_CYCLE_PAUSE_SEC, 60)
        try:
            while True:
                received_message = self.pull()
                if received_message:
                    self.process_message(received_message)
                deleted_dirs = srm_utils.clean_completed_runs(basedir=self.basedir, limit=self.sweep_age_sec)
                if deleted_dirs:
                    for d_path in deleted_dirs:
                        self.logger.info("Deleted directory {}".format(d_path))
                time.sleep(interval)
        except Exception as e:
            tb = e.__traceback__
            tb_msg = pformat(traceback.extract_tb(tb).format())                                 
            msg = "Main process Exception: {} {}".format(e, tb_msg)
            self.logger.error(msg)
            self.send_mail(subject="Error", body=msg)
            raise


class Workflow:
    def __init__(self, conf_file, run_name, demuxtest=False):
        """
        Args:
            conf_file: `str`. Path to the JSON configurationn file. 
            run_name: `str`. The name of the sequencing run to process. 
            demuxtest: `bool`. True means to demultiplex only a single tile (s_1_1101) - handy when developing/testing.
        """
        self.conf_file = conf_file
        self.conf = srm_utils.validate_conf(conf_file, schema_file=sssub.CONF_SCHEMA)
        self.run_name = run_name
        self.demuxtest = demuxtest
        #: Path to the base directory in which all further actions take place, i.e. downloads, 
        #: and running bcl2fastq. Will be created if the path does not yet exist.
        self.basedir = get_basedir()
        self.firestore_collection_name = self.conf[srm.C_FIRESTORE_COLLECTION]
        self.firestore_coll = FirestoreCollection(self.firestore_collection_name)
        self.firestore_doc = self.firestore_coll.get(run_name)
        self.psmsg = self.firestore_doc.get(srm.FIRESTORE_ATTR_SS_PUBSUB_DATA)
        if not self.psmsg:
            msg = f"Firestore document ID '{run_name}' does not have a value set for attribute '{srm.FIRESTORE_ATTR_SS_PUBSUB_DATA}'."
            logger.critical(msg)
            raise FirestoreMissingPubSubMessage(msg)
        # Get path to raw run data (tarball) in Google Storage. Has bucket name as prefix, i.e.
        # mybucket/path/to/obj
        gs_rundir_path = self.firestore_doc.get(srm.FIRESTORE_ATTR_STORAGE)
        if not gs_rundir_path:
            msg = f"Firestore document '{self.run_name}' doesn't have the storage path attribute '{srm.FIRESTORE_ATTR_STORAGE}' set!"
            msg += f" Did the sequencing run finish uploading to Google Storeage yet?"
            raise srm_exceptions.FirestoreDocumentMissingStoragePath(msg)
        run_bucket_name, self.gs_rundir_path = gs_rundir_path.split("/", 1)
        self.run_bucket = gcstorage_utils.get_bucket(run_bucket_name)
        self.download_dir = self.get_download_dir()

    def get_local_rundir_path(self):
        """
        Absolute, local path to the sequencing run directory. 
        Once downloaded by `self.download_rawrun`, this should be it's full path.
        """
        return os.path.join(self.download_dir, self.run_name)

    def get_local_samplesheet_path(self):
        """
        Absolute, local path to the samplesheet file. 
        Once downloaded by `self.download_samplesheet`, this should be it's full path.
        """
        return os.path.join(self.download_dir, self.psmsg["name"])

    def run(self):
        self.download_samplesheet()
        raw_rundir_path = self.download_rawrun()
        # Extract tarball in same directory in which raw_rundir_path resides
        self.extract_run(raw_rundir_path)
        # Launch bcl2fastq
        demux_dir = self.run_bcl2fastq()
        self.upload_demux(path=demux_dir)

    def get_download_dir(self):
        return os.path.join(self.basedir, self.run_name, self.psmsg["generation"])

    def download_samplesheet(self):
        ss_bucket = gcstorage_utils.get_bucket(self.psmsg["bucket"])
        samplesheet_path = gcstorage_utils.download(bucket=ss_bucket, object_path=self.psmsg["name"], download_dir=self.download_dir)
        return samplesheet_path
   
    def download_rawrun(self):
        raw_rundir_path = gcstorage_utils.download(bucket=self.run_bucket, object_path=self.gs_rundir_path, download_dir=self.download_dir)
        return raw_rundir_path
            
    def extract_run(self, raw_rundir_path):
        srm_utils.extract(raw_rundir_path, where=self.download_dir)

    def run_bcl2fastq(self):
        """
        Demultiplexes the provided run directory using bcl2fastq and outputs the results in a
        folder named 'demux' that will reside within the run directory.

        Returns:
            `str`. The path to the directory that contains the demultiplexing results.

        Raises:
            `subprocess.SubprocessError`: There was a problem running bcl2fastq. The STDOUT and
                STDERR will be logged.
        """
        rundir = self.get_local_rundir_path()
        samplesheet_path = self.get_local_samplesheet_path()
        logger.info(f"Starting bcl2fastq for run {rundir} and SampleSheet {samplesheet_path}.")
        outdir = os.path.join(rundir, "demux")
        cmd = "bcl2fastq"
        if self.demuxtest:
            cmd += " --tiles s_1_1101"
        cmd += f" --sample-sheet {samplesheet_path} -R {rundir} --ignore-missing-bcls --ignore-missing-filter"
        cmd += f" --ignore-missing-positions --output-dir {outdir}"
        logger.info(cmd)
        try:
            stdout, stderr = srm_utils.create_subprocess(cmd)
        except subprocess.SubprocessError as e:
            logger.critical(str(e))
            raise
        logger.info(f"Finished running bcl2fastq. STDOUT was '{stdout}', STDERR was '{stderr}'.")
        return outdir

    def upload_demux(self, path):
        """
        Uploads a demultiplexing results folder to Google Storage. For example, if the run name
        is BOB and the demultiplexing folder is at /path/to/BOB/demux, and the bucket is
        named myruns, then the folder will be uploaded to gs://myruns/BOB/demux.

        Args:
            path: `str`. The path to the folder that contains the demultiplexing results.
        """
        bucket_path = f"{self.run_name}/"
        logger.info(f"Uploading demultiplexing results for run {self.run_name}")
        gcstorage_utils.upload_folder(bucket=self.run_bucket, folder=path, bucket_path=bucket_path)

