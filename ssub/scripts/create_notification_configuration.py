#!/usr/bin/env python3

"""
Creates a notification configuration on a bucket for a Pub/Sub topic. It's an alternative to using
`gsutil notification create`, which is not easy to use since permissions are difficult to set up properly,
resulting in access denied errors. 

GCP documentation at https://googleapis.dev/python/storage/latest/notification.html?highlight=notification%20configuration.
"""

import argparse

from google.cloud.storage.notification import BucketNotification
from google.cloud import storage


def get_parser():
    parser = argparse.ArgumentParser(formatter_class=argparse.RawTextHelpFormatter, description=__doc__)
    parser.add_argument("-b", "--bucket", required=True, help="The name of the bucket")
    parser.add_argument("-t", "--topic", required=True, help="The name of the Pub/Sub topic")
    parser.add_argument("-p", "--project_id", help="The Google Cloud Project ID that contains the Pub/Sub topic that this tool is subscribed too.")
    parser.add_argument("-s", "--subscription_name", required=True, help="The Pub/Sub subscription name")
    return parser

def main():
    parser = get_parser()
    args = parser.parse_args()
    bucket_name = args.bucket_name
    topic = args.topic
    project_id = args.project_id

    storage_client = storage.Client()
    bucket = storage_client.get_bucket(bucket_name)

    bn = BucketNotification(
        bucket=bucket,
        topic_name=topic,
        topic_project=project_id,
        event_types=["OBJECT_FINALIZE"],
        payload_format="JSON_API_V1"
    )
    bn.create()

if __name__ == "__main__":
    main()
