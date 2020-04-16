SampleSheet Subscriber - ssub
*******************************

A downstream tool of smon_ that uses Pub/Sub notifications to initiate demultiplexing of an 
Illumina sequecing Run.

Use case
========
smon_ has done its job to persistantly store the raw sequencing runs in a Google Storage bucket.
Now another tool is necessary that can automatially start demultiplexing. However, demultiplexing 
generally mustn't begin until it has a SampleSheet. But once a SampleSheet is readily available, 
demultiplexing needs to start and the results need to be uploaded to Google Storage. 

How it works
============
SampleSheets Subscriber (ssub) solves the aforementioned challenges by utilizing the power of GCP
events and triggers. At a high level, it works as follows:

  #. User/application uploads a samplesheet to a dedicated bucket. The sample sheet naming convention 
     is ${RUN_NAME }.csv.
  #. Google Storage immediately fires off an event to a Pub/Sub topic (whenever there is a new SampleSheet
     or when an existing one is overwritten).
  #. Meanwhile, ssub is running on a compute instance as a daemon process.  It is subscribed to that 
     same Pub/Sub topic. ssub polls the topic for new messages regularly, i.e. once a minute.
  #. When ssub receives a new message, the script parses information about the event.
  #. ssub will the query the Firestore collection - the same one used by smon_ - for a 
     document whose name is equal to the samplesheet name (minus the .csv part).
     ssub will then download both the samplesheet and the run tarball.  The samplesheet location
     is provided in the Pub/Sub message; the raw run tarball location is provided within the 
     Firestore document.
  #. ssub will then kick off bcl2fastq. 
  #. Demultiplexing results are output in a folder name 'demux' within the local run directory.
  #. ssub will upload the demux folder to the same Google Storage folder that
     contains the raw sequencing run.
  #. ssub will update the relevant Firestore document to add the location to the demux folder in 
     Google Storage.

All processing happens within a sub-directory of the calling directory that is named
ssub_runs. 

Reanalysis
==========
Reruns of the dmeultiplexing pipeline may be necessary for various reasons, i.e. the 
demultiplexing results are no longer available and need to be regenerated, or there was a missing
barcode in the SampleSheet, or there was an incorrect barcode in the SampleSheet ...

Reanalysis is easily accomplished simply by re-uploading the SampleSheet, overwriting the previous one,
to Google Storage. Google Storage will assign a generation number to the SampleSheet.  Think of the
generation number as a type of versioning number that Google Storage assigns to each object each time
that the object changes. Even re-uploading the same exact same file again produces a new generation
number.

Internally, ssub does all of it's processing (file downloads, analysis) within a local directory
path named after the run and the generation number of the SampleSheet. Thus, it's perfectly fine for a user to 
upload an incorrect SampleSheet, and then to immediately afterwards upload the correct one. 
In such a scenario, there will be two runs of the pipeline, and they won't interfere with each other. 
You will notice, however, that there will be two sets of demultplexing results uploaded to Google 
Storage, each of which exist within a folder named after the original generation number. 

Scalablilty
-----------
While thare aren't any parallel steps in ssub, you can achieve scalability by launching two or more
instances of ssub, either on one single, beefy compute instance, or on separate ones. While it's 
certainly possible that two running instances of ssub can pull the same message from Pub/Sub, only
one of these two insances will actually make use of it. It works as follows: 

    #. Instance 1 of ssub receives a new message from Pub/Sub and immediately begings to process it.
    #. Instances 1 downloads and parses the corresponding Firestore document that's related to the
       SampleSheet detailed within the Pub/Sub message.
    #. Instance 1 notices that the document doesn't have the `ssub.FIRESTORE_ATTR_SS_PUBSUB_DATA` 
       attribute set, so then sets it to the value of the JSON serialized of the PUb/Sub message
       data.
    #. Meanwhile, Instance 2 of ssub has also pulled down the same Pub/Sub message.
    #. Instance 2 queries Firestore and downloads the corresponding document. 
    #. Instance 2 notices that the document attribute `ssub.FIRESTORE_ATTR_SS_PUBSUB_DATA` is already
       set, so it downloades this JSON value.
    #. Instance 2 then parses the generation number out of the JSON value it downloaded from
       Firestore and notices that the generation number is the same as the generation number in the
       Pub/Sub message that it is currently working on.
    #. Instance 2 logs a message that it is deferring further processing - thus leaving the rest 
       of the work to be fulfilled by Instance 1. 

Let's now take a few steps back and pose the question - What if Instance 2 noticed that the generation
numbers differ? Well, in this case, it will continue on to run the demultiplexing workflow since
there are different versions of the SampleSheet at hand. It will also, however, first set the 
Firestore document's `ssub.FIRESTORE_ATTR_SS_PUBSUB_DATA` attribute to the JSON serialization of the
Pub/Sub message data that it's working on. 

Note: If using more than one deployment of ssub on the same instance, it is recommended to run each in a
separate working directory.  


Setup
-----

#. You should already have a Firestore collection for smon's use.  smon will create one for you
   if necessary, but you can create one in advance if you'd like for manual testing. See the
   documentation for smon_ for details on the structure of the documents stored in this collection.
#. Create a dedicated Google Storage bucket for storing your SampleSheets and give it a useful name,
   i.e. samplesheets.  Make sure to set the bucket to use Fine-Grained access control rather than Uniform.
#. Create a dedicated Pub/Sub topic and give it a useful name, i.e. samplesheets.
#. Create a `notification configuration`_ so that your samplesheets storage bucket will notify
   the samplesheets Pub/Sub topic whenever a new file is added or modified. Note that you can use
   gsutil for this as detailed `here <https://cloud.google.com/storage/docs/gsutil/commands/notification>`_.
   Here is an example command::
   
     gsutil notification create -e OBJECT_FINALIZE -f json -t samplesheets gs://samplesheets

   If you get an access denied error while doing this, give the included script named 
   **create_notification_configuration.py** a try. It uses the GCP Python API and is much easier to
   work with in regards to how permissions are configured. 

#. Create a Pub/Sub subscription. For example::

     gcloud beta pubsub subscriptions create --topic samplesheets ssub

#. Locate the Cloud Storage service account and grant it the IAM role pubsub.publisher.
   By default, a bucket doesn't have the priviledge to send notifications to Pub/Sub. Follow the 
   instructions in steps 5 and 6 in this `GCP documentation  <https://cloud.google.com/storage/docs/reporting-changes>`_.


Mail notifications
------------------
If the 'mail' JSON object is set in your JSON configuration file, then the designated recipients will
receive email notifications under the folowing events:

  * There is an Exception in the main thread
  * A new Pub/Sub message is being processed (duplicates excluded). 

You can use the script `send_test_email.py` to test that the mail configuration you provide is
working. If it is, you should receive an email with the subject "ssub test email". 

The configuration file
======================
This is a small JSON file that lets the monitor know things such as which GCP bucket and Firestore
collection to use, for example. The possible keys are:

  * `name`: The client name of the subscriber. The name will appear in the subject line if email 
    notification is configured, as well as in other places, i.e. log messages.
  * `cycle_pause_sec`: The number of seconds to wait in-between polls of the Pub/Sub topic. Defaults to 60.
  * `firestore_collection`: The name of the Google Firestore collection to use for
    persistent workflow state that downstream tools can query. If it doesn't exist yet, it will be
    created. If this parameter is not provided, support for Firestore is turned off. 
  * `sweep_age_sec`: When an analysis directory (within the ssub_runs directory)
     is older than this many seconds, remove it. Defaults to 604800 (1 week).

The user-supplied configuration file is validated against a built-in schema. 

Installation
============
In a later version of Python3, run::

  pip3 install ssub

It is recommended to start your compute instance (that will run the monitor) using a service account
with the following roles:

  * roles/storage.objectAdmin
  * roles/datastore.owner

Alternatively, give your compute instance the cloud-platform scope.

Deployment:
===========
It is suggested to use the Dockerfile that comes in the respository.


.. _smon: https://pypi.org/project/sruns-monitor/
.. _`notification configuration`: https://cloud.google.com/storage/docs/pubsub-notifications


