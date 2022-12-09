import sys
import argparse

arg_parser = argparse.ArgumentParser()
arg_parser.add_argument('-s', '--stats', required=False, help="only stats mode")
arg_parser.add_argument('gclog_file')
try:
    args = arg_parser.parse_args()
except argparse.ArgumentError, e:
    import traceback

    exc_type, exc_value, exc_traceback = sys.exc_info()
    print >> sys.stderr, "Error while parsing arguments", sys.argv
    traceback.print_exception(exc_type, exc_value, exc_traceback, limit=10, file=sys.stderr)
    arg_parser.print_usage()
    sys.exit(1)
