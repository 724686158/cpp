#!/usr/bin/env python
'''Compute metrics for varying number of controllers w/ different algorithms.'''
import logging
from optparse import OptionParser
import time

import networkx as nx

import metrics_lib as metrics
from topo.os3e import OS3EGraph
from file_libs import write_csv_file, write_json_file, read_json_file
from file_libs import write_dist_csv_file
from os3e_weighted import OS3EWeightedGraph

logging.basicConfig(level=logging.DEBUG)


def parse_args():
    opts = OptionParser()
    opts.add_option("--from_start", type = 'int', default = 3,
                    help = "number of controllers from start")
    opts.add_option("--from_end", type = 'int', default = 0,
                    help = "number of controllers from end")
    opts.add_option("--controller_list", type = 'str', default = None,
                    help = "list of space-separated controller totals")
    opts.add_option("--metric",
                    default = 'latency',
                    choices = metrics.METRICS,
                    help = "metric to compute, one in %s" % metrics.METRICS)
    opts.add_option("--all_metrics",  action = "store_true",
                    default = False,
                    help = "compute all metrics?")    
    opts.add_option("--lat_metrics",  action = "store_true",
                    default = False,
                    help = "compute all latency metrics?")
    opts.add_option("-w", "--write",  action = "store_true",
                    default = False,
                    help = "write plots, rather than display?")
    opts.add_option("--weighted",  action = "store_true",
                    default = False,
                    help = "used weighted input graph?")
    opts.add_option("--median",  action = "store_true",
                    default = False,
                    help = "compute median?")
    opts.add_option("--no-multiprocess",  action = "store_false",
                    default = True, dest = 'multiprocess',
                    help = "don't use multiple processes?")
    opts.add_option("--processes", type = 'int', default = 4,
                    help = "worker pool size; must set multiprocess=True")
    opts.add_option("--chunksize", type = 'int', default = 50,
                    help = "batch size for parallel processing")
    opts.add_option("--write_combos",  action = "store_true",
                    default = False,
                    help = "write out combinations?")
    opts.add_option("--write_dist",  action = "store_true",
                    default = False,
                    help = "write_distribution?")
    opts.add_option("--no-dist_only",  action = "store_false",
                    default = True, dest = 'dist_only',
                    help = "don't write out _only_ the full distribution (i.e.,"
                    "run all algorithms.)")
    opts.add_option("--use_prior_opts",  action = "store_true",
                    default = False,
                    help =  "Pull in previously computed data, rather than recompute?")
    opts.add_option("--no-compute_start",  action = "store_false",
                    default = True, dest = 'compute_start',
                    help = "don't compute metrics from start?")
    opts.add_option("--no-compute_end",  action = "store_false",
                    default = True, dest = 'compute_end',
                    help = "don't compute metrics from end?")
    options, arguments = opts.parse_args()

    if options.all_metrics:
        options.metrics = metrics.METRICS
    elif options.lat_metrics:
        options.metrics = ['latency', 'wc_latency']
    else:
        options.metrics = [options.metric]

    options.controllers = None
    if options.controller_list:
        options.controllers = []
        for i in options.controller_list.split(' '):
            options.controllers.append(int(i))

    return options


# Additional args to pass to metrics functions.
EXTRA_PARAMS = {
    'link_fail_prob': 0.01,
    'max_failures': 2
}


class Metrics:
    
    def __init__(self):

        options = parse_args()

        
        if options.weighted:
            g = OS3EWeightedGraph()
        else:
            g = OS3EGraph()

        if options.controllers:
            controllers = options.controllers
        else:  
            # Controller numbers to compute data for.
            controllers = []
    
            # Eventually expand this to n.
            if options.compute_start:
                controllers += range(1, options.from_start + 1)
            
            if options.compute_end:
                controllers += (range(g.number_of_nodes() - options.from_end + 1, g.number_of_nodes() + 1))

        filename = "data_out/os3e_"
        if options.weighted:
            filename += "weighted"
        else:
            filename += "unweighted"
            PRIOR_OPTS_filename = "data_out/os3e_unweighted_9_9.json"
        
        if options.controller_list:
            for c in controllers:
                filename += "_%s" % c
        else:
            filename += "_%s_to_%s" % (options.from_start, options.from_end)


        # data['data'][num controllers] = [latency:latency, nodes:[best-pos node(s)]]
        # data['metrics'] = [list of metrics included]
        # latency is also equal to 1/closeness centrality.
        data = {}

        if options.weighted:
            apsp = nx.all_pairs_dijkstra_path_length(g)
            apsp_paths = nx.all_pairs_dijkstra_path(g)
            # Try to roughly match the failure probability of links.
            link_fail_prob = EXTRA_PARAMS['link_fail_prob']
            distances = [g[src][dst]['weight'] for src, dst in g.edges()]
            weighted_link_fail_prob = g.number_of_edges() / float(sum(distances)) * link_fail_prob
            EXTRA_PARAMS['link_fail_prob'] = weighted_link_fail_prob
        else:
            apsp = nx.all_pairs_shortest_path_length(g)
            apsp_paths = nx.all_pairs_shortest_path(g)
        
        if options.use_prior_opts:
            data = read_json_file(PRIOR_OPTS_filename)
        else:
            start = time.time()
            metrics.run_all_combos(options.metrics, g, controllers, data, apsp,
                                   apsp_paths, options.weighted, options.write_dist,
                                   options.write_combos, EXTRA_PARAMS, options.processes,
                                   options.multiprocess, options.chunksize, options.median)
            total_duration = time.time() - start
            print "%0.6f" % total_duration
        
        if not options.dist_only:
            metrics.run_greedy_informed(data, g, apsp, options.weighted)
            metrics.run_greedy_alg_dict(data, g, 'greedy-cc', 'latency', nx.closeness_centrality(g, weighted_edges = options.weighted), apsp, options.weighted)
            metrics.run_greedy_alg_dict(data, g, 'greedy-dc', 'latency', nx.degree_centrality(g), apsp, options.weighted)
            for i in [10, 100, 1000]:
                metrics.run_best_n(data, g, apsp, i, options.weighted)
                metrics.run_worst_n(data, g, apsp, i, options.weighted)
        
        print "*******************************************************************"
        
        # Ignore the actual combinations in CSV outputs as well as single points.
        exclude = ["distribution", "metric", "group", "id"]
        if not options.write_combos:
            exclude += ['highest_combo', 'lowest_combo']

#        for d in data['data']['1']['distribution']:
#            print " id: %s latency: %s" % (d['id'], d['latency'])
#        
        if options.write:
            write_json_file(filename + '.json', data)
            write_csv_file(filename, data["data"], exclude = exclude)
            if options.write_dist:
                write_dist_csv_file(filename + '_dist', data["data"], exclude)


if __name__ == '__main__':
    Metrics()
