#!/usr/bin/python
# -*- coding: utf-8 -*-

import sys
import json
import time
import logging
from Queue import Queue
from threading import Thread
from datetime import datetime

from flask import Flask, request, jsonify

from proxytools import pool_utils
from proxytools.proxy_tester import check_proxies, get_local_ip
from proxytools.shared_utils import (get_country_from_ip,
                                     load_proxies,
                                     parse_bool)
from proxytools.pool_models import (init_database,
                                    db_updater,
                                    add_proxy_direct,
                                    working_proxy_count,
                                    get_all_proxies,
                                    get_working_proxies,
                                    get_filtered_proxies,
                                    purge_invalid_proxies,
                                    flaskDb)
from proxytools.proxy_scraper import (scrape_sockslist_net,
                                      scrape_vipsocks24_net,
                                      scrape_proxyserverlist24_top,
                                      scrape_socksproxylist24_top,
                                      scrape_premproxy_free)


# Reduce noise from logs
logging.getLogger("requests").setLevel(logging.CRITICAL)
logging.getLogger("urllib3").setLevel(logging.CRITICAL)
logging.basicConfig(
    format='%(asctime)s [%(threadName)15.15s][%(levelname)8.8s] %(message)s',
    level=logging.INFO)

# Silence some loggers
logging.getLogger('werkzeug').setLevel(logging.WARNING)

log = logging.getLogger('pogo-proxies')


stats_conditions = [
    ("Working", "working = 1 and banned = 0 and failed = 0 and invalid = 0"),
    ("Banned", "working = 0 and banned = 1 and failed = 0 and invalid = 0"),
    ("Failed", "working = 0 and banned = 0 and failed = 1 and invalid = 0"),
    ("Invalid", "invalid = 1")
]

# ---------------------------------------------------------------------------

app = Flask(__name__)


# ---------------------------------------------------------------------------
# REST Methods
# ---------------------------------------------------------------------------

@app.route('/', methods=['GET'])
def index():
    return "PGProxy running!"


@app.route('/proxy/status', methods=['GET'])
def get_status():

    lines = """<style>
        th,td { padding-left: 10px; padding-right:
            10px; border: 1px solid #ddd; }
        table { border-collapse: collapse }
        td { text-align:center }</style>"""
    lines += "DB Queue Size: {} <br><br>".format(db_updates_queue.qsize())

    lines += "<table>"

    lines += "<th>&nbsp;</th><th>Active</th><th>Frequency</th>"
    lines += "<tr><td>Auto Refresh: </td>"
    if args.auto_refresh:
        lines += "<td>ON</td><td>{}</td>".format(args.auto_refresh_frequency)
    else:
        lines += "<td>OFF</td><td>0</td>"
    lines += "</tr>"
    lines += "</table>"
    lines += "<br>"

    lines += "<table>"
    for c in stats_conditions:
        lines += "<th>{}</th>".format(c[0])
    lines += "<th>TOTAL</th>"

    total_count = 0
    lines += "<tr>"
    for c in stats_conditions:
        cursor = flaskDb.database.execute_sql('''
            select count(*) from proxypool
            where {}
        '''.format(c[1]))

        count = 0
        for row in cursor.fetchall():
            count = row[0]

        total_count += count
        lines += "<td>{}</td>".format(count)

    lines += "<td>{}</td>".format(total_count)
    lines += "</tr>"
    lines += "</table>"

    return lines


@app.route('/proxy/status/full', methods=['GET'])
def get_status_full():

    lines = get_status()

    lines += "<br>"
    for c in stats_conditions:

        lines += "<h3>{}</h3>".format(c[0])

        cursor = flaskDb.database.execute_sql('''
            select url from proxypool
            where {}
            order by url desc
        '''.format(c[1]))

        lines += "<textarea name='proxies' rows='15' style='width:100%;'>"
        for row in cursor.fetchall():
            lines += "{}\r\n".format(row[0])
        lines += "</textarea>"

    return lines


@app.route('/proxy/request', methods=['GET'])
def get_proxy_batch():

    format = request.args.get('format')

    working = parse_bool(request.args.get('working'))
    banned = parse_bool(request.args.get('banned'))
    failed = parse_bool(request.args.get('failed'))
    invalid = parse_bool(request.args.get('invalid'))

    if not banned and not failed and not invalid:
        working = True

    proxies = get_filtered_proxies(working, banned, failed, invalid)

    if format == 'txt':
        page = ''
        for p in proxies:
            page += p.url + '\r\n'
        return page
    elif format == 'list':
        page = '['
        page += ', '.join(str(p.url) for p in proxies)
        page += ']'
        return page
    else:
        return jsonify([e.serialize() for e in proxies])


@app.route('/proxy/update', methods=['POST'])
def proxy_update():

    data = json.loads(request.data)
    if isinstance(data, list):
        for update in data:
            update['last_modified'] = datetime.now()
            db_updates_queue.put(update)
    else:
        data['last_modified'] = datetime.now()
        db_updates_queue.put(data)
    return 'ok'


@app.route('/proxy/add', methods=['GET', 'POST'])
def proxy_add():

    def load_proxies(s):
        proxies = []
        for line in s.splitlines():
            if line.strip() == "":
                continue
            proxies.append({
                'url': line
            })
        return proxies

    if request.method == 'POST':

        if 'proxies' in request.form:
            data = request.form
            proxies = load_proxies(data.get('proxies'))
        elif 'proxies' in request.args:
            data = request.args
            proxies = load_proxies(data.get('proxies'))
        else:
            data = request.get_json()
            if data:
                proxies = data.get('proxies', [])
            else:
                proxies = []

        if data is None or len(proxies) == 0:
            msg = "No proxies provided, or data not parseable"
            log.warning(msg)
            return msg, 503

        proxies = list(proxies)

        if isinstance(proxies, list):
            for proxy in proxies:
                update_proxy_status(proxy['url'], False, False, False)
            return "Successfully added {} proxies.".format(len(proxies))
        else:
            update_proxy_status(proxies['url'], False, False, False)
            return "Successfully added 1 proxy."
    else:
        page = """<p>Manually add new proxies to the DB.
                    These will not be validated until the next call for
                    auto-validate and only if they are within the
                    assigned limit.</p>
                   <form method=POST>
                   <textarea name='proxies' rows='15'
                       placeholder='protocol://ip:port' style='width:100%;'>
                   </textarea>
                   <p><input type='submit' value='Submit'></p>
                   </form>
               """
        return page


# ---------------------------------------------------------------------------
# Run Methods
# ---------------------------------------------------------------------------

def run_server():
    app.run(threaded=True, host=args.host, port=args.port)


def import_proxies():

    proxies = set()

    log.info('Loading proxies from file: %s', args.proxy_file)
    proxylist = load_proxies(args.proxy_file, args.mode)

    if len(proxylist) > 0:
        proxies.update(proxylist)
    else:
        log.error('Proxy file was configured but no proxies were loaded.')
        sys.exit(1)

    proxies = list(proxies)

    check_and_import_proxies(proxies, True, False, True)

    log.info('Import completed, exiting.')


# ---------------------------------------------------------------------------
# Proxy Updating Methods
# ---------------------------------------------------------------------------

def check_and_import_proxies(proxies, import_all_types,
                             capture_failed_anon, ignore_limit):

    log.info('Found a total of %d proxies. Starting tests...', len(proxies))

    args.local_ip = None
    if not args.no_anonymous:
        local_ip = get_local_ip(args.proxy_judge)

        if not local_ip:
            log.error('Failed to identify local IP address.')
            sys.exit(1)

        log.info(
            'Using local IP address to test for anonymous: %s', local_ip)
        args.local_ip = local_ip

    if args.batch_size > 0:
        chunks = [proxies[x:x+args.batch_size]
                  for x in xrange(0, len(proxies), args.batch_size)]

        batch_count = 0
        working_count = 0
        num_chunks = len(chunks)

        log.info('Using {} chunks of {}'
                 .format(num_chunks, args.batch_size))

        for chunk in chunks:

            batch_count += 1
            log.info('Starting batch {} of {}. Working: {}'
                     .format(batch_count, num_chunks, working_count))

            working_proxies, banned_proxies, failed_proxies = check_proxies(
                args, chunk, capture_failed_anon)

            for proxy in working_proxies:

                # Now that the IP is validated, let's check the country.
                country = get_country_from_ip(args.geoip_url, proxy)
                if country in args.ignore_country:
                    log.info('Skipping proxy from country: {} for {}'
                             .format(proxy, country))
                    continue

                # If still ok, update it now (creates if new)
                update_proxy_status(proxy, True, False, False)

                # If we've reached the limit of working proxies, break out.
                working_count += 1
                if not ignore_limit and working_count >= args.limit:
                    break

            # If requested, import all other result types.
            if import_all_types:
                for proxy in banned_proxies:
                    update_proxy_status(proxy, False, True, False)

                for proxy in failed_proxies:
                    update_proxy_status(proxy, False, False, True)

            # Second check for limit to break out of chunk loop.
            if not ignore_limit and working_count >= args.limit:
                log.info(
                    'Stopping tests, Limit reached: {} >= {}'
                    .format(working_count, args.limit))
                break

    else:
        working_proxies, banned_proxies, failed_proxies = check_proxies(
            args, proxies, capture_failed_anon)

        for proxy in working_proxies:

            # Now that the IP is validated, let's check the country.
            country = get_country_from_ip(args.geoip_url, proxy)
            if country in args.ignore_country:
                log.info('Skipping proxy from country: {} for {}'
                         .format(proxy, country))
                continue

            # If still here, add the proxy.
            update_proxy_status(proxy, True, False, False)

        if import_all_types:
            for proxy in banned_proxies:
                update_proxy_status(proxy, False, True, False)
            for proxy in failed_proxies:
                update_proxy_status(proxy, False, False, True)

    # Now log a status of everything in DB.
    log_proxy_status()


def log_proxy_status():

    # Wait until the DB is finished updating.
    wait_db_updates()

    # Now pull out the status for everything.
    total_count = 0
    lines = "Status of {} proxies. "
    for c in stats_conditions:
        cursor = flaskDb.database.execute_sql('''
            select count(*) from proxypool
            where {}
        '''.format(c[1]))

        count = 0
        for row in cursor.fetchall():
            count = row[0]

        total_count += count
        lines += "{}: {}, ".format(c[0], count)

    lines = lines.rstrip(', ')
    log.info(lines.format(total_count))


def update_proxy_status(url, working, banned, failed):

    if args.proxy_file:
        add_proxy_direct(url, working, banned, failed)
        log.info(
            "add_proxy_direct for {}. working: {}, failed: {}, banned: {}"
            .format(url, working, failed, banned))
    else:
        proxy = {}
        proxy['url'] = url
        proxy['working'] = working
        proxy['banned'] = banned
        proxy['failed'] = failed
        proxy['last_modified'] = datetime.now()

        # Reset their retry counts back to 0 if currently working.
        if working:
            proxy['banned_retry_count'] = 0
            proxy['failed_retry_count'] = 0

        db_updates_queue.put(proxy)
        if args.log_proxy_updates:
            log.info(
                """DB update_proxy_status
                for {}. working: {}, failed: {}, banned: {}"""
                .format(url, working, failed, banned))


def wait_db_updates():

    # Give time for DB to update before continuing if needed.
    if db_updates_queue.qsize() > 0:
        log.info("Waiting on DB updates.")

        while db_updates_queue.qsize() > 0:
            time.sleep(1)

        log.info("DB updates completed.")

    # Sleep at least one second regardless, just in case.
    time.sleep(1)


def clone_proxy(dbproxy):

    proxy = {}
    proxy['url'] = dbproxy.url
    proxy['working'] = dbproxy.working
    proxy['invalid'] = dbproxy.invalid
    proxy['banned'] = dbproxy.banned
    proxy['banned_retry_count'] = dbproxy.banned_retry_count
    proxy['failed'] = dbproxy.failed
    proxy['failed_retry_count'] = dbproxy.failed_retry_count
    proxy['last_modified'] = dbproxy.last_modified

    return proxy


# ---------------------------------------------------------------------------
# Validation Methods
# ---------------------------------------------------------------------------

def validate_working_proxies():

    log.info('Validating existing working proxies...')

    urls = []
    proxies = get_working_proxies()
    for proxy in proxies:
        urls.append(proxy.url)

    if len(urls) > 0:
        check_and_import_proxies(urls, True, True, True)
    else:
        log.info('No proxies available for validation.')


def validate_all_proxies():

    log.info('Validating ALL existing proxies...')

    urls = []

    proxies = get_all_proxies()
    for proxy in proxies:

        update_proxy = clone_proxy(proxy)

        # If any banned/failed proxies have reached their retry limit,
        # then update them to have invalid flag and don't add to list.
        if proxy.banned == 1:

            if proxy.banned_retry_count < args.auto_refresh_banned_retries:
                # Update current banned retry count.
                # It will be set to 0 if found valid later.
                update_proxy['banned_retry_count'] += 1
                update_proxy['last_modified'] = datetime.now()
                db_updates_queue.put(update_proxy)
                if args.log_proxy_updates:
                    log.info(
                        'Incrementing banned retry for: %s',
                        update_proxy['url'])
            else:
                # Flag this proxy as invalid.
                update_proxy['working'] = False
                update_proxy['invalid'] = True
                update_proxy['last_modified'] = datetime.now()
                db_updates_queue.put(update_proxy)
                if args.log_proxy_updates:
                    log.info(
                        'Too many ban retries. Proxy is invalid: %s',
                        update_proxy['url'])

                # Don't continue any further with this proxy.
                continue

        if proxy.failed == 1:

            if proxy.failed_retry_count < args.auto_refresh_failed_retries:
                # Update current failed retry count.
                # It will be set to 0 if found valid later.
                update_proxy['failed_retry_count'] += 1
                update_proxy['last_modified'] = datetime.now()
                db_updates_queue.put(update_proxy)
                if args.log_proxy_updates:
                    log.info(
                        'Incrementing failed retry for: %s',
                        update_proxy['url'])
            else:
                # Flag this proxy as invalid.
                update_proxy['working'] = False
                update_proxy['invalid'] = True
                update_proxy['last_modified'] = datetime.now()
                db_updates_queue.put(update_proxy)
                if args.log_proxy_updates:
                    log.info(
                        'Too many failure retries. Proxy is invalid: %s',
                        update_proxy['url'])

                # Don't continue any further with this proxy.
                continue

        # If not invalid, add this proxy to the list for (re)validation.
        if not proxy.invalid:
            urls.append(proxy.url)

    if len(urls) > 0:
        check_and_import_proxies(urls, True, True, True)
    else:
        log.info('No proxies available for validation.')


# ---------------------------------------------------------------------------
# Scraping Methods
# ---------------------------------------------------------------------------

def scrape_http(proxies):
    log.info('Scraping HTTP proxies...')
    proxies.update(scrape_proxyserverlist24_top())
    proxies.update(scrape_premproxy_free(args.ignore_country))


def scrape_socks(proxies):
    log.info('Scraping SOCKS5 proxies...')
    proxies.update(scrape_sockslist_net(args.ignore_country))
    proxies.update(scrape_vipsocks24_net())
    proxies.update(scrape_socksproxylist24_top())


def scrape_proxies():

    # Check to see if we have at least the minimum proxies wanted.
    # Read DB for working proxies and compare against args.limit
    # If we already have limit, then don't scrape for more.
    working = working_proxy_count()
    if working < args.limit:
        log.info(
            'Scraping required. Working proxies NOT within limit. {} >= {}'
            .format(working, args.limit))
    else:
        log.info(
            'Scraping NOT required. Working proxies within limit. {} >= {}'
            .format(working, args.limit))
        return

    log.info('Scraping for new proxies...')

    proxies = set()

    if args.mode == 'http':
        scrape_http(proxies)
    elif args.mode == 'socks':
        scrape_socks(proxies)
    else:
        scrape_http(proxies)
        scrape_socks(proxies)

    proxies = list(proxies)

    # Validate all the obtained proxies.
    check_and_import_proxies(proxies, False, False, False)


# ---------------------------------------------------------------------------
# Daemon Threads
# ---------------------------------------------------------------------------

def auto_refresh_daemon():

    update_frequency_mins = args.auto_refresh_frequency
    refresh_time_sec = update_frequency_mins * 60

    # Sleep the initial amount of time before first run.
    time.sleep(refresh_time_sec)

    while True:
        log.info('Running auto refresh...')

        # Purge all invalid proxies if turned on
        if args.auto_refresh_purge_invalid:
            purge_invalid_proxies()

        # Validate all existing proxies in the DB.
        validate_all_proxies()

        # Check to see if we need to scrape for new proxies..
        scrape_proxies()

        # Wait x seconds before next refresh.
        log.info('Waiting %d minutes before next auto refresh.',
                 refresh_time_sec / 60)
        time.sleep(refresh_time_sec)


# ---------------------------------------------------------------------------
# Initialize
# ---------------------------------------------------------------------------

def initialize():

    t = Thread(target=db_updater, name='db-updater',
               args=(args, db_updates_queue, db))
    t.daemon = True
    t.start()

    # Check to see if we should be doing an import instead.
    if args.proxy_file:
        # Run the import.
        import_proxies()
    else:

        # Check to see if there should be any jobs run before startup.
        updated = False
        if args.initial_validate_working:
            validate_working_proxies()
            updated = True
        elif args.initial_validate_all:
            validate_all_proxies()
            updated = True

        if args.initial_scrape:
            scrape_proxies()
            updated = True

        # Log out current status.
        if updated is False:
            log_proxy_status()

        # Start the auto refresh thread if required.
        if args.auto_refresh:
            t = Thread(target=auto_refresh_daemon, name='auto-refresh')
            t.daemon = True
            t.start()
            log.info('Auto refresh is enabled.')
        else:
            log.info('Auto refresh is disabled.')

        # Start the server.
        log.info('Server initialized and running...')
        run_server()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

log.info("PGProxy starting up...")

# Obtain arguments from commandline or configuration file.
args = pool_utils.get_args()

# Initialize the database.
db = init_database(args, app)

# DB Updates queue.
db_updates_queue = Queue()

# Set the logging level.
log.setLevel(logging.INFO)
if args.verbose:
    log.setLevel(logging.DEBUG)
    log.debug('Running in verbose mode (-v).')

# Start up everything.
initialize()
