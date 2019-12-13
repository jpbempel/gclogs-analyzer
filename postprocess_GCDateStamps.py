import sys
import bz2
import gzip
import re
import time
import datetime

def open_file(inputfile, mode):
    if inputfile.endswith('bz2'):
        return bz2.BZ2File(inputfile, mode)
    elif inputfile.endswith('gz'):
        return gzip.open(inputfile, mode)
    else:
        return open(inputfile, mode)

def process(gclog_file, postprocess_file):
    elapsed_time_re = re.compile('(^\[?(?P<ELAPSED>\d+\.\d{3}))')
    now = time.time()
    for line in gclog_file:
        match_line = elapsed_time_re.match(line)
        if match_line:
            elapsed = float(match_line.group('ELAPSED'))
            date_stamp = datetime.datetime.fromtimestamp(now+elapsed).strftime("%Y-%m-%dT%H:%M:%S.%f")
            date_stamp = date_stamp[:-3] + "+0100"
            if line.startswith('['):
                date_stamp = '[' + date_stamp + ']'
            else:
                date_stamp = date_stamp + ': '
            postprocess_file.write(date_stamp + line)
        else:
            postprocess_file.write(line)



gclog_filename = sys.argv[1]
postprocess_filename = sys.argv[2]
gclog_file = open_file(gclog_filename, "r")
try:
    postprocess_file = open(postprocess_filename, 'w')
    try:
        process(gclog_file, postprocess_file)
    finally:
        postprocess_file.close()
finally:
    gclog_file.close()