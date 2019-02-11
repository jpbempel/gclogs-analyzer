import sys
import bz2
import gzip
import re
import math
import time
import datetime


def open_file(inputfile, mode):
    if inputfile.endswith('bz2'):
        return bz2.BZ2File(inputfile, mode)
    elif inputfile.endswith('gz'):
        return gzip.open(inputfile, mode)
    else:
        return open(inputfile, mode)

def parse(gclog_file, data_filename):

    def format_timestamp(now, elapsed, offset = 0):
        dt = datetime.datetime.fromtimestamp(now + elapsed)
        return 'Date.UTC({},{},{},{},{},{},{})+{}'.format(dt.year, dt.month, dt.day,
                                                dt.hour, dt.minute, dt.second,
                                                       int(dt.microsecond / 1000), offset)

    def heap_occupancy_to_G(value_B):
        return round(value_B / (1024 * 1024 * 1024), 2)

    def heap_occupancy_to_M(value_B):
        return round(value_B / (1024 * 1024), 2)


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
        data[key] = data.get(key, '') + value

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

    data = {}
    now = time.time()
    for line in gclog_file:
        cols = line.split(',')
        if cols[0] == "StartRelativeMSec": # skip header
            continue
        elapsed = float(cols[0]) / 1000
        gen0 = int(cols[9])
        gen0before = int(cols[13])
        gen0after = int(cols[17])
        gen1 = int(cols[10])
        gen2 = int(cols[11])
        loh = int(cols[12])
        pause_ms = int(float(cols[7]))
        #add_data(data, 'gen0_occupancy', '[{},{}],\n'.format(format_timestamp(now, elapsed), heap_occupancy_to_M(gen0)))
        add_data(data, 'gen0_occupancy', '[{},{}],\n'.format(format_timestamp(now, elapsed), heap_occupancy_to_M(gen0before)))
        add_data(data, 'gen0_occupancy', '[{},{}],\n'.format(format_timestamp(now, elapsed, pause_ms), heap_occupancy_to_M(gen0after)))
        add_data(data, 'gen1_occupancy', '[{},{}],\n'.format(format_timestamp(now, elapsed), heap_occupancy_to_M(gen1)))
        add_data(data, 'gen2_occupancy', '[{},{}],\n'.format(format_timestamp(now, elapsed), heap_occupancy_to_G(gen2)))
        add_data(data, 'gen3_occupancy', '[{},{}],\n'.format(format_timestamp(now, elapsed), heap_occupancy_to_G(loh)))
        total = gen0 + gen1 + gen2 + loh
        add_data(data, 'total_heap_occupancy', '[{},{}],\n'.format(format_timestamp(now, elapsed), heap_occupancy_to_G(total)))
        generation = int(cols[2])
        if generation == 0:
            add_data(data, 'pause_gen0',
                     '[{},{}],\n'.format(format_timestamp(now, elapsed), pause_ms))
        if generation == 1:
            add_data(data, 'pause_gen1',
                     '[{},{}],\n'.format(format_timestamp(now, elapsed), pause_ms))
        if generation == 2:
            add_data(data, 'pause_initialmark',
                     '[{},{}],\n'.format(format_timestamp(now, elapsed), pause_ms))
            pause2_ms = int(float(cols[8]))
            add_data(data, 'pause_finalmark',
                     '[{},{}],\n'.format(format_timestamp(now, elapsed), pause2_ms))


    data_file = open(data_filename, 'w')
    try:
        data_file.write('var data_serie_heap_gen0 = [{}]\n'.format(data.get('gen0_occupancy', '')))
        data_file.write('var data_serie_heap_gen1 = [{}]\n'.format(data.get('gen1_occupancy', '')))
        data_file.write('var data_serie_heap_gen2 = [{}]\n'.format(data.get('gen2_occupancy', '')))
        data_file.write('var data_serie_heap_gen3 = [{}]\n'.format(data.get('gen3_occupancy', '')))
        data_file.write('var data_serie_heap_total = [{}]\n'.format(data.get('total_heap_occupancy', '')))
        data_file.write('var data_serie_pause_gen0 = [{}]\n'.format(data.get('pause_gen0', '')))
        data_file.write('var data_serie_pause_gen1 = [{}]\n'.format(data.get('pause_gen1', '')))
        data_file.write('var data_serie_pause_initialmark = [{}]\n'.format(data.get('pause_initialmark', '')))
        data_file.write('var data_serie_pause_finalmark = [{}]\n'.format(data.get('pause_finalmark', '')))
        series = build_series(data.get('minorgc', ''), data.get('fullgc', ''), data.get('initialmark', ''),
                             data.get('finalremark', ''), data.get('cleanup', ''), data.get('mixed', ''))
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