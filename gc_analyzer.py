import sys
import bz2
import gzip
import re
import math


def open_file(inputfile, mode):
    if inputfile.endswith('bz2'):
        return bz2.BZ2File(inputfile, mode)
    elif inputfile.endswith('gz'):
        return gzip.open(inputfile, mode)
    else:
        return open(inputfile, mode)

def parse(gclog_file, data_filename):

    def format_timestamp(match_timestamp, offset = 0):
        return 'Date.UTC({},{},{},{},{},{},{})+{}'.format(match_timestamp.group(1), int(match_timestamp.group(2))-1, match_timestamp.group(3),
                                                match_timestamp.group(4), match_timestamp.group(5), match_timestamp.group(6),
                                                match_timestamp.group(7), offset)

    def heap_occupancy_to_G(value_with_suffix):
        value = float(value_with_suffix[:-1])
        factor = 1
        if value_with_suffix.endswith('G'):
            factor = 1
        if value_with_suffix.endswith('M'):
            factor = 1024
        if value_with_suffix.endswith('K'):
            factor = 1024 * 1024
        return round(value / factor, 2)

    def heap_max_to_G(value_with_suffix):
        value = float(value_with_suffix[:-1])
        factor = 1
        if value_with_suffix.endswith('G'):
            factor = 1
        if value_with_suffix.endswith('M'):
            factor = 1024
        if value_with_suffix.endswith('K'):
            factor = 1024 * 1024
        return math.ceil(value / factor)

    def add_data(data, key, value):
        l = data.get(key)
        if not l:
            l = []
            data[key] = l
        l.append(value)

    def add_cpu_times(match_line, match_timestamp, data):
        def add_cpu_time(group_name, serie_name):
            cpu_time = round(float(match_line.group(group_name)) * 1000)
            add_data(data, serie_name, '[{},{}],\n'.format(format_timestamp(match_timestamp), cpu_time))

        add_cpu_time('USER', 'user')
        add_cpu_time('SYS', 'sys')
        add_cpu_time('REAL', 'real')

    def build_series(minorgc_str, fullgc_str, initialmark_str, finalremark_str, cleanup_str, mixed_str):
        series = ''
        if minorgc_str != '':
            series = series + '''
                {
                    name: 'minor GC',
        			tooltip: {
        				valueSuffix: 'ms'
        			},
                    data: data_serie_minorgc,
        			yAxis: 0
                }'''
        if mixed_str != '':
            if series != '':
                series = series + ', '
            series = series + '''
                {
                    name: 'mixed',
                    tooltip: {
                        valueSuffix: 'ms'
                    },
                    data: data_serie_mixed,
                    yAxis: 0
                }'''
        if initialmark_str != '':
            if series != '':
                series = series + ', '
            series = series + '''
                {
                    name: 'inital mark',
                    tooltip: {
                        valueSuffix: 'ms'
                    },
                    data: data_serie_initialmark,
                    yAxis: 0
                }'''
        if finalremark_str != '':
            if series != '':
                series = series + ', '
            series = series + '''
                {
                    name: 'final remark',
                    tooltip: {
                        valueSuffix: 'ms'
                    },
                    data: data_serie_finalremark,
                    yAxis: 0
                }'''
        if cleanup_str != '':
            if series != '':
                series = series + ', '
            series = series + '''
                {
                    name: 'cleanup',
                    tooltip: {
                        valueSuffix: 'ms'
                    },
                    data: data_serie_cleanup,
                    yAxis: 0
                }'''
        if fullgc_str != '':
            if series != '':
                series = series + ', '
            series = series + '''
                {
                    name: 'Full GC',
                    tooltip: {
                        valueSuffix: 's'
                    },
                    data: data_serie_fullgc,
                    yAxis: 1
                }'''
        return series

    pause_pattern = ', (?P<PAUSE>\d+\.\d+) secs\]'
    times_pattern = '\[Times: user=(?P<USER>\d+\.\d+) sys=(?P<SYS>\d+\.\d+), real=(?P<REAL>\d+\.\d+) secs\]'
    parallel_minorgc_re = re.compile('(?P<TIMESTAMP>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3})\+\d{4}: .*\[GC [^\[]+\[[^\]]+\] (?P<HEAP_BEFORE_GC>\d+)K->(?P<HEAP_AFTER_GC>\d+)K\((?P<HEAP_MAX>\d+)K\)' + pause_pattern + '.*' + times_pattern, re.DOTALL)
    parallel_fullgc_re = re.compile('(?P<TIMESTAMP>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3})\+\d{4}: .*\[Full GC [^\[]+\[[^\]]+\][^\[]+\[[^\]]+\] (?P<HEAP_BEFORE_GC>\d+)K->(?P<HEAP_AFTER_GC>\d+)K\((?P<HEAP_MAX>\d+)K\),.*' + pause_pattern + '.*' + times_pattern, re.DOTALL)
    CMS_initalmark_re = re.compile('(?P<TIMESTAMP>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3})\+\d{4}: .*\[GC \(CMS Initial Mark\) .*\[1 CMS-initial-mark: [^\]]+\] (?P<HEAP_BEFORE_GC>\d+)K\((?P<HEAP_MAX>\d+)K\)' + pause_pattern + '.*' + times_pattern, re.DOTALL)
    CMS_finalremark_re = re.compile('(?P<TIMESTAMP>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3})\+\d{4}: .*\[GC \(CMS Final Remark\) .*\[1 CMS-remark: [^\]]+\] (?P<HEAP_BEFORE_GC>\d+)K\((?P<HEAP_MAX>\d+)K\)' + pause_pattern + '.*' + times_pattern, re.DOTALL)
    CMS_fullgc_re = re.compile('(?P<TIMESTAMP>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3})\+\d{4}: .*\[CMS: [^\]]+\] (?P<HEAP_BEFORE_GC>\d+)K->(?P<HEAP_AFTER_GC>\d+)K\((?P<HEAP_MAX>\d+)K\), \[Metaspace: [^\]]+\]' + pause_pattern + '.*' + times_pattern, re.DOTALL)
    G1_heap_occupancy_pattern = 'Heap: (?P<HEAP_BEFORE_GC>\d+\.\d+[KMG])\(\d+\.\d+[KMG]\)->(?P<HEAP_AFTER_GC>\d+\.\d+[KMG])\((?P<HEAP_MAX>\d+\.\d+[KMG])\)'
    G1_minorgc_re = re.compile('(?P<TIMESTAMP>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3})\+\d{4}: .*\[GC pause .* \(young\).*' + pause_pattern + '.*' + G1_heap_occupancy_pattern + '.*' + times_pattern, re.DOTALL)
    G1_remark_re = re.compile('(?P<TIMESTAMP>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3})\+\d{4}: .*\[GC remark .*' + pause_pattern + '.*' + times_pattern, re.DOTALL)
    G1_cleanup_re = re.compile('(?P<TIMESTAMP>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3})\+\d{4}: .*\[GC cleanup (?P<HEAP_BEFORE_GC>\d+[KMG])->(?P<HEAP_AFTER_GC>\d+[KMG])\((?P<HEAP_MAX>\d+[KMG])\).*' + pause_pattern + '.*' + times_pattern, re.DOTALL)
    G1_mixed_re = re.compile('(?P<TIMESTAMP>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3})\+\d{4}: .*\[GC pause .* \(mixed\).*' + pause_pattern + '.*' + G1_heap_occupancy_pattern + '.*' + times_pattern, re.DOTALL)
    G1_fullgc_re = re.compile('(?P<TIMESTAMP>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3})\+\d{4}: .*\[Full GC \([^\)]+\).*' + pause_pattern + '.*' + G1_heap_occupancy_pattern + '.*' + times_pattern, re.DOTALL)
    timestamp_re = re.compile('(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})\.(\d{3})')
    timestamp_line_start_re = re.compile('\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}')

    def pattern_match_full_line(full_line, data):
        match_line = parallel_minorgc_re.match(full_line)
        if match_line:  # minor GC
            timestamp = match_line.group('TIMESTAMP')
            match_timestamp = timestamp_re.match(timestamp)
            if match_timestamp:
                add_data(data, 'heap_occupancy', '[{},{}],\n'.format(format_timestamp(match_timestamp), round(int(match_line.group('HEAP_BEFORE_GC'))/1048576, 2)))
                pause_ms = round(float(match_line.group('PAUSE')) * 1000)
                add_data(data, 'heap_occupancy', '[{},{}],\n'.format(format_timestamp(match_timestamp, pause_ms), round(int(match_line.group('HEAP_AFTER_GC'))/1048576, 2)))
                add_data(data, 'max_heap', '[{},{}],\n'.format(format_timestamp(match_timestamp), math.ceil(int(match_line.group('HEAP_MAX'))/1048576)))
                add_data(data, 'minorgc', '[{},{}],\n'.format(format_timestamp(match_timestamp), pause_ms))
                add_cpu_times(match_line, match_timestamp, data)
                return
        match_line = parallel_fullgc_re.match(full_line)
        if match_line:  # Full GC
            timestamp = match_line.group('TIMESTAMP')
            match_timestamp = timestamp_re.match(timestamp)
            if match_timestamp:
                add_data(data, 'heap_occupancy', '[{},{}],\n'.format(format_timestamp(match_timestamp), round(int(match_line.group('HEAP_BEFORE_GC'))/1048576, 2)))
                pause_sec = float(match_line.group('PAUSE'))
                pause_ms = round(pause_sec * 1000)
                add_data(data, 'heap_occupancy', '[{},{}],\n'.format(format_timestamp(match_timestamp, pause_ms), round(int(match_line.group('HEAP_AFTER_GC'))/1048576, 2)))
                add_data(data, 'max_heap', '[{},{}],\n'.format(format_timestamp(match_timestamp), math.ceil(int(match_line.group('HEAP_MAX'))/1048576)))
                add_data(data, 'fullgc', '[{},{}],\n'.format(format_timestamp(match_timestamp), round(pause_sec, 3)))
                add_cpu_times(match_line, match_timestamp, data)
                return
        match_line = CMS_initalmark_re.match(full_line)
        if match_line:  # CMS initial mark
            timestamp = match_line.group('TIMESTAMP')
            match_timestamp = timestamp_re.match(timestamp)
            if match_timestamp:
                add_data(data, 'heap_occupancy', '[{},{}],\n'.format(format_timestamp(match_timestamp), round(int(match_line.group('HEAP_BEFORE_GC'))/1048576, 2)))
                add_data(data, 'initialmark', '[{},{}],\n'.format(format_timestamp(match_timestamp), round(float(match_line.group('PAUSE'))*1000)))
                add_cpu_times(match_line, match_timestamp, data)
                return
        match_line = CMS_finalremark_re.match(full_line)
        if match_line:  # CMS final remark
            timestamp = match_line.group('TIMESTAMP')
            match_timestamp = timestamp_re.match(timestamp)
            if match_timestamp:
                add_data(data, 'heap_occupancy', '[{},{}],\n'.format(format_timestamp(match_timestamp), round(int(match_line.group('HEAP_BEFORE_GC'))/1048576, 2)))
                add_data(data, 'finalremark', '[{},{}],\n'.format(format_timestamp(match_timestamp), round(float(match_line.group('PAUSE'))*1000)))
                add_cpu_times(match_line, match_timestamp, data)
                return
        match_line = CMS_fullgc_re.match(full_line)
        if match_line:  # CMS Full GC
            timestamp = match_line.group('TIMESTAMP')
            match_timestamp = timestamp_re.match(timestamp)
            if match_timestamp:
                add_data(data, 'heap_occupancy', '[{},{}],\n'.format(format_timestamp(match_timestamp), round(int(match_line.group('HEAP_BEFORE_GC'))/1048576, 2)))
                add_data(data, 'heap_occupancy', '[{},{}],\n'.format(format_timestamp(match_timestamp), round(int(match_line.group('HEAP_AFTER_GC'))/1048576, 2)))
                add_data(data, 'max_heap', '[{},{}],\n'.format(format_timestamp(match_timestamp), math.ceil(int(match_line.group('HEAP_MAX')) / 1048576)))
                add_data(data, 'fullgc', '[{},{}],\n'.format(format_timestamp(match_timestamp), round(float(match_line.group('PAUSE')), 3)))
                add_cpu_times(match_line, match_timestamp, data)
                return
        match_line = G1_minorgc_re.match(full_line)
        if match_line:  # G1 minor gc
            timestamp = match_line.group('TIMESTAMP')
            match_timestamp = timestamp_re.match(timestamp)
            if match_timestamp:
                current_pause_ms = round(float(match_line.group('PAUSE')) * 1000)
                add_data(data, 'heap_occupancy', '[{},{}],\n'.format(format_timestamp(match_timestamp), heap_occupancy_to_G(match_line.group('HEAP_BEFORE_GC'))))
                add_data(data, 'heap_occupancy', '[{},{}],\n'.format(format_timestamp(match_timestamp, current_pause_ms), heap_occupancy_to_G(match_line.group('HEAP_AFTER_GC'))))
                add_data(data, 'max_heap', '[{},{}],\n'.format(format_timestamp(match_timestamp), heap_max_to_G(match_line.group('HEAP_MAX'))))
                if full_line.find('(initial-mark)') == -1:
                    key = 'minorgc'
                else:
                    key = 'initialmark'
                add_data(data, key, '[{},{}],\n'.format(format_timestamp(match_timestamp), current_pause_ms))
                add_cpu_times(match_line, match_timestamp, data)
                return
        match_line = G1_remark_re.match(full_line)
        if match_line:
            timestamp = match_line.group('TIMESTAMP')
            match_timestamp = timestamp_re.match(timestamp)
            if match_timestamp:
                current_pause_ms = round(float(match_line.group('PAUSE')) * 1000)
                add_data(data, 'finalremark', '[{},{}],\n'.format(format_timestamp(match_timestamp), current_pause_ms))
                add_cpu_times(match_line, match_timestamp, data)
                return
        match_line = G1_cleanup_re.match(full_line)
        if match_line:
            timestamp = match_line.group('TIMESTAMP')
            match_timestamp = timestamp_re.match(timestamp)
            if match_timestamp:
                current_pause_ms = round(float(match_line.group('PAUSE')) * 1000)
                add_data(data, 'heap_occupancy', '[{},{}],\n'.format(format_timestamp(match_timestamp), heap_occupancy_to_G(match_line.group('HEAP_BEFORE_GC'))))
                add_data(data, 'heap_occupancy', '[{},{}],\n'.format(format_timestamp(match_timestamp, current_pause_ms), heap_occupancy_to_G(match_line.group('HEAP_AFTER_GC'))))
                add_data(data, 'max_heap', '[{},{}],\n'.format(format_timestamp(match_timestamp), heap_max_to_G(match_line.group('HEAP_MAX'))))
                add_data(data, 'cleanup', '[{},{}],\n'.format(format_timestamp(match_timestamp), current_pause_ms))
                add_cpu_times(match_line, match_timestamp, data)
                return
        match_line = G1_mixed_re.match(full_line)
        if match_line:  # G1 mixed
            timestamp = match_line.group('TIMESTAMP')
            match_timestamp = timestamp_re.match(timestamp)
            if match_timestamp:
                current_pause_ms = round(float(match_line.group('PAUSE'))*1000)
                add_data(data, 'heap_occupancy', '[{},{}],\n'.format(format_timestamp(match_timestamp), heap_occupancy_to_G(match_line.group('HEAP_BEFORE_GC'))))
                add_data(data, 'heap_occupancy', '[{},{}],\n'.format(format_timestamp(match_timestamp, current_pause_ms), heap_occupancy_to_G(match_line.group('HEAP_AFTER_GC'))))
                add_data(data, 'max_heap', '[{},{}],\n'.format(format_timestamp(match_timestamp), heap_max_to_G(match_line.group('HEAP_MAX'))))
                add_data(data, 'mixed', '[{},{}],\n'.format(format_timestamp(match_timestamp), current_pause_ms))
                add_cpu_times(match_line, match_timestamp, data)
                return
        match_line = G1_fullgc_re.match(full_line)
        if match_line:
            timestamp = match_line.group('TIMESTAMP')
            match_timestamp = timestamp_re.match(timestamp)
            if match_timestamp:
                pause_sec = float(match_line.group('PAUSE'))
                current_pause_ms = round(pause_sec * 1000)
                add_data(data, 'heap_occupancy', '[{},{}],\n'.format(format_timestamp(match_timestamp), heap_occupancy_to_G(match_line.group('HEAP_BEFORE_GC'))))
                add_data(data, 'heap_occupancy', '[{},{}],\n'.format(format_timestamp(match_timestamp, current_pause_ms), heap_occupancy_to_G(match_line.group('HEAP_AFTER_GC'))))
                add_data(data, 'max_heap', '[{},{}],\n'.format(format_timestamp(match_timestamp), heap_max_to_G(match_line.group('HEAP_MAX'))))
                add_data(data, 'fullgc', '[{},{}],\n'.format(format_timestamp(match_timestamp), round(pause_sec, 3)))
                add_cpu_times(match_line, match_timestamp, data)
                return

    full_line = ''
    data = {}
    for line in gclog_file:
        if timestamp_line_start_re.match(line):
            if line.find('[SoftReference,') == -1:
                if full_line != '':  # process the full previous line
                    pattern_match_full_line(full_line, data)
                full_line = line  # reset to a new line
            else:  # PrintReferenceGC => partial line => concat with previous lines
                full_line += line
        else:  # partial line => concat with previous lines
            full_line += line

    data_file = open(data_filename, 'w')
    try:
        data_file.write('var data_serie_heap = [{}]\n'.format(''.join(data.get('heap_occupancy', []))))
        data_file.write('var data_serie_heapmax = [{}]\n'.format(''.join(data.get('max_heap', []))))
        data_file.write('var data_serie_minorgc = [{}]\n'.format(''.join(data.get('minorgc', []))))
        data_file.write('var data_serie_fullgc = [{}]\n'.format(''.join(data.get('fullgc', []))))
        data_file.write('var data_serie_initialmark = [{}]\n'.format(''.join(data.get('initialmark', []))))
        data_file.write('var data_serie_finalremark = [{}]\n'.format(''.join(data.get('finalremark', []))))
        data_file.write('var data_serie_cleanup = [{}]\n'.format(''.join(data.get('cleanup', []))))
        data_file.write('var data_serie_mixed = [{}]\n'.format(''.join(data.get('mixed', []))))
        data_file.write('var data_serie_user = [{}]\n'.format(''.join(data.get('user', []))))
        data_file.write('var data_serie_sys = [{}]\n'.format(''.join(data.get('sys', []))))
        data_file.write('var data_serie_real = [{}]\n'.format(''.join(data.get('real', []))))
        series = build_series(''.join(data.get('minorgc', [])), ''.join(data.get('fullgc', [])), ''.join(data.get('initialmark', [])),
                             ''.join(data.get('finalremark', [])), ''.join(data.get('cleanup', [])), ''.join(data.get('mixed', [])))
        data_file.write('var series = [{}]\n'.format(series))
    finally:
        data_file.close()


gclog_filename = sys.argv[1]
data_filename = sys.argv[2]
gclog_file = open_file(gclog_filename, "r")
try:
    parse(gclog_file, data_filename)
finally:
    gclog_file.close()