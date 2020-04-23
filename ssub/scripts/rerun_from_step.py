#!/usr/bin/env python3

"""
Reruns a failed run either at the bcl2fastq stage or the upload to GCP storage stage.
"""

import argparse

from ssub.subscriber import Poll


def get_parser():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("-a", "--analysis-base-dir", help="The top-level directory path in which all analysis will take place. If not specified, it will default to a subdirectory within the calling directory whose name is equal to `Poll.DEFAULT_ANALYSIS_DIR`. Will be created if it does not exist.")
    parser.add_argument("-c", "--conf-file", required=True, help="""
        Path to JSON configuration file.
    """)
    parser.add_argument("-d", "--demuxtest", action="store_true", help="True means to demultiplex only a single tile - handy when developing/testing.")
    parser.add_argument("-r", "--run-name", required=True, help="The name of the sequencing run.")
    parser.add_argument("--restart-from", required=True, help=f"Must be one of the constants defined in `Workflow.RESTART_FROM_CHOICES`: {Workflow.RESTART_FROM_CHOICES}.")
    return parser

def main():
    parser = get_parser()
    args = parser.parse_args()
    analysis_base_dir = args.analysis_base_dir
    restart_from = args.restart_from
    run_name = args.run_name
    demuxtest = args.demuxtest
    conf_file = args.conf_file
    wf = Workflow(analysis_base_dir=analysis_base_dir, conf_file=conf_file, demuxtest=demuxtest, run_name=run_name, restart_from=restart_from)
    wf.run()


if __name__ == "__main__":
    main()



