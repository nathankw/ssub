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
from sruns_monitor import logging_utils
from sruns_monitor  import gcstorage_utils
from sruns_monitor import utils as srm_utils

import sssub

from google.cloud import firestore
from google.cloud import pubsub_v1
import google.api_core.exceptions

"""
GCP documentation for creating a notification configuration at https://cloud.google.com/storage/docs/pubsub-notifications.
GCP documentation for synchronous pull at https://cloud.google.com/pubsub/docs/pull#synchronous_pull.
"""


class Poll:

    def __init__(self, subscription_name, conf_file, gcp_project_id=""):
        """
        Creates a sub directory named sssub_demultiplexing within the calling directory.

        Args:
            subscription_name: `str`. The name of the Pub
            gcp_project_id: `str`. The ID of the GCP project in which the subscription identified by
                the 'subscription_name` parameter was created. If left blank, it will be extracted from
                the standard environment variable GCP_PROJECT.
        """
        self.logger = self._set_logger()
        self.subscription_name = subscription_name
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
        self.basedir = os.path.join(os.getcwd(), "sssub_demultiplexing")
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

    def get_firestore_document(self, run_name):
        """
        Retrieves a document in the Firestore collection that has the given entry name.

        Args:
            run_name: `str`. The name of the sequencing run at hand. Used to query Firestore for a
                document having the 'name' attribute set to this.

        Returns: `google.cloud.firestore_v1.document.DocumentReference`
        """

        self.logger.info(f"Querying Firestore for a document with name '{run_name}'")
        return self.firestore_coll.document(run_name)

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
        #: docref is a `google.cloud.firestore_v1.document.DocumentReference` object.
        docref = self.get_firestore_document(run_name=run_name)
        doc = docref.get().to_dict() # dict
        if not doc:
            msg = f"No Firestore document exists for run '{run_name}'."
            raise srm_exceptions.FirestoreDocumentMissing(msg)
        # Get path to raw run data (tarball) in Google Storage. Has bucket name as prefix, i.e.
        # mybucket/path/to/obj
        gs_rundir_path = doc.get(srm.FIRESTORE_ATTR_STORAGE)
        if not gs_rundir_path:
            msg = f"Firestore document '{run_name}' doesn't have the storage path attribute '{srm.FIRESTORE_ATTR_STORAGE}' set!"
            msg += f" Did the sequencing run finish uploading to Google Storeage yet?"
            raise srm_exceptions.FirestoreDocumentMissingStoragePath(msg)
        run_bucket_name, gs_rundir_path = gs_rundir_path.split("/", 1)
        run_bucket = gcstorage_utils.get_bucket(run_bucket_name)
        # Check if we have a previous sample sheet message that we stored in the Firestore
        # document.
        samplesheet_pubsub_data = doc.get(srm.FIRESTORE_ATTR_SS_PUBSUB_DATA)
        if not samplesheet_pubsub_data:
            docref.update({srm.FIRESTORE_ATTR_SS_PUBSUB_DATA: jdata})
        else:
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
                # Acknowledge the received message so it won't be sent again.
                self.subscriber.acknowledge(self.subscription_path, ack_ids=[received_message.ack_id])
                return
            else:
                # Overwrite previous value for srm.FIRESTORE_ATTR_SS_PUBSUB_DATA with most
                # recent pubsub message data.
                docref.update({srm.FIRESTORE_ATTR_SS_PUBSUB_DATA: jdata})
                # Acknowledge the received message so it won't be sent again.
                self.subscriber.acknowledge(self.subscription_path, ack_ids=[received_message.ack_id])
        msg = f"Processing SampleSheet for run name {run_name}"
        self.logger.info(msg)
        self.send_mail(subject=f"ssub: {run_name}", body=msg)
        # Download raw run data
        download_dir = os.path.join(self.basedir, run_name, jdata["generation"])
        raw_rundir_path = gcstorage_utils.download(bucket=run_bucket, object_path=gs_rundir_path, download_dir=download_dir)
        ss_bucket = gcstorage_utils.get_bucket(jdata["bucket"])
        samplesheet_path = gcstorage_utils.download(bucket=ss_bucket, object_path=jdata["name"], download_dir=download_dir)
        # Extract tarball
        srm_utils.extract(raw_rundir_path, where=download_dir)
        # Launch bcl2fastq
        demux_dir = self.run_bcl2fastq(rundir=os.path.join(download_dir, run_name), samplesheet=samplesheet_path)
        self.upload_demux(bucket=ss_bucket, path=demux_dir, run_name=run_name)

    def run_bcl2fastq(self, rundir, samplesheet):
        """
        Demultiplexes the provided run directory using bcl2fastq and outputs the results in a
        folder named 'demux' that will reside within the run directory.

        Args:
            rundir: `str`. Directory path to the sequencing run.
            samplesheet_path: `str`. Directory path to the SampleSheet.

        Returns:
            `str`. The path to the directory that contains the demultiplexing results.

        Raises:
            `subprocess.SubprocessError`: There was a problem running bcl2fastq. The STDOUT and
                STDERR will be logged.
        """
        self.logger.info("Starting bcl2fastq for run {rundir} and SampleSheet {samplesheet}.")
        outdir = os.path.join(rundir, "demux")
        cmd = "bcl2fastq"
        cmd += f" --sample-sheet {samplesheet} -R {rundir} --ignore-missing-bcls --ignore-missing-filter"
        cmd += f" --ignore-missing-positions --output-dir {outdir}"
        self.logger.info(cmd)
        try:
            stdout, stderr = srm_utils.create_subprocess(cmd)
        except subprocess.SubprocessError as e:
            self.logger.critical(str(e))
            raise
        self.logger.info(f"Finished running bcl2fastq. STDOUT was '{stdout}', STDERR was '{stderr}'.")
        return outdir

    def upload_demux(self, bucket_name,  path, run_name):
        """
        Uploads a demultiplexing results folder to Google Storage. For example, if the run name
        is BOB and the demultiplexing folder is at /path/to/BOB/demux, and the bucket is
        named myruns, then the folder will be uploaded to gs://myruns/BOB/demux.

        Args:
            bucket_name: `str`. The name of the bucket.
            path: `str`. The path to the folder that contains the demultiplexing results.
            run_name: `str`. Name of the sequencing run (rundir).
        """
        bucket_path = f"{run_name}/"
        self.logger.info(f"Uploading demultiplexing results for run {run_name}")
        gcstorage_utils.upload_folder(bucket=bucket, folder=path, bucket_path=bucket_path)

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


