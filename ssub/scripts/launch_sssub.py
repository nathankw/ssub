#!/usr/bin/env python3

"""
Polls a GCP Pub/Sub topic for new SampleSheet notification messages in order to initiate bcl2fastq.

python ~/repos/ssub/ssub/scripts/launch_ssub.py -s ssub -c ~/repos/ssub/conf_example.json -p cloudfunctions-238722
"""

import argparse

from ssub.subscriber import Poll


def get_parser():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("-c", "--conf-file", required=True, help="""
        Path to JSON configuration file.
    """)
    parser.add_argument("-d", "--demuxtest", action="store_true", help="True means to demultiplex only a single tile - handy when developing/testing.")
    parser.add_argument("-p", "--project_id", help="""
        The Google Cloud Project ID that contains the Pub/Sub topic that this tool is subscribed too.
        If not provided, then it is expected that the environment variable GCP_PROJECT has been set.
    """)
    parser.add_argument("-s", "--subscription_name", required=True, help="The Pub/Sub subscription name")
    return parser

def main():
    parser = get_parser()
    args = parser.parse_args()
    demuxtest = args.demuxtest
    project_id = args.project_id
    subscription_name = args.subscription_name
    conf_file = args.conf_file
    poll = Poll(subscription_name=subscription_name, conf_file=conf_file, gcp_project_id=project_id, demuxtest=demuxtest)
    poll.start()


if __name__ == "__main__":
    main()



