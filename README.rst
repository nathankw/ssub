Sequencing Runs Monitor
***********************

A tool that archives new Illumina sequencing runs to Google Cloud Storage

Use case
========
You have one or more Illumina sequencers that are writing to a mounted filesystem such as NFS.
You need a way to detect when there is a new, completed sequencing run directory and then relocate
it to redundant storage. Downstream tools need to be able to know when a tarred run directory is
available to post-processing (i.e. demultiplexing, QC, read alignment, etc.).

How it works
============
Sequencing Runs Monitor solves the aforementioned challenges through the use of Google Cloud Platform
services and by tracking workflow state. Sequencing runs are tarred with gzip compression and then
uploaded to Google Cloud Storage. Workflow state is tracked locally via SQLite and optionally 
in the NoSQL database Google Firestore for redundancy and to allow downstream clients to query sequencing
run records. 

Note: while you don't need to use a Google compute instance to run the monitor script, the documentation
here assumes that you are since it is the recommended way. That's due to the fact that the monitor
must interact with certain GCP services, and hence must be running with proper Google credentials
(i.e. a service account).

The monitor script is named `srun-mon` (a shim that calls the `main` function in  *launch_monitor.py*).
When running this, you must provide a path to a JSON configuration file, described in detail further 
below. You should set up your compute instance to run this script as a daemon service.

The workflow is fitted into two tasks: the *tar task* and the *upload task*. When the monitor
detects a new sequencing run, it executes the workflow in a child process. The workflow is smart
enough to detect which task to begin with, thanks to the local SQLite database. This database has
a record for each sequencing run and tracks which workflow tasks have been completed, and whether
the workflow is running.

Mail notifications
------------------
If the 'mail' JSON object is set in your configuration file, then the designated recipients will
receive email notifications under the folowing events:

  * A child process running a workflow crashes
  * A child process is killed for running too long (see conf parameter `task_runtime_limit_sec`)
  * There is an Exception in the main thread
  * A new sequencing run is being processed. 

You can use the script `send_test_email.py` to test that the mail configuration you provide is
working. If it is, you should receive an email with the subject "sruns-mon test email". 

The workflow tasks
==================
The workflow is split up into two tasks, each of which can be run on its own (i.e. if the workflow
needs to be restarted from where it left off). 

Tar task
-----------
Creates a tarball with gzip compression. The process ID is stored in the local run record in the
SQLite database.

Upload task
-----------
Uploads the tarfile to a Google bucket. This task fetches the run record from the local database
to get the path to the local tarfile.

The configuration file
======================
This is a small JSON file that lets the monitor know things such as which GCP bucket and Firestore
collection to use, for example. The possible keys are:

  * `name`: The name of the monitor. The name will appear in the subject line if email notification
    is configured, as well as in other places, i.e. log messages.
  * `completed_runs_dir`:  The directory to move a run directory to after it has completed the
    workflow. This directory will be created if it doesn't yet exist.  Defaults to a folder by the 
    name 'SRM_COMPLETED` that resides within the same directory as the one being watched. Note 
    that at present, there isn't a means to clean out the completed runs directory, but that will 
    come in a future release.  
  * `cycle_pause_sec`: The number of seconds to wait in-between scans of `watchdir`. Defaults to 60.
  * `firestore_collection`: The name of the Google Firestore collection to use for
    persistent workflow state that downstream tools can query. If it doesn't exist yet, it will be
    created. If this parameter is not provided, support for Firestore is turned off. 
  * `gcp_bucket_basedir`: The directory in `gcp_bucket_name` in which to store all uploaded files.
    Defaults to the root directory.
  * `gcp_bucket_name`: (Required) The name of the Google Cloud Storage bucket to which tarred run
    directories will be uploaded.
  * `sentinal_file_age_minutes`: How old in minutes the sentinal file, i.e. CopyComplete.txt, should 
    be before initiating any tasks, such as tarring the run directory. Illumina Support recommends 
    15 minutes, which is thus the default. This helps to ensure that the Illumina Universal Copy 
    Services (UCS) running on the sequencer has had ample time to complete once the sentinal file 
    appears.
  * `sqlite_db`: The name of the local SQLite database to use for tracking workflow state.
    Defaults to *sruns.db* if not specified.
  * `sweep_age_sec`: When a run in the completed runs directory is older than this many seconds, 
    remove it. Defaults to 604800 (1 week).
  * `task_runtime_limit_sec`: The number of seconds a child process is allowed to run before
    being killed. This is meant to serve as a safety mechanism to prevent errant child processes
    from consuming resources in the event that this does happen due to unforeseen circumstances.
    An email notification will be sent out in this case to alert about the errant process
    and the sequencing run it was associated with. The number of seconds you set for this depends
    on several factors, such as run size and network speed. It is suggested to use two days (172800
    seconds) at least to be conservative.
  * `watchdir`: (Required) The directory to monitor for new sequencing runs.

The user-supplied configuration file is validated in the Monitor agains a built-in schema. 

Tracking workflow state
=======================
The state of the workflow for a given run directory is tracked both locally in a SQLite database
as well as Google Firestore - a NoSQL database. Local state is tracked for the purpose of being
able to restart workflows if a child process ever crashes, or if the node goes down. Firestore is
used to enable downstream applications to query the collection (whose name is specified in your
configuration file) to do their own post-processing as desired. For example, an external tool
could query the collection and ask if a given run is completed yet. Completed in this sense means
that the run was tarred and uploded to a Google bucket. Then, the tool could tell where the tarfile
blob is located.

SQLite
------
There is a record for every sequencing run, which is stored in the *tasks* table - the only table.
The possible fields are:

  * `name`: The name of the sequencing run.
  * `pid`: The process ID of the workflow that is running or that already ran.
  * `tarfile`: The path to the local tarfile that was generated by the tar task.
  * `gcp_tarfile`: The blob object path in the Google bucket, stored as *$bucket_name/$blob_name*.
  * `rundir_path`: The directory path of the original sequencing run. 

Firestore
---------
Firestore is optional. If your configuration file includes the `firestore_collection` setting, then
attempts to write to the designated Firestore collection will be made (creating it if needbe). 

There is a record in the collection for each sequencing run. The possible fields are:

  * `name`: The name of the sequencing run. This mirrors the value of the same attribute in the
    analagous SQLite database record.
  * `storage`: Bucket storage object path for the tarred run directory in the
    form $bucket_name/path/to/run.tar.gz
  * `workflow_status`: The overall status of the worklfow. Possible values are:

    * `new`
    * `starting`
    * `tarring`
    * `tarring_complete`
    * `uploading`
    * `uploading_complete`
    * `complete`
    * `not_running`

Installation and setup
======================
This works in later versions of Python 3 only::

  pip3 install sruns-monitor

It is recommended to start your compute instance (that will run the monitor) using a service account
with the following roles:

  * roles/storage.objectAdmin
  * roles/datastore.owner


Running Test Cases
==================
Each module has associated test cases. There are both unit tests and functional tests.

Unit Tests
----------
Run the following command from within the `tests` package directory::

  python3 -m unittest

There are two unit test modules:

  * test_sqlite_utils.py: Tests methods in the `sqlite_utils.Db` class. These tests make sure that
    the methods that interface with the local SQLite database function as expected.
  * test_utils.py: Tests general utility functions in `utils.py`, such as tarring a run directory,
    uploading an object to Google Storage, and checking child process state.


Functional Tests
-----------------
Running the functional tests are especially helpful in letting you know that your environment is 
set up correctly and that the monitor can access your Firestore database and Google bucket. 

The test module is named `monitor_integration_tests.py`. It is testing logic in 
the class `sruns_monitor.Monitor`. Because this class requires a configuration file in JSON format 
during instantiation, you must create such a file in order to run these tests. 
The file must be named as `conf.json` and must reside within the calling directory. 
The following config parameters should not be specified, however:

  * watchdir
  * completed_runs_dir
  * sqlite_db

That is because within the `tests` package directory, it includes its own watch directory with
mock run directories. The parameters you should provide in the conf.json file for testing are:

  * firestore_collection
  * gcp_bucket_name
  * gcp_bucket_basedir

Then, you run the tests like so::

  monitor_integration_tests.py

Note that you should be using a Google service account as described above. 
