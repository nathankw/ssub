SampleSheets Subscriber - sssub
*******************************

A downstream tool of smon_ that uses Pub/Sub notifications to initiate demultiplexing of an 
Illumina sequecing Run.

Use case
========
smon_ has done its job to persistantly store the raw sequencing runs in a Google Storage bucket.
Now you need another tool that can automatially start demultiplexing. However, demultiplexing can't 
start until you have a SampleSheet.  But once it's there, demultiplexing needs to start and the
results need to be uploaded to Google Storage. 

How it works
============
SampleSheets Subscriber (sssub) solves the aforementioned challenges by utilizing the power of GCP
events and triggers. At a high level, it works as follows:

  * User/application uploads a samplesheet to a dedicated bucket. The sample sheet naming convention 
    is ${RUN_NAME }.csv.
  * Google Storage immediately fires off an event to a Pub/Sub topic (whenever there is a new file
    or when an existing file is overwritten).
  * sssub is running on a compute instance as a daemon process.  It is subscribed to that Pub/Sub 
    topic. sssub polls the topic for new messages regularly, i.e. once a minute.
  * When a new message is received, the script parses information about the event.
  * sssub will the query the Firestore collection - the same one used by smon_ - for a 
    document whose name is equal to the samplesheet name (minus the .csv part).
    sssub will then download both the samplesheet and the run tarball.  The samplesheet location
    is provided in the Pub/Sub message; the raw run tarball location is provided within the 
    Firestore document.
  * sssub will then kick off bcl2fastq. 
  * sssub will finally upload the demultiplexing results to the same Google Storage bucket that
    contains the raw sequencing run, and its storage location will be recorded in Firestore document.

Setup
-----

#. You should already have a Firestore collection for smon's use.  smon will create one for you
   if necessary, but you can create one in advance if you'd like for manual testing. See the
   documentation for smon_ for details on the structure of the documents stored in this collection.
#. Create a dedicated Google Storage bucket for storing your SampleSheets and give it a useful name,
   i.e. samplesheets.
#. Create a dedicated Pub/Sub topic and give it a useful name, i.e. samplesheets.
#. Create a `notification configuration`_ so that your samplesheets storage bucket will notify
   the samplesheets Pub/Sub topic whenever a new file is added or modified. Note that you can use
   gsutil for this as detailed `here <https://cloud.google.com/storage/docs/gsutil/commands/notification>`_.
   Here is an example command::
   
     gsutil notification create -e OBJECT_FINALIZE -t samplesheets gs://samplesheets

#. Create a Pub/Sub subscription. For example::

     gcloud beta pubsub subscriptions create --topic samplesheets sssub

Mail notifications
------------------
If the 'mail' JSON object is set in your JSON configuration file, then the designated recipients will
receive email notifications under the folowing events:

  * There is an Exception in the main thread
  * A new Pub/Sub message is being processed (duplicates excluded). 

You can use the script `send_test_email.py` to test that the mail configuration you provide is
working. If it is, you should receive an email with the subject "sssub test email". 

The configuration file
======================
This is a small JSON file that lets the monitor know things such as which GCP bucket and Firestore
collection to use, for example. The possible keys are:

  * `name`: The client name of the subscriber. The name will appear in the subject line if email 
    notification is configured, as well as in other places, i.e. log messages.
  * `cycle_pause_sec`: The number of seconds to wait in-between scans of `watchdir`. Defaults to 60.
  * `firestore_collection`: The name of the Google Firestore collection to use for
    persistent workflow state that downstream tools can query. If it doesn't exist yet, it will be
    created. If this parameter is not provided, support for Firestore is turned off. 
  * `sweep_age_sec`: When a run in the completed runs directory is older than this many seconds, 
    remove it. Defaults to 604800 (1 week).

The user-supplied configuration file is validated in the Monitor against a built-in schema. 

Installation and setup
======================
This works in later versions of Python 3 only::

  pip3 install sssub

It is recommended to start your compute instance (that will run the monitor) using a service account
with the following roles:

  * roles/storage.objectAdmin
  * roles/datastore.owner


.. _smon: https://pypi.org/project/sruns-monitor/
.. _`notification configuration`: https://cloud.google.com/storage/docs/pubsub-notifications
