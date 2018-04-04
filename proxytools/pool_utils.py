#!/usr/bin/python
# -*- coding: utf-8 -*-

import sys
import os
import configargparse
import logging

log = logging.getLogger('pogo-proxies')


def get_args():

    # Pre-check to see if the -cf or --config flag is used on the command line.
    # If not, we'll use the env var or default value. This prevents layering of
    # config files as well as a missing config.ini.
    defaultconfigfiles = []
    if '-cf' not in sys.argv and '--config' not in sys.argv:
        defaultconfigfiles = [os.getenv('PROXYPOOL_CONFIG', os.path.join(
            os.path.dirname(__file__), '../config/config.ini'))]
    parser = configargparse.ArgParser(default_config_files=defaultconfigfiles)

    parser.add_argument('-cf', '--config',
                        is_config_file=True, help='Set configuration file')
    parser.add_argument('-v', '--verbose',
                        help='Run in the verbose mode.',
                        action='store_true')

    parser.add_argument('-f', '--proxy-file',
                        help=('Filename of proxy list to verify and import. ' +
                              'Exits when completed.'))

    parser.add_argument('-m', '--mode',
                        help=('Specify which proxy mode to use for testing. ' +
                              'Default: all'),
                        default='all',
                        choices=('all', 'http', 'socks'))
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

    parser.add_argument('-er', '--extra-request',
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
                        help='Minimum number of good proxies to maintain.',
                        default=100,
                        type=int)
    parser.add_argument('-ic', '--ignore-country',
                        help='Ignore proxies from countries in this list.',
                        action='append', default=['china'])
    parser.add_argument('-gu', '--geoip_url',
                        help='URL to lookup the geo location of a given IP.',
                        action='store_true',
                        default='http://www.freegeoip.net/json/{0}')

    parser.add_argument('--host',
                        help='Binding IP.',
                        default='127.0.0.1')
    parser.add_argument('--port',
                        help='Port.',
                        type=int, default=4646)
    parser.add_argument('--db-name',
                        help='Database name.',
                        default='')
    parser.add_argument('--db-user',
                        help='Database user name.',
                        default='')
    parser.add_argument('--db-pass',
                        help='Database user password.',
                        default='')
    parser.add_argument('--db-host',
                        help='Database host.',
                        default='localhost')
    parser.add_argument('--db-port',
                        help='Database port.',
                        type=int, default=3306)
    parser.add_argument('--db-max-connections',
                        help='Database max connections.',
                        type=int, default=20)

    onstrt = parser.add_mutually_exclusive_group()
    onstrt.add_argument('--initial-validate-working',
                        help=('Validate ONLY previously working proxies ' +
                              'upon server start.'),
                        action='store_true', default=False)
    onstrt.add_argument('--initial-validate-all',
                        help=('Validate ALL proxies upon server start.'),
                        action='store_true', default=False)

    parser.add_argument('--initial-scrape',
                        help=('Scrape and validate new proxies upon ' +
                              'server start.'),
                        action='store_true', default=False)

    parser.add_argument('--auto-refresh',
                        help=('Periodically re-validate working, banned ' +
                              'or failed proxies and obtain new one''s ' +
                              'if needed to maintain minimum level. ' +
                              'Default false.'),
                        action='store_true', default=False)
    parser.add_argument('--auto-refresh-frequency',
                        help=('Frequency, in minutes, of how often to run ' +
                              'auto-refresh. Default 60.'),
                        type=int, default=60)
    parser.add_argument('--auto-refresh-banned-retries',
                        help=('Number of times to retry a banned proxy ' +
                              'before giving up entirely.'),
                        type=int, default=5)
    parser.add_argument('--auto-refresh-failed-retries',
                        help=('Number of times to retry a failed proxy ' +
                              'before giving up entirely.'),
                        type=int, default=5)
    parser.add_argument('--auto-refresh-purge-invalid',
                        help=('During refresh processing, purge proxies ' +
                              'flagged as invalid due to max retries.' +
                              'Default False.'),
                        action='store_true', default=False)

    parser.add_argument('--log-db-updates',
                        help='Log database updates. Default False.',
                        action='store_true', default=False)
    parser.add_argument('--log-proxy-updates',
                        help='Log proxy updates. Default False.',
                        action='store_true', default=False)

    args = parser.parse_args()

    if not args.proxy_judge:
        log.error('You must specify a URL for an AZenv proxy judge.')
        exit(1)

    return args


def parse_bool(val):
    if val is None:
        return False
    if val.lower() == 'yes' or val.lower() == 'true':
        return True
    return False
