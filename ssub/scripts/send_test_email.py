#!/usr/bin/env python3

"""
Send a test email using the mail configuration in the user-provided configuration file.
"""

import argparse

from ssub.subscriber import Poll


def get_parser():
    parser = argparse.ArgumentParser(formatter_class=argparse.RawTextHelpFormatter, description=__doc__)
    parser.add_argument("-c", "--conf-file", required=True, help="The JSON configuration file.")
    parser.add_argument("-p", "--project_id", help="""
        The Google Cloud Project ID that contains the Pub/Sub topic that this tool is subscribed too.
        If not provided, then it is expected that the environment variable GCP_PROJECT has been set.
    """)
    parser.add_argument("-s", "--subscription_name", required=True, help="The Pub/Sub subscription name")
    return parser

def main():
    parser = get_parser()
    args = parser.parse_args()
    conf_file = args.conf_file
    project_id = args.project_id
    subscription_name = args.subscription_name
    m = Poll(conf_file=conf_file, subscription_name=subscription_name, gcp_project_id=project_id)
    if not m.get_mail_params():
        # mail isn't configured in the conf file that the user provided
        raise Exception("You must provided mail configuration in your conf file.")
    m.send_mail(subject="ssub test email", body="test")

if __name__ == "__main__":
    main()



