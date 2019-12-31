#!/usr/bin/env python3

"""
python sruns_monitor/scripts/launch_samplesheet_subscriber.py  -p cloudfunctions-238722 -s sssub -c ~/smon_conf.json 
"""

import argparse

from sruns_monitor.samplesheet_subscriber import Poll


def get_parser():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("-c", "--conf-file", required=True, help="""
        Path to JSON configuration file.
    """)
    parser.add_argument("-p", "--project_id", required=True, help="""
        The Google Cloud Project ID that contains the Pub/Sub topic that this tool is subscribed too.
    """)
    parser.add_argument("-s", "--subscription_name", required=True, help="The Pub/Sub subscription name")
    return parser

def main():
    parser = get_parser()
    args = parser.parse_args()
    project_id = args.project_id
    subscription_name = args.subscription_name
    conf_file = args.conf_file
    poll = Poll(subscription_name=subscription_name, conf_file=conf_file)
    poll.start()


if __name__ == "__main__":
    main()



