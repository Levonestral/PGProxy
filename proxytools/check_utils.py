#!/usr/bin/python
# -*- coding: utf-8 -*-

import argparse
import logging

log = logging.getLogger('pogo-proxies')


def get_args():
    parser = argparse.ArgumentParser()
    parser.add_argument('-v', '--verbose',
                        help='Run in the verbose mode.',
                        action='store_true')
    source = parser.add_mutually_exclusive_group(required=True)
    source.add_argument('-f', '--proxy-file',
                        help='Filename of proxy list to verify.')
    source.add_argument('-s', '--scrape',
                        help='Scrape webpages for proxy lists.',
                        default=False,
                        action='store_true')
    parser.add_argument('-m', '--mode',
                        help=('Specify which proxy mode to use for testing. ' +
                              'Default is "socks".'),
                        default='socks',
                        choices=('http', 'socks'))
    parser.add_argument('-o', '--output-file',
                        help='Output filename for working proxies.',
                        default='working_proxies.txt')
    parser.add_argument('-r', '--retries',
                        help='Number of attempts to check each proxy.',
                        default=5,
                        type=int)
    parser.add_argument('-t', '--timeout',
                        help='Connection timeout. Default is 5 seconds.',
                        default=5,
                        type=float)
    parser.add_argument('-pj', '--proxy-judge',
                        help='URL for AZenv script used to test proxies.',
                        default='http://pascal.hoez.free.fr/azenv.php')
    parser.add_argument('-na', '--no-anonymous',
                        help='Disable anonymous proxy test.',
                        default=False,
                        action='store_true')
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument('-nt', '--no-test',
                      help='Disable PTC/Niantic proxy test.',
                      default=False,
                      action='store_true')
    mode.add_argument('-er', '--extra-request',
                      help='Make an extra request to validate PTC.',
                      default=False,
                      action='store_true')
    parser.add_argument('-bf', '--backoff-factor',
                        help=('Factor (in seconds) by which the delay ' +
                              'until next retry will increase.'),
                        default=0.25,
                        type=float)
    parser.add_argument('-mc', '--max-concurrency',
                        help='Maximum concurrent proxy testing requests.',
                        default=100,
                        type=int)
    parser.add_argument('-bs', '--batch-size',
                        help='Check proxies in batches of limited size.',
                        default=300,
                        type=int)
    parser.add_argument('-l', '--limit',
                        help='Stop tests when we have enough good proxies.',
                        default=100,
                        type=int)
    parser.add_argument('-ic', '--ignore-country',
                        help='Ignore proxies from countries in this list.',
                        action='append', default=['china'])
    parser.add_argument('-gu', '--geoip_url',
                        help='URL to lookup the geo-location/country of IP.',
                        action='store_true',
                        default='http://www.freegeoip.net/json/{0}')
    output = parser.add_mutually_exclusive_group()
    output.add_argument('--proxychains',
                        help='Output in proxychains-ng format.',
                        default=False,
                        action='store_true')
    output.add_argument('--kinancity',
                        help='Output in Kinan City format.',
                        default=False,
                        action='store_true')
    output.add_argument('--clean',
                        help='Output proxy list without protocol.',
                        default=False,
                        action='store_true')
    args = parser.parse_args()

    if not args.proxy_file and not args.scrape:
        log.error('You must supply a proxylist file or enable scraping.')
        exit(1)

    if not args.proxy_judge:
        log.error('You must specify a URL for an AZenv proxy judge.')
        exit(1)

    return args
