#!/usr/bin/python
# -*- coding: utf-8 -*-

import json
import logging
import urllib

log = logging.getLogger('pgproxy')


def parse_bool(val):
    if val is None:
        return False
    if val.lower() == 'yes' or val.lower() == 'true':
        return True
    return False


def validate_ip(ip):
    try:
        parts = ip.split('.')
        return len(parts) == 4 and all(0 <= int(part) < 256 for part in parts)
    except ValueError:
        # one of the 'parts' not convertible to integer.
        log.warning('Bad IP: %s', ip)
        return False
    except (AttributeError, TypeError):
        # `ip` isn't even a string
        log.warning('Weird IP: %s', ip)
        return False


def get_country_from_ip(geoip_url, ip):

    try:

        address = ip.replace("socks5://", "")
        address = address.replace("http://", "")
        address = address.replace("https://", "")
        address = address.split(":")[0]

        url = "http://www.freegeoip.net/json/{0}".format(address)
        locationInfo = json.loads(urllib.urlopen(url).read())
        return locationInfo['country_name'].lower()
        # print 'City: ' + locationInfo['city']
        # print 'Latitude: ' + str(locationInfo['latitude'])
        # print 'Longitude: ' + str(locationInfo['longitude'])
        # print 'IP: ' + str(locationInfo['ip'])
    except Exception as e:
        log.exception('Failed do geo locate IP from %s: %s.', url, e)
        return None


# Load proxies and return a list.
def load_proxies(filename, mode):
    proxies = []
    protocol = ''
    if mode == 'socks':
        protocol = 'socks5://'
    else:
        protocol = 'http://'

    # Load proxies from the file. Override args.proxy if specified.
    with open(filename) as f:
        for line in f:
            stripped = line.strip()

            # Ignore blank lines and comment lines.
            if len(stripped) == 0 or line.startswith('#'):
                continue

            if '://' in stripped:
                proxies.append(stripped)
            else:
                proxies.append(protocol + stripped)

        log.info('Loaded %d proxies.', len(proxies))

    return proxies


def export(filename, proxies, clean=False):
    with open(filename, 'w') as file:
        file.truncate()
        for proxy in proxies:
            if clean:
                proxy = proxy.split('://', 2)[1]

            file.write(proxy + '\n')


def export_proxychains(filename, proxies):
    with open(filename, 'w') as file:
        file.truncate()
        for proxy in proxies:
            # Split the protocol
            protocol, address = proxy.split('://', 2)
            # address = proxy.split('://')[1]
            # Split the port
            ip, port = address.split(':', 2)
            # Write to file
            file.write(protocol + ' ' + ip + ' ' + port + '\n')


def export_kinancity(filename, proxies):
    with open(filename, 'w') as file:
        file.truncate()
        file.write('[')
        for proxy in proxies:
            file.write(proxy + ',')

        file.seek(-1, 1)
        file.write(']\n')
