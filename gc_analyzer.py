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

# GC type
PARALLEL_GC = 0
CMS_GC = 1
G1_GC = 2
SHENANDOAH_GC = 3

# Log format
JDK8_FORMAT = 0
JDK9_FORMAT = 1

def parse(gclog_file, data_filename):

    def detect_gc_type(line):
        if sys.argv[1] == "--gc=Parallel":
            return PARALLEL_GC
        if sys.argv[1] == "--gc=CMS":
            return CMS_GC
        if sys.argv[1] == "--gc=G1":
            return G1_GC
        if sys.argv[1] == "--gc=Shenandoah":
            return SHENANDOAH_GC
        idx = line.find('[PSYoungGen')
        if  idx != -1:
            print("Detected Parallel GC with line: " + line[:idx+len('[PSYoungGen')])
            return PARALLEL_GC
        idx = line.find('[ParNew')
        if idx != -1:
            print("Detected CMS GC with line: " + line[:idx+len('[ParNew')])
            return CMS_GC
        idx = line.find('G1 Evacuation Pause')
        if idx != -1:
            print("Detected G1 GC with line: " + line[:idx+len('G1 Evacuation Pause')])
            return G1_GC
        idx = line.find('[Pause ')
        if idx == -1:
            idx = line.find('Using Shenandoah')
        if idx != -1:
            print("Detected Shenandoah GC with line: " + line[:idx+len('Using Shenandoah')])
            return SHENANDOAH_GC
        return None

    def detect_log_format(line):
        jdk9_datetime_re = re.compile('^\[\d{4}-\d{2}-\d{2}T')
        if jdk9_datetime_re.match(line):
            print("Format: JDK9+")
            return JDK9_FORMAT
        jdk8_datetime_re = re.compile('^\d{4}-\d{2}-\d{2}T')
        if jdk8_datetime_re.match(line):
            print("Format: JDK8")
            return JDK8_FORMAT
        return None

    def create_parser(gc_type, log_format):
        if gc_type == PARALLEL_GC:
            return ParallelGCParser(log_format)
        if gc_type == CMS_GC:
            return CMSGCLineParser(log_format)
        if gc_type == G1_GC:
            return G1GCLineParser(log_format)
        if gc_type == SHENANDOAH_GC:
            return ShenandoahGCLineParser(log_format)
        return None

    timestamp_line_start_re = re.compile('(\d{4}|\[\d{4})-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3}')
    full_line = ''
    gc_type = None
    log_format = None
    parser = None
    for line in gclog_file:
        if timestamp_line_start_re.match(line):
            if line.find('[SoftReference,') == -1:
                if full_line != '':  # process the full previous line
                    if gc_type is None:
                        gc_type = detect_gc_type(full_line)
                    if log_format is None:
                        log_format = detect_log_format(full_line)
                    if parser is None:
                        parser = create_parser(gc_type, log_format)
                    if parser is not None:
                        parser.parse_line(full_line)
                        if parser.event_count > 10000:
                            print("[WARNING] more than 10K points")
                            parser.event_count = 0
                full_line = line  # reset to a new line
            else:  # PrintReferenceGC => partial line => concat with previous lines
                full_line += line
        else:  # partial line => concat with previous lines
            full_line += line

    if parser is None:
        print("ERROR: Cannot recognize file format!")
        return

    data_file = open(data_filename, 'w')
    try:
        parser.write(data_file)
        series = parser.build_series()
        data_file.write('var series = [{}]\n'.format(series))
    finally:
        data_file.close()


SERIE_MS_FORMAT = '''
        {{
            name: '{}',
            tooltip: {{
                valueSuffix: 'ms'
            }},
            data: data_serie_{},
            yAxis: 0
        }}'''

SERIE_S_FORMAT = '''
        {{
            name: '{}',
            tooltip: {{
                valueSuffix: 's'
            }},
            data: data_serie_{},
            yAxis: 1
        }}'''

class GCLineParser:

    def __init__(self, log_format):
        self.log_format = log_format
        self.pause_pattern = ', (?P<PAUSE>\d+\.\d+) secs\]'
        self.jdk9_pause_pattern = '(?P<PAUSE>\d+\.\d+)ms'
        self.times_pattern = '\[Times: user=(?P<USER>\d+\.\d+) sys=(?P<SYS>\d+\.\d+), real=(?P<REAL>\d+\.\d+) secs\]'
        self.timestamp_re = re.compile('(\d{4})-(\d{2})-(\d{2})T(\d{2}):(\d{2}):(\d{2})\.(\d{3})')
        self.data = {}
        self.event_count = 0

    @staticmethod
    def format_timestamp(match_timestamp, offset=0):
        return 'Date.UTC({},{},{},{},{},{},{})+{}'.format(match_timestamp.group(1), int(match_timestamp.group(2))-1, match_timestamp.group(3),
                                                match_timestamp.group(4), match_timestamp.group(5), match_timestamp.group(6),
                                                match_timestamp.group(7), offset)

    @staticmethod
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

    @staticmethod
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

    def add_cpu_times(self, match_line, match_timestamp):
        def add_cpu_time(group_name, serie_name):
            cpu_time = round(float(match_line.group(group_name)) * 1000)
            self.add_data(serie_name, '[{},{}],\n'.format(GCLineParser.format_timestamp(match_timestamp), cpu_time))

        add_cpu_time('USER', 'user')
        add_cpu_time('SYS', 'sys')
        add_cpu_time('REAL', 'real')

    def add_data(self, key, value):
        value_list = self.data.get(key)
        if not value_list:
            value_list = []
            self.data[key] = value_list
        value_list.append(value)

    def format_data_serie(self, var_format, data_name):
        return var_format.format(''.join(self.data.get(data_name, [])))

    def write(self, data_file):
        data_file.write(self.format_data_serie('var data_serie_heap = [{}]\n', 'heap_occupancy'))
        data_file.write(self.format_data_serie('var data_serie_heapmax = [{}]\n', 'max_heap'))
        data_file.write(self.format_data_serie('var data_serie_minorgc = [{}]\n', 'minorgc'))
        data_file.write(self.format_data_serie('var data_serie_fullgc = [{}]\n', 'fullgc'))
        # Times
        data_file.write(self.format_data_serie('var data_serie_user = [{}]\n', 'user'))
        data_file.write(self.format_data_serie('var data_serie_sys = [{}]\n', 'sys'))
        data_file.write(self.format_data_serie('var data_serie_real = [{}]\n', 'real'))


class ParallelGCParser(GCLineParser):

    def __init__(self, log_format):
        super(ParallelGCParser, self).__init__(log_format)
        if log_format == JDK8_FORMAT:
            self.parallel_minorgc_re = re.compile('(?P<TIMESTAMP>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3})\+\d{4}: .*\[GC [^\[]+\[[^\]]+\] (?P<HEAP_BEFORE_GC>\d+)K->(?P<HEAP_AFTER_GC>\d+)K\((?P<HEAP_MAX>\d+)K\)' + self.pause_pattern + '.*' + self.times_pattern, re.DOTALL)
            self.parallel_fullgc_re = re.compile('(?P<TIMESTAMP>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3})\+\d{4}: .*\[Full GC [^\[]+\[[^\]]+\][^\[]+\[[^\]]+\] (?P<HEAP_BEFORE_GC>\d+)K->(?P<HEAP_AFTER_GC>\d+)K\((?P<HEAP_MAX>\d+)K\),.*' + self.pause_pattern + '.*' + self.times_pattern, re.DOTALL)
        else:
            self.parallel_heap_occupancy_pattern = ' (?P<HEAP_BEFORE_GC>\d+[KMG])->(?P<HEAP_AFTER_GC>\d+[KMG])\((?P<HEAP_MAX>\d+[KMG])\)'
            self.parallel_minorgc_re = re.compile('\[(?P<TIMESTAMP>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3})\+\d{4}\].*GC\(\d+\) Pause Young .*' + self.parallel_heap_occupancy_pattern + ' ' + self.jdk9_pause_pattern)
            self.parallel_fullgc_re = re.compile('\[(?P<TIMESTAMP>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3})\+\d{4}\].*GC\(\d+\) Pause Full .*' + self.parallel_heap_occupancy_pattern + ' ' + self.jdk9_pause_pattern)

    def parse_line(self, full_line):
        if self.log_format == JDK8_FORMAT:
            self.jdk8_parse_line(full_line)
        else:
            self.jdk9_parse_line(full_line)

    def jdk8_parse_line(self, full_line):
        match_line = self.parallel_minorgc_re.match(full_line)
        if match_line:  # minor GC
            timestamp = match_line.group('TIMESTAMP')
            match_timestamp = self.timestamp_re.match(timestamp)
            if match_timestamp:
                self.add_data('heap_occupancy', '[{},{}],\n'.format(GCLineParser.format_timestamp(match_timestamp), round(int(match_line.group('HEAP_BEFORE_GC'))/1048576, 2)))
                pause_ms = round(float(match_line.group('PAUSE')) * 1000)
                self.add_data('heap_occupancy', '[{},{}],\n'.format(GCLineParser.format_timestamp(match_timestamp, pause_ms), round(int(match_line.group('HEAP_AFTER_GC'))/1048576, 2)))
                self.add_data('max_heap', '[{},{}],\n'.format(GCLineParser.format_timestamp(match_timestamp), round(int(match_line.group('HEAP_MAX'))/1048576, 2)))
                self.add_data('minorgc', '[{},{}],\n'.format(GCLineParser.format_timestamp(match_timestamp), pause_ms))
                self.add_cpu_times(match_line, match_timestamp)
                self.event_count += 1
                return
        match_line = self.parallel_fullgc_re.match(full_line)
        if match_line:  # Full GC
            timestamp = match_line.group('TIMESTAMP')
            match_timestamp = self.timestamp_re.match(timestamp)
            if match_timestamp:
                self.add_data('heap_occupancy', '[{},{}],\n'.format(GCLineParser.format_timestamp(match_timestamp), round(int(match_line.group('HEAP_BEFORE_GC'))/1048576, 2)))
                pause_sec = float(match_line.group('PAUSE'))
                pause_ms = round(pause_sec * 1000)
                self.add_data('heap_occupancy', '[{},{}],\n'.format(GCLineParser.format_timestamp(match_timestamp, pause_ms), round(int(match_line.group('HEAP_AFTER_GC'))/1048576, 2)))
                self.add_data('max_heap', '[{},{}],\n'.format(GCLineParser.format_timestamp(match_timestamp), round(int(match_line.group('HEAP_MAX'))/1048576, 2)))
                self.add_data('fullgc', '[{},{}],\n'.format(GCLineParser.format_timestamp(match_timestamp), round(pause_sec, 3)))
                self.add_cpu_times(match_line, match_timestamp)
                self.event_count += 1
                return

    def jdk9_parse_line(self, full_line):
        match_line = self.parallel_minorgc_re.match(full_line)
        if match_line:
            timestamp = match_line.group('TIMESTAMP')
            match_timestamp = self.timestamp_re.match(timestamp)
            if match_timestamp:
                current_pause_ms = round(float(match_line.group('PAUSE')))
                before_gc = match_line.group('HEAP_BEFORE_GC')
                after_gc = match_line.group('HEAP_AFTER_GC')
                self.add_data('heap_occupancy', '[{},{}],\n'.format(GCLineParser.format_timestamp(match_timestamp),
                                                                    GCLineParser.heap_occupancy_to_G(before_gc)))
                self.add_data('heap_occupancy', '[{},{}],\n'.format(GCLineParser.format_timestamp(match_timestamp, current_pause_ms),
                                                                    GCLineParser.heap_occupancy_to_G(after_gc)))
                self.add_data('max_heap', '[{},{}],\n'.format(GCLineParser.format_timestamp(match_timestamp),
                                                               GCLineParser.heap_max_to_G(match_line.group('HEAP_MAX'))))
                self.add_data('minorgc', '[{},{}],\n'.format(GCLineParser.format_timestamp(match_timestamp), current_pause_ms))
                self.event_count += 1
                return
        match_line = self.parallel_fullgc_re.match(full_line)
        if match_line:
            timestamp = match_line.group('TIMESTAMP')
            match_timestamp = self.timestamp_re.match(timestamp)
            if match_timestamp:
                current_pause_ms = round(float(match_line.group('PAUSE')))
                before_gc = match_line.group('HEAP_BEFORE_GC')
                after_gc = match_line.group('HEAP_AFTER_GC')
                self.add_data('heap_occupancy', '[{},{}],\n'.format(GCLineParser.format_timestamp(match_timestamp),
                                                                    GCLineParser.heap_occupancy_to_G(before_gc)))
                self.add_data('heap_occupancy', '[{},{}],\n'.format(GCLineParser.format_timestamp(match_timestamp, current_pause_ms),
                                                                    GCLineParser.heap_occupancy_to_G(after_gc)))
                self.add_data('max_heap', '[{},{}],\n'.format(GCLineParser.format_timestamp(match_timestamp),
                                                               GCLineParser.heap_max_to_G(match_line.group('HEAP_MAX'))))
                self.add_data('fullgc', '[{},{}],\n'.format(GCLineParser.format_timestamp(match_timestamp), round(current_pause_ms / 1000, 3)))
                self.event_count += 1
                return



    def build_series(self):
        series = ''
        minorgc_str = ''.join(self.data.get('minorgc', []))
        if minorgc_str != '':
            series = series + SERIE_MS_FORMAT.format('minor GC', 'minorgc')
        fullgc_str = ''.join(self.data.get('fullgc', []))
        if fullgc_str != '':
            if series != '':
                series = series + ', '
            series = series + SERIE_S_FORMAT.format('Full GC', 'fullgc')
        return series



class G1GCLineParser(GCLineParser):

    def __init__(self, log_format):
        super(G1GCLineParser, self).__init__(log_format)
        if log_format == JDK8_FORMAT:
            self.G1_heap_occupancy_pattern = 'Heap: (?P<HEAP_BEFORE_GC>\d+\.\d+[KMG])\(\d+\.\d+[KMG]\)->(?P<HEAP_AFTER_GC>\d+\.\d+[KMG])\((?P<HEAP_MAX>\d+\.\d+[KMG])\)'
            self.G1_minorgc_re = re.compile('(?P<TIMESTAMP>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3})\+\d{4}: .*\[GC pause .* \(young\).*' + self.pause_pattern + '.*' + self.G1_heap_occupancy_pattern + '.*' + self.times_pattern, re.DOTALL)
            self.G1_remark_re = re.compile('(?P<TIMESTAMP>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3})\+\d{4}: .*\[GC remark .*' + self.pause_pattern + '.*' + self.times_pattern, re.DOTALL)
            self.G1_cleanup_re = re.compile('(?P<TIMESTAMP>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3})\+\d{4}: .*\[GC cleanup (?P<HEAP_BEFORE_GC>\d+[KMG])->(?P<HEAP_AFTER_GC>\d+[KMG])\((?P<HEAP_MAX>\d+[KMG])\).*' + self.pause_pattern + '.*' + self.times_pattern, re.DOTALL)
            self.G1_mixed_re = re.compile('(?P<TIMESTAMP>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3})\+\d{4}: .*\[GC pause .* \(mixed\).*' + self.pause_pattern + '.*' + self.G1_heap_occupancy_pattern + '.*' + self.times_pattern, re.DOTALL)
            self.G1_fullgc_re = re.compile('(?P<TIMESTAMP>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3})\+\d{4}: .*\[Full GC \([^\)]+\).*' + self.pause_pattern + '.*' + self.G1_heap_occupancy_pattern + '.*' + self.times_pattern, re.DOTALL)
        else:
            self.G1_heap_occupancy_pattern = ' (?P<HEAP_BEFORE_GC>\d+[KMG])->(?P<HEAP_AFTER_GC>\d+[KMG])\((?P<HEAP_MAX>\d+[KMG])\)'
            self.G1_pause_young_re = re.compile('\[(?P<TIMESTAMP>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3})\+\d{4}\].*GC\(\d+\) Pause Young .*' + self.G1_heap_occupancy_pattern + ' ' + self.jdk9_pause_pattern)
            self.G1_remark_re = re.compile('\[(?P<TIMESTAMP>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3})\+\d{4}\].*GC\(\d+\) Pause Remark ' + self.G1_heap_occupancy_pattern + ' ' + self.jdk9_pause_pattern)
            self.G1_times_re = re.compile('\[(?P<TIMESTAMP>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3})\+\d{4}\].*GC\(\d+\) User=(?P<USER>\d+\.\d+)s Sys=(?P<SYS>\d+\.\d+)s Real=(?P<REAL>\d+\.\d+)s')

    def parse_line(self, full_line):
        if self.log_format == JDK8_FORMAT:
            self.jdk8_parse_line(full_line)
        else:
            self.jdk9_parse_line(full_line)

    def jdk8_parse_line(self, full_line):
        match_line = self.G1_minorgc_re.match(full_line)
        if match_line:  # G1 minor gc
            timestamp = match_line.group('TIMESTAMP')
            match_timestamp = self.timestamp_re.match(timestamp)
            if match_timestamp:
                current_pause_ms = round(float(match_line.group('PAUSE')) * 1000)
                self.add_data('heap_occupancy', '[{},{}],\n'.format(GCLineParser.format_timestamp(match_timestamp), GCLineParser.heap_occupancy_to_G(
                    match_line.group('HEAP_BEFORE_GC'))))
                self.add_data('heap_occupancy', '[{},{}],\n'.format(GCLineParser.format_timestamp(match_timestamp, current_pause_ms),
                                                                    GCLineParser.heap_occupancy_to_G(
                                                                         match_line.group('HEAP_AFTER_GC'))))
                self.add_data('max_heap', '[{},{}],\n'.format(GCLineParser.format_timestamp(match_timestamp),
                                                               GCLineParser.heap_max_to_G(match_line.group('HEAP_MAX'))))
                if full_line.find('(initial-mark)') == -1:
                    key = 'minorgc'
                else:
                    key = 'initialmark'
                self.add_data(key, '[{},{}],\n'.format(GCLineParser.format_timestamp(match_timestamp), current_pause_ms))
                self.add_cpu_times(match_line, match_timestamp)
                self.event_count += 1
                return
        match_line = self.G1_remark_re.match(full_line)
        if match_line:
            timestamp = match_line.group('TIMESTAMP')
            match_timestamp = self.timestamp_re.match(timestamp)
            if match_timestamp:
                current_pause_ms = round(float(match_line.group('PAUSE')) * 1000)
                self.add_data('finalremark', '[{},{}],\n'.format(GCLineParser.format_timestamp(match_timestamp), current_pause_ms))
                self.add_cpu_times(match_line, match_timestamp)
                self.event_count += 1
                return
        match_line = self.G1_cleanup_re.match(full_line)
        if match_line:
            timestamp = match_line.group('TIMESTAMP')
            match_timestamp = self.timestamp_re.match(timestamp)
            if match_timestamp:
                current_pause_ms = round(float(match_line.group('PAUSE')) * 1000)
                self.add_data('heap_occupancy', '[{},{}],\n'.format(GCLineParser.format_timestamp(match_timestamp), GCLineParser.heap_occupancy_to_G(
                    match_line.group('HEAP_BEFORE_GC'))))
                self.add_data('heap_occupancy', '[{},{}],\n'.format(GCLineParser.format_timestamp(match_timestamp, current_pause_ms),
                                                                     GCLineParser.heap_occupancy_to_G(
                                                                         match_line.group('HEAP_AFTER_GC'))))
                self.add_data('max_heap', '[{},{}],\n'.format(GCLineParser.format_timestamp(match_timestamp),
                                                               GCLineParser.heap_max_to_G(match_line.group('HEAP_MAX'))))
                self.add_data('cleanup', '[{},{}],\n'.format(GCLineParser.format_timestamp(match_timestamp), current_pause_ms))
                self.add_cpu_times(match_line, match_timestamp)
                self.event_count += 1
                return
        match_line = self.G1_mixed_re.match(full_line)
        if match_line:  # G1 mixed
            timestamp = match_line.group('TIMESTAMP')
            match_timestamp = self.timestamp_re.match(timestamp)
            if match_timestamp:
                current_pause_ms = round(float(match_line.group('PAUSE')) * 1000)
                self.add_data('heap_occupancy', '[{},{}],\n'.format(GCLineParser.format_timestamp(match_timestamp), GCLineParser.heap_occupancy_to_G(
                    match_line.group('HEAP_BEFORE_GC'))))
                self.add_data('heap_occupancy', '[{},{}],\n'.format(GCLineParser.format_timestamp(match_timestamp, current_pause_ms),
                                                                     GCLineParser.heap_occupancy_to_G(
                                                                         match_line.group('HEAP_AFTER_GC'))))
                self.add_data('max_heap', '[{},{}],\n'.format(GCLineParser.format_timestamp(match_timestamp),
                                                               GCLineParser.heap_max_to_G(match_line.group('HEAP_MAX'))))
                self.add_data('mixed', '[{},{}],\n'.format(GCLineParser.format_timestamp(match_timestamp), current_pause_ms))
                self.add_cpu_times(match_line, match_timestamp)
                self.event_count += 1
                return
        match_line = self.G1_fullgc_re.match(full_line)
        if match_line:
            timestamp = match_line.group('TIMESTAMP')
            match_timestamp = self.timestamp_re.match(timestamp)
            if match_timestamp:
                pause_sec = float(match_line.group('PAUSE'))
                current_pause_ms = round(pause_sec * 1000)
                self.add_data('heap_occupancy', '[{},{}],\n'.format(GCLineParser.format_timestamp(match_timestamp), GCLineParser.heap_occupancy_to_G(
                    match_line.group('HEAP_BEFORE_GC'))))
                self.add_data('heap_occupancy', '[{},{}],\n'.format(GCLineParser.format_timestamp(match_timestamp, current_pause_ms),
                                                                     GCLineParser.heap_occupancy_to_G(
                                                                         match_line.group('HEAP_AFTER_GC'))))
                self.add_data('max_heap', '[{},{}],\n'.format(GCLineParser.format_timestamp(match_timestamp),
                                                               GCLineParser.heap_max_to_G(match_line.group('HEAP_MAX'))))
                self.add_data('fullgc', '[{},{}],\n'.format(GCLineParser.format_timestamp(match_timestamp), round(pause_sec, 3)))
                self.add_cpu_times(match_line, match_timestamp)
                self.event_count += 1
                return

    def jdk9_parse_line(self, full_line):
        match_line = self.G1_pause_young_re.match(full_line)
        if match_line:
            timestamp = match_line.group('TIMESTAMP')
            match_timestamp = self.timestamp_re.match(timestamp)
            if match_timestamp:
                current_pause_ms = round(float(match_line.group('PAUSE')))
                before_gc = match_line.group('HEAP_BEFORE_GC')
                self.add_data('heap_occupancy', '[{},{}],\n'.format(GCLineParser.format_timestamp(match_timestamp), GCLineParser.heap_occupancy_to_G(
                    before_gc)))
                self.add_data('heap_occupancy', '[{},{}],\n'.format(GCLineParser.format_timestamp(match_timestamp, current_pause_ms),
                                                                    GCLineParser.heap_occupancy_to_G(
                                                                         match_line.group('HEAP_AFTER_GC'))))
                self.add_data('max_heap', '[{},{}],\n'.format(GCLineParser.format_timestamp(match_timestamp),
                                                               GCLineParser.heap_max_to_G(match_line.group('HEAP_MAX'))))
                if full_line.find('(Concurrent Start)') != -1:
                    key = 'initialmark'
                elif full_line.find('(Normal)') != -1:
                    key = 'minorgc'
                elif full_line.find('(Prepare Mixed)') != -1: # == cleanup
                    key = 'cleanup'
                elif full_line.find('(Mixed)') != -1:
                    key = 'mixed'
                else:
                    key = 'unknown'
                self.add_data(key, '[{},{}],\n'.format(GCLineParser.format_timestamp(match_timestamp), current_pause_ms))
                self.event_count += 1
                return
        match_line = self.G1_remark_re.match(full_line)
        if match_line:
            timestamp = match_line.group('TIMESTAMP')
            match_timestamp = self.timestamp_re.match(timestamp)
            if match_timestamp:
                current_pause_ms = round(float(match_line.group('PAUSE')))
                self.add_data('finalremark',
                              '[{},{}],\n'.format(GCLineParser.format_timestamp(match_timestamp), current_pause_ms))
                self.event_count += 1
                return
        match_line = self.G1_times_re.match(full_line)
        if match_line:
            timestamp = match_line.group('TIMESTAMP')
            match_timestamp = self.timestamp_re.match(timestamp)
            if match_timestamp:
                self.add_cpu_times(match_line, match_timestamp)
                return

    def write(self, data_file):
        super(G1GCLineParser, self).write(data_file)
        # CMS/G1
        data_file.write(self.format_data_serie('var data_serie_initialmark = [{}]\n', 'initialmark'))
        data_file.write(self.format_data_serie('var data_serie_finalremark = [{}]\n', 'finalremark'))
        # G1
        data_file.write(self.format_data_serie('var data_serie_cleanup = [{}]\n', 'cleanup'))
        data_file.write(self.format_data_serie('var data_serie_mixed = [{}]\n', 'mixed'))

    def build_series(self):
        series = ''
        minorgc_str = ''.join(self.data.get('minorgc', []))
        if minorgc_str != '':
            series = series + SERIE_MS_FORMAT.format('minor GC', 'minorgc')
        mixed_str = ''.join(self.data.get('mixed', []))
        if mixed_str != '':
            if series != '':
                series = series + ', '
            series = series + SERIE_MS_FORMAT.format('mixed', 'mixed')
        initialmark_str = ''.join(self.data.get('initialmark', []))
        if initialmark_str != '':
            if series != '':
                series = series + ', '
            series = series + SERIE_MS_FORMAT.format('initial mark', 'initialmark')
        finalremark_str = ''.join(self.data.get('finalremark', []))
        if finalremark_str != '':
            if series != '':
                series = series + ', '
            series = series + SERIE_MS_FORMAT.format('final remark', 'finalremark')
        cleanup_str = ''.join(self.data.get('cleanup', []))
        if cleanup_str != '':
            if series != '':
                series = series + ', '
            series = series + SERIE_MS_FORMAT.format('cleanup', 'cleanup')
        fullgc_str = ''.join(self.data.get('fullgc', []))
        if fullgc_str != '':
            if series != '':
                series = series + ', '
            series = series + SERIE_S_FORMAT.format('Full GC', 'fullgc')
        return series


class ShenandoahGCLineParser(GCLineParser):
    def __init__(self, log_format):
        super(ShenandoahGCLineParser, self).__init__(log_format)
        self.shenandoah_heap_occupancy_pattern = '(?P<HEAP_BEFORE_GC>\d+[MG])->(?P<HEAP_AFTER_GC>\d+[MG])\((?P<HEAP_MAX>\d+[MG])\)'
        if log_format == JDK8_FORMAT:
            self.shenandoah_pause_pattern = ', (?P<PAUSE>\d+\.\d+) ms\]'
            self.shenandoah_init_mark_re = re.compile('(?P<TIMESTAMP>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3})\+\d{4}: .*\[Pause Init Mark.*' + self.shenandoah_pause_pattern + '.*', re.DOTALL)
            self.shenandoah_final_mark_re = re.compile('(?P<TIMESTAMP>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3})\+\d{4}: .*\[Pause Final Mark.*' + self.shenandoah_pause_pattern + '.*', re.DOTALL)
            self.shenandoah_init_update_re = re.compile('(?P<TIMESTAMP>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3})\+\d{4}: .*\[Pause Init Update.*' + self.shenandoah_pause_pattern + '.*', re.DOTALL)
            self.shenandoah_final_update_re = re.compile('(?P<TIMESTAMP>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3})\+\d{4}: .*\[Pause Final Update.*' + self.shenandoah_pause_pattern + '.*', re.DOTALL)
            self.shenandoah_final_evac_re = re.compile('(?P<TIMESTAMP>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3})\+\d{4}: .*\[Pause Final Evac.*' + self.shenandoah_pause_pattern + '.*', re.DOTALL)
            self.shenandoah_degenerated_re = re.compile('(?P<TIMESTAMP>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3})\+\d{4}: .*\[Pause Degenerated GC.*' + self.shenandoah_pause_pattern + '.*', re.DOTALL)
            self.shenandoah_full_re = re.compile('(?P<TIMESTAMP>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3})\+\d{4}: .*\[Pause Full.*' + self.shenandoah_pause_pattern + '.*', re.DOTALL)
            self.shenandoah_heap_occupancy_re = re.compile('(?P<TIMESTAMP>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3})\+\d{4}: .*\[Concurrent cleanup.*' + self.shenandoah_heap_occupancy_pattern + '.*', re.DOTALL)
        else:
            self.shenandoah_pause_pattern = '(?P<PAUSE>\d+\.\d+)ms'
            self.shenandoah_init_mark_re = re.compile('\[(?P<TIMESTAMP>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3})\+\d{4}.* GC\(\d+\) Pause Init Mark.*' + self.shenandoah_pause_pattern + '.*', re.DOTALL)
            self.shenandoah_final_mark_re = re.compile('\[(?P<TIMESTAMP>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3})\+\d{4}.* GC\(\d+\) Pause Final Mark.*' + self.shenandoah_pause_pattern + '.*', re.DOTALL)
            self.shenandoah_init_update_re = re.compile('\[(?P<TIMESTAMP>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3})\+\d{4}.* GC\(\d+\) Pause Init Update.*' + self.shenandoah_pause_pattern + '.*', re.DOTALL)
            self.shenandoah_final_update_re = re.compile('\[(?P<TIMESTAMP>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3})\+\d{4}.* GC\(\d+\) Pause Final Update.*' + self.shenandoah_pause_pattern + '.*', re.DOTALL)
            self.shenandoah_final_evac_re = re.compile('\[(?P<TIMESTAMP>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3})\+\d{4}.* GC\(\d+\) Pause Final Evac.*' + self.shenandoah_pause_pattern + '.*', re.DOTALL)
            self.shenandoah_degenerated_re = re.compile('\[(?P<TIMESTAMP>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3})\+\d{4}.* GC\(\d+\) Pause Degenerated GC.*' + self.shenandoah_pause_pattern + '.*', re.DOTALL)
            self.shenandoah_full_re = re.compile('\[(?P<TIMESTAMP>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3})\+\d{4}.* GC\(\d+\) .*\[Pause Full.*' + self.shenandoah_pause_pattern + '.*', re.DOTALL)
            self.shenandoah_heap_occupancy_re = re.compile('\[(?P<TIMESTAMP>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3})\+\d{4}.* GC\(\d+\) Concurrent cleanup ' + self.shenandoah_heap_occupancy_pattern + '.*', re.DOTALL)


    def parse_line(self, full_line):
        self.jdk8_parse_line(full_line)

    def jdk8_parse_line(self, full_line):
        match_line = self.shenandoah_init_mark_re.match(full_line)
        if match_line:  # Shenandoah Init Mark
            timestamp = match_line.group('TIMESTAMP')
            match_timestamp = self.timestamp_re.match(timestamp)
            if match_timestamp:
                current_pause_ms = round(float(match_line.group('PAUSE')))
                self.add_data('initmark', '[{},{}],\n'.format(GCLineParser.format_timestamp(match_timestamp), current_pause_ms))
                self.event_count += 1
                return
        match_line = self.shenandoah_final_mark_re.match(full_line)
        if match_line:  # Shenandoah Final Mark
            timestamp = match_line.group('TIMESTAMP')
            match_timestamp = self.timestamp_re.match(timestamp)
            if match_timestamp:
                current_pause_ms = round(float(match_line.group('PAUSE')))
                self.add_data('finalmark', '[{},{}],\n'.format(GCLineParser.format_timestamp(match_timestamp), current_pause_ms))
                self.event_count += 1
                return
        match_line = self.shenandoah_init_update_re.match(full_line)
        if match_line:  # Shenandoah Init Update
            timestamp = match_line.group('TIMESTAMP')
            match_timestamp = self.timestamp_re.match(timestamp)
            if match_timestamp:
                current_pause_ms = round(float(match_line.group('PAUSE')))
                self.add_data('initupdate', '[{},{}],\n'.format(GCLineParser.format_timestamp(match_timestamp), current_pause_ms))
                self.event_count += 1
                return
        match_line = self.shenandoah_final_update_re.match(full_line)
        if match_line:  # Shenandoah Final Update
            timestamp = match_line.group('TIMESTAMP')
            match_timestamp = self.timestamp_re.match(timestamp)
            if match_timestamp:
                current_pause_ms = round(float(match_line.group('PAUSE')))
                self.add_data('finalupdate', '[{},{}],\n'.format(GCLineParser.format_timestamp(match_timestamp), current_pause_ms))
                self.event_count += 1
                return
        match_line = self.shenandoah_final_evac_re.match(full_line)
        if match_line:  # Shenandoah Final Evac
            timestamp = match_line.group('TIMESTAMP')
            match_timestamp = self.timestamp_re.match(timestamp)
            if match_timestamp:
                current_pause_ms = round(float(match_line.group('PAUSE')))
                self.add_data('finalevac', '[{},{}],\n'.format(GCLineParser.format_timestamp(match_timestamp), current_pause_ms))
                self.event_count += 1
                return
        match_line = self.shenandoah_degenerated_re.match(full_line)
        if match_line:  # Shenandoah Degenerated GC
            timestamp = match_line.group('TIMESTAMP')
            match_timestamp = self.timestamp_re.match(timestamp)
            if match_timestamp:
                current_pause_ms = round(float(match_line.group('PAUSE')))
                self.add_data('degenerated', '[{},{}],\n'.format(GCLineParser.format_timestamp(match_timestamp), round(current_pause_ms/1000.0,3)))
                self.event_count += 1
                return
        match_line = self.shenandoah_full_re.match(full_line)
        if match_line:  # Shenandoah Full GC
            timestamp = match_line.group('TIMESTAMP')
            match_timestamp = self.timestamp_re.match(timestamp)
            if match_timestamp:
                current_pause_ms = round(float(match_line.group('PAUSE')))
                self.add_data('fullgc', '[{},{}],\n'.format(GCLineParser.format_timestamp(match_timestamp), round(current_pause_ms/1000.0, 3)))
                self.event_count += 1
                return
        match_line = self.shenandoah_heap_occupancy_re.match(full_line)
        if match_line:  # Shenandoah Concurrent cleanup occupancy
            timestamp = match_line.group('TIMESTAMP')
            match_timestamp = self.timestamp_re.match(timestamp)
            if match_timestamp:
                self.add_data('heap_occupancy', '[{},{}],\n'.format(GCLineParser.format_timestamp(match_timestamp), GCLineParser.heap_occupancy_to_G(match_line.group('HEAP_BEFORE_GC'))))
                self.add_data('heap_occupancy', '[{},{}],\n'.format(GCLineParser.format_timestamp(match_timestamp, 10), GCLineParser.heap_occupancy_to_G(match_line.group('HEAP_AFTER_GC'))))
                self.add_data('max_heap', '[{},{}],\n'.format(GCLineParser.format_timestamp(match_timestamp), GCLineParser.heap_max_to_G(match_line.group('HEAP_MAX'))))
                return


    def write(self, data_file):
        super(ShenandoahGCLineParser, self).write(data_file)
        data_file.write(self.format_data_serie('var data_serie_init_mark = [{}]\n', 'initmark'))
        data_file.write(self.format_data_serie('var data_serie_final_mark = [{}]\n', 'finalmark'))
        data_file.write(self.format_data_serie('var data_serie_init_update = [{}]\n', 'initupdate'))
        data_file.write(self.format_data_serie('var data_serie_final_update = [{}]\n', 'finalupdate'))
        data_file.write(self.format_data_serie('var data_serie_final_evac = [{}]\n', 'finalevac'))
        data_file.write(self.format_data_serie('var data_serie_degenerated = [{}]\n', 'degenerated'))

    def build_series(self):
        series = ''
        initmark_str = ''.join(self.data.get('initmark', []))
        if initmark_str != '':
            if series != '':
                series = series + ', '
            series = series + SERIE_MS_FORMAT.format('Init Mark', 'init_mark')
        finalmark_str = ''.join(self.data.get('finalmark', []))
        if finalmark_str != '':
            if series != '':
                series = series + ', '
            series = series + SERIE_MS_FORMAT.format('Final Mark', 'final_mark')
        initupdate_str = ''.join(self.data.get('initupdate', []))
        if initupdate_str != '':
            if series != '':
                series = series + ', '
            series = series + SERIE_MS_FORMAT.format('Init Update', 'init_update')
        finalupdate_str = ''.join(self.data.get('finalupdate', []))
        if finalupdate_str != '':
            if series != '':
                series = series + ', '
            series = series + SERIE_MS_FORMAT.format('Final Update', 'final_update')
        finalevac_str = ''.join(self.data.get('finalevac', []))
        if finalevac_str != '':
            if series != '':
                series = series + ', '
            series = series + SERIE_MS_FORMAT.format('Final Evac', 'final_evac')
        degenerated_str = ''.join(self.data.get('degenerated', []))
        if degenerated_str != '':
            if series != '':
                series = series + ', '
            series = series + SERIE_S_FORMAT.format('Degenerated GC', 'degenerated')
        return series

class CMSGCLineParser(GCLineParser):

    def __init__(self, log_format):
        super(CMSGCLineParser, self).__init__(log_format)
        self.CMS_initalmark_re = re.compile('(?P<TIMESTAMP>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3})\+\d{4}: .*\[GC \(CMS Initial Mark\) .*\[1 CMS-initial-mark: [^\]]+\] (?P<HEAP_BEFORE_GC>\d+)K\((?P<HEAP_MAX>\d+)K\)' + self.pause_pattern + '.*' + self.times_pattern, re.DOTALL)
        self.CMS_finalremark_re = re.compile('(?P<TIMESTAMP>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3})\+\d{4}: .*\[GC \(CMS Final Remark\) .*\[1 CMS-remark: [^\]]+\] (?P<HEAP_BEFORE_GC>\d+)K\((?P<HEAP_MAX>\d+)K\)' + self.pause_pattern + '.*' + self.times_pattern, re.DOTALL)
        self.CMS_fullgc_re = re.compile('(?P<TIMESTAMP>\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}\.\d{3})\+\d{4}: .*\[CMS: [^\]]+\] (?P<HEAP_BEFORE_GC>\d+)K->(?P<HEAP_AFTER_GC>\d+)K\((?P<HEAP_MAX>\d+)K\), \[Metaspace: [^\]]+\]' + self.pause_pattern + '.*' + self.times_pattern, re.DOTALL)

    def parse_line(self, full_line):
        match_line = self.CMS_initalmark_re.match(full_line)
        if match_line:  # CMS initial mark
            timestamp = match_line.group('TIMESTAMP')
            match_timestamp = self.timestamp_re.match(timestamp)
            if match_timestamp:
                self.add_data('heap_occupancy', '[{},{}],\n'.format(GCLineParser.format_timestamp(match_timestamp), round(int(match_line.group('HEAP_BEFORE_GC'))/1048576, 2)))
                self.add_data('initialmark', '[{},{}],\n'.format(GCLineParser.format_timestamp(match_timestamp), round(float(match_line.group('PAUSE'))*1000)))
                self.add_cpu_times(match_line, match_timestamp)
                self.event_count += 1
                return
        match_line = self.CMS_finalremark_re.match(full_line)
        if match_line:  # CMS final remark
            timestamp = match_line.group('TIMESTAMP')
            match_timestamp = self.timestamp_re.match(timestamp)
            if match_timestamp:
                self.add_data('heap_occupancy', '[{},{}],\n'.format(GCLineParser.format_timestamp(match_timestamp), round(int(match_line.group('HEAP_BEFORE_GC'))/1048576, 2)))
                self.add_data('finalremark', '[{},{}],\n'.format(GCLineParser.format_timestamp(match_timestamp), round(float(match_line.group('PAUSE'))*1000)))
                self.add_cpu_times(match_line, match_timestamp)
                self.event_count += 1
                return
        match_line = self.CMS_fullgc_re.match(full_line)
        if match_line:  # CMS Full GC
            timestamp = match_line.group('TIMESTAMP')
            match_timestamp = self.timestamp_re.match(timestamp)
            if match_timestamp:
                self.add_data('heap_occupancy', '[{},{}],\n'.format(GCLineParser.format_timestamp(match_timestamp), round(int(match_line.group('HEAP_BEFORE_GC'))/1048576, 2)))
                self.add_data('heap_occupancy', '[{},{}],\n'.format(GCLineParser.format_timestamp(match_timestamp), round(int(match_line.group('HEAP_AFTER_GC'))/1048576, 2)))
                self.add_data('max_heap', '[{},{}],\n'.format(GCLineParser.format_timestamp(match_timestamp), math.ceil(int(match_line.group('HEAP_MAX')) / 1048576)))
                self.add_data('fullgc', '[{},{}],\n'.format(GCLineParser.format_timestamp(match_timestamp), round(float(match_line.group('PAUSE')), 3)))
                self.add_cpu_times(match_line, match_timestamp)
                self.event_count += 1
                return

    def write(self, data_file):
        super(CMSGCLineParser, self).write(data_file)
        # CMS/G1
        data_file.write(self.format_data_serie('var data_serie_initialmark = [{}]\n', 'initialmark'))
        data_file.write(self.format_data_serie('var data_serie_finalremark = [{}]\n', 'finalremark'))

    def build_series(self):
        series = ''
        minorgc_str = ''.join(self.data.get('minorgc', []))
        if minorgc_str != '':
            series = series + SERIE_MS_FORMAT.format('minor GC', 'minorgc')
        initialmark_str = ''.join(self.data.get('initialmark', []))
        if initialmark_str != '':
            if series != '':
                series = series + ', '
            series = series + SERIE_MS_FORMAT.format('initial mark', 'initialmark')
        finalremark_str = ''.join(self.data.get('finalremark', []))
        if finalremark_str != '':
            if series != '':
                series = series + ', '
            series = series + SERIE_MS_FORMAT.format('final remark', 'finalremark')
        fullgc_str = ''.join(self.data.get('fullgc', []))
        if fullgc_str != '':
            if series != '':
                series = series + ', '
            series = series + SERIE_S_FORMAT.format('Full GC', 'fullgc')
        return series

idx = 1
if (sys.argv[1].startswith("--gc=")):
    idx = 2
gclog_filename = sys.argv[idx]
data_filename = sys.argv[idx + 1]
gclog_file = open_file(gclog_filename, "r")
try:
    parse(gclog_file, data_filename)
finally:
    gclog_file.close()