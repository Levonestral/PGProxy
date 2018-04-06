#!/usr/bin/python
# -*- coding: utf-8 -*-

import requests
import logging
from requests_futures.sessions import FuturesSession
from requests.packages.urllib3.util.retry import Retry
from requests.adapters import HTTPAdapter

log = logging.getLogger('pgproxy')

# Proxy check result constants.
check_result_ok = 0
check_result_failed = 1
check_result_banned = 2
check_result_wrong = 3
check_result_timeout = 4
check_result_exception = 5
check_result_empty = 6
check_result_max = 6  # Should be equal to maximal return code.


# Background handler for completed proxy check requests.
# Currently doesn't do anything.
def __proxy_check_completed(sess, resp):
    pass


# Get a future_requests FuturesSession that supports asynchronous workers
# and retrying requests on failure.
# Setting up a persistent session that is re-used by multiple requests can
# speed up requests to the same host, as it'll re-use the underlying TCP
# connection.
def get_async_requests_session(num_retries, backoff_factor, pool_size,
                               status_forcelist=[500, 502, 503, 504]):
    # Use requests & urllib3 to auto-retry.
    # If the backoff_factor is 0.1, then sleep() will sleep for [0.1s, 0.2s,
    # 0.4s, ...] between retries. It will also force a retry if the status
    # code returned is in status_forcelist.
    session = FuturesSession(max_workers=pool_size)

    # If any regular response is generated, no retry is done. Without using
    # the status_forcelist, even a response with status 500 will not be
    # retried.
    retries = Retry(total=num_retries, backoff_factor=backoff_factor,
                    status_forcelist=status_forcelist)

    # Mount handler on both HTTP & HTTPS.
    session.mount('http://', HTTPAdapter(max_retries=retries,
                                         pool_connections=pool_size,
                                         pool_maxsize=pool_size))
    session.mount('https://', HTTPAdapter(max_retries=retries,
                                          pool_connections=pool_size,
                                          pool_maxsize=pool_size))

    return session


def get_local_ip(proxy_judge):
    local_ip = None

    try:
        r = requests.get(proxy_judge)
        test = parse_azevn(r.content)
        local_ip = test['remote_addr']
    except Exception as e:
        log.error(e)

    return local_ip


def test_proxies(args, proxies):
    total_proxies = len(proxies)
    show_warnings = total_proxies <= 10

    max_concurrency = args.max_concurrency

    # If proxy testing concurrency is set to automatic, use max.
    if args.max_concurrency == 0:
        max_concurrency = total_proxies

    log.info('Testing anonymity of %d proxies with %d concurrency.',
             total_proxies, max_concurrency)

    session = get_async_requests_session(
        args.retries,
        args.backoff_factor,
        max_concurrency)

    test_queue = []
    anon_proxies = []
    failed_proxies = []

    for proxy in proxies:

        future = session.get(
            args.proxy_judge,
            proxies={'http': proxy, 'https': proxy},
            timeout=args.timeout,
            headers={
                 'Connection': 'close',
                 'Accept': '*/*',
                 'User-Agent': 'pokemongo/0 CFNetwork/893.14.2 Darwin/17.3.0',
                 'Accept-Language': 'en-us',
                 'Accept-Encoding': 'br, gzip, deflate',
                 'X-Unity-Version': '2017.1.2f1'},
            background_callback=__proxy_check_completed)
        test_queue.append((proxy, future))

    for proxy, future in test_queue:
        proxy_error = None
        try:
            response = future.result()
            # let's check the content
            result = parse_azevn(response.content)
            if result['remote_addr'] == args.local_ip:
                proxy_error = 'Non-anonymous proxy {}'.format(proxy)
            elif result['x_unity_version'] != '2017.1.2f1':
                proxy_error = 'Bad headers with proxy {}'.format(proxy)
            elif result['user_agent'] != ('pokemongo/0 ' +
                                          'CFNetwork/893.14.2 ' +
                                          'Darwin/17.3.0'):
                proxy_error = 'Bad user-agent with proxy {}'.format(proxy)

        except requests.exceptions.ConnectTimeout:
            proxy_error = 'Connection timeout for proxy {}.'.format(proxy)
        except requests.exceptions.ConnectionError:
            proxy_error = 'Failed to connect to proxy {}.'.format(proxy)
        except Exception as e:
            proxy_error = e

        if proxy_error:
            if show_warnings:
                log.warning(proxy_error)
            else:
                log.debug(proxy_error)
            failed_proxies.append(proxy)
        else:
            log.debug('Good anonymous proxy: %s', proxy)
            anon_proxies.append(proxy)

    return anon_proxies, failed_proxies


def parse_azevn(response):
    lines = response.split('\n')
    result = {
        'remote_addr': None,
        'x_unity_version': None,
        'user_agent': None
    }
    try:
        for line in lines:
            if 'REMOTE_ADDR' in line:
                result['remote_addr'] = line.split(' = ')[1]
            if 'X_UNITY_VERSION' in line:
                result['x_unity_version'] = line.split(' = ')[1]
            if 'USER_AGENT' in line:
                result['user_agent'] = line.split(' = ')[1]
    except Exception as e:
        log.warning('Error parsing AZ Environment variables: %s', e)

    return result


# Evaluates the status of PTC and Niantic request futures, and returns the
# result (optionally with an error).
# Warning: blocking! Can only get status code if request has finished.
def get_proxy_test_status(proxy, future_login, future_niantic, future_ptc):

    # Start by assuming everything is OK.
    check_result = check_result_ok
    proxy_error = None

    # Make sure we don't trip any code quality tools that test scope.
    ptc_response = None
    login_response = None
    niantic_response = None

    # Make sure both requests are completed.
    try:
        login_response = future_login.result()
        niantic_response = future_niantic.result()
        if future_ptc:
            ptc_response = future_ptc.result()
    except requests.exceptions.ConnectTimeout:
        proxy_error = ('Connection timeout for'
                       + ' proxy {}.').format(proxy)
        check_result = check_result_timeout
    except requests.exceptions.ConnectionError:
        proxy_error = 'Failed to connect to proxy {}.'.format(proxy)
        check_result = check_result_failed
    except Exception as e:
        proxy_error = e
        check_result = check_result_exception

    # If we've already encountered a problem, stop here.
    if proxy_error:
        return (proxy_error, check_result)

    # Evaluate response status code.
    login_status = login_response.status_code
    niantic_status = niantic_response.status_code

    if ptc_response:
        ptc_status = ptc_response.status_code
    else:
        ptc_status = 200

    banned_status_codes = [403, 409]

    if niantic_status == 200 and login_status == 200 and ptc_status == 200:
        log.debug('Proxy %s is ok.', proxy)
    elif (niantic_status in banned_status_codes or
          login_status in banned_status_codes or
          ptc_status in banned_status_codes):
        proxy_error = ('Proxy {} is banned. '
                       + 'Niantic: {}, '
                       + 'Login: {}, '
                       + 'PTC: {}.').format(proxy,
                                            niantic_status,
                                            login_status,
                                            ptc_status)
        check_result = check_result_banned
    else:
        proxy_error = ('Wrong status codes -'
                       + ' Niantic: {}, '
                       + ' login: {}, '
                       + ' PTC: {}.').format(niantic_status,
                                             login_status,
                                             ptc_status)
        check_result = check_result_wrong

    # Explicitly release connection back to the pool, because we don't need
    # or want to consume the content.
    login_response.close()
    niantic_response.close()
    if ptc_response:
        ptc_response.close()

    return (proxy_error, check_result)


def start_request_login(session, proxy, timeout):

    proxy_test_ptc_url = 'https://sso.pokemon.com/sso/login' \
                         '?service=https%3A%2F%2Fsso.pokemon.com' \
                         '%2Fsso%2Foauth2.0%2FcallbackAuthorize' \
                         '&locale=en_US'

    # Send request to pokemon.com.
    future_ptc = session.get(
        proxy_test_ptc_url,
        proxies={'http': proxy, 'https': proxy},
        timeout=timeout,
        headers={'Host': 'sso.pokemon.com',
                 'Connection': 'close',
                 'Accept': '*/*',
                 'User-Agent': 'pokemongo/0 CFNetwork/893.14.2 Darwin/17.3.0',
                 'Accept-Language': 'en-us',
                 'Accept-Encoding': 'br, gzip, deflate',
                 'X-Unity-Version': '2017.1.2f1'},
        background_callback=__proxy_check_completed,
        stream=True)

    return future_ptc


def start_request_niantic(session, proxy, timeout):
    proxy_test_url = 'https://pgorelease.nianticlabs.com/plfe/version'

    # Send request to nianticlabs.com.
    future_niantic = session.get(
        proxy_test_url,
        proxies={'http': proxy, 'https': proxy},
        timeout=timeout,
        headers={'Host': 'sso.pokemon.com',
                 'Connection': 'close',
                 'Accept': '*/*',
                 'User-Agent': 'pokemongo/0 CFNetwork/893.14.2 Darwin/17.3.0',
                 'Accept-Language': 'en-us',
                 'Accept-Encoding': 'br, gzip, deflate',
                 'X-Unity-Version': '2017.1.2f1'},
        background_callback=__proxy_check_completed,
        stream=True)

    return future_niantic


def start_request_ptc(session, proxy, timeout):
    proxy_test_ptc_url = 'https://club.pokemon.com/us/pokemon-trainer-club'

    # log.debug('Checking proxy: %s.', proxy)

    # Send request to pokemon.com.
    future_ptc = session.get(
        proxy_test_ptc_url,
        proxies={'http': proxy, 'https': proxy},
        timeout=timeout,
        headers={'Host': 'sso.pokemon.com',
                 'Connection': 'close',
                 'Accept': '*/*',
                 'User-Agent': 'pokemongo/0 CFNetwork/893.14.2 Darwin/17.3.0',
                 'Accept-Language': 'en-us',
                 'Accept-Encoding': 'br, gzip, deflate',
                 'X-Unity-Version': '2017.1.2f1'},
        background_callback=__proxy_check_completed,
        stream=True)

    return future_ptc


# Requests to send for testing, which returns futures for Niantic and PTC.
def start_request_futures(
        ptc_session, niantic_session, proxy, timeout, extra_request):

    log.debug('Checking proxy: %s.', proxy)

    # Send request to pokemon.com.
    future_login = start_request_login(ptc_session, proxy, timeout)

    # Send request to nianticlabs.com.
    future_niantic = start_request_niantic(niantic_session, proxy, timeout)

    # Send optional request to PTC account.
    future_ptc = None
    if extra_request:
        future_ptc = start_request_ptc(ptc_session, proxy, timeout)

    # Return futures.
    return (future_login, future_niantic, future_ptc)


# Check all proxies and return a working list with proxies.
def check_proxies(args, proxies, capture_failed_anon):

    working_proxies = []
    banned_proxies = []
    failed_proxies = []

    if not args.no_anonymous:
        proxies, failed = test_proxies(args, proxies)
        if capture_failed_anon:
            failed_proxies = list(failed)

    # Get the updated number of proxies.
    total_proxies = len(proxies)

    # Store counter per result type.
    check_results = [0] * (check_result_max + 1)

    # If proxy testing concurrency is set to automatic, use max.
    max_concurrency = args.max_concurrency

    if args.max_concurrency == 0:
        max_concurrency = total_proxies

    if max_concurrency >= 100:
        log.warning(
            "Starting proxy test for %d proxies with %d concurrency. " +
            "If this causes issues, consider lowering it.",
            total_proxies, max_concurrency)

    # Get persistent session per host.
    ptc_session = get_async_requests_session(
        args.retries,
        args.backoff_factor,
        max_concurrency)
    niantic_session = get_async_requests_session(
        args.retries,
        args.backoff_factor,
        max_concurrency)

    # List to hold background workers.
    proxy_queue = []
    working_proxies = []
    show_warnings = total_proxies <= 10

    log.info('Checking %d proxies with %d retries and %d sec timeout...',
             total_proxies, args.retries, args.timeout)

    if not args.verbose and not show_warnings:
        log.info('Enable -v to see proxy testing details.')

    # Start async requests & store futures.
    for proxy in proxies:
        future_login, future_niantic, future_ptc = start_request_futures(
            ptc_session,
            niantic_session,
            proxy,
            args.timeout,
            args.extra_request)

        proxy_queue.append((proxy, future_login, future_niantic, future_ptc))

    # Wait here until all items in proxy_queue are processed, so we have a list
    # of working proxies. We intentionally start all requests before handling
    # them so they can asynchronously continue in the background, even as we're
    # blocking to wait for one. The double loop is intentional.
    for proxy, future_login, future_niantic, future_ptc in proxy_queue:
        error, result = get_proxy_test_status(proxy,
                                              future_login,
                                              future_niantic,
                                              future_ptc)

        check_results[result] += 1

        if error:
            # Decrease output amount if there are a lot of proxies.
            if show_warnings:
                log.warning(error)
            else:
                log.debug(error)

            if result == check_result_banned:
                banned_proxies.append(proxy)
            else:
                failed_proxies.append(proxy)
        else:
            working_proxies.append(proxy)

    other_fails = (check_results[check_result_failed] +
                   check_results[check_result_wrong] +
                   check_results[check_result_exception] +
                   check_results[check_result_empty])

    log.info('Checked %d proxies. Working: %d, banned: %d,'
             + ' timeout: %d, other fails: %d.',
             total_proxies, len(working_proxies),
             check_results[check_result_banned],
             check_results[check_result_timeout],
             other_fails)

    return working_proxies, banned_proxies, failed_proxies
