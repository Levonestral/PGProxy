# PGProxy
Proxy checker that verifies if proxies are able to connect to PokemonGo servers.

## Credits
 - Originally forked from [Neskks proxy checker](https://github.com/neskk/PoGo-Proxies).
 - Proxy testing code came mostly from [RocketMap](http://github.com/RocketMap/RocketMap).
 - Inspiration and ideas from [SenorKarlos PGPool](https://github.com/SenorKarlos/PGPool).
 - Inspiration and ideas from [a-moss/Proxy Scraper for Pokemon Go](https://gist.github.com/a-moss/1578eb07b2570b5d97d85b1e93e81cc8s)

## Feature Support
 * Python 2
 * Multi-threaded proxy checker
 * HTTP and SOCKS protocols
 * Test if proxies are anonymous
 * Output final proxy list in several formats

## Requirements
 * Python 2
 * configargparse
 * requests
 * urllib3
 * BeautifulSoup 4


## Installation

Run the usual `pip install -r requirements.txt`.

If planning on using the server, you will also need to setup a MySQL database. 

## Usage

Two options are available. 

 * **Manual Tool** Allows you to manually scrape and validate proxies from various locations.
 * **ProxyPool** Runs as a server that can be queried to obtain a list of valid proxies. The service runs scrapes and validations automatically as per configuration options.

# Manual Tool

```
python start.py [-h] [-v] (-f PROXY_FILE | -s) [-m {http,socks}]
                [-o OUTPUT_FILE] [-r RETRIES] [-t TIMEOUT] [-pj PROXY_JUDGE]
                [-na] [-nt | -er] [-bf BACKOFF_FACTOR] [-mc MAX_CONCURRENCY]
                [-bs BATCH_SIZE] [-l LIMIT] [-ic IGNORE_COUNTRY]
                [--proxychains | --kinancity | --clean]

optional arguments:
  -h, --help            show this help message and exit
  -v, --verbose         Run in the verbose mode.
  -f PROXY_FILE, --proxy-file PROXY_FILE
                        Filename of proxy list to verify.
  -s, --scrap           Scrap webpages for proxy lists.
  -m {http,socks}, --mode {http,socks}
                        Specify which proxy mode to use for testing. Default
                        is "socks".
  -o OUTPUT_FILE, --output-file OUTPUT_FILE
                        Output filename for working proxies.
  -r RETRIES, --retries RETRIES
                        Number of attempts to check each proxy.
  -t TIMEOUT, --timeout TIMEOUT
                        Connection timeout. Default is 5 seconds.
  -pj PROXY_JUDGE, --proxy-judge PROXY_JUDGE
                        URL for AZenv script used to test proxies.
  -na, --no-anonymous   Disable anonymous proxy test.
  -nt, --no-test        Disable PTC/Niantic proxy test.
  -er, --extra-request  Make an extra request to validate PTC.
  -bf BACKOFF_FACTOR, --backoff-factor BACKOFF_FACTOR
                        Factor (in seconds) by which the delay until next
                        retry will increase.
  -mc MAX_CONCURRENCY, --max-concurrency MAX_CONCURRENCY
                        Maximum concurrent proxy testing requests.
  -bs BATCH_SIZE, --batch-size BATCH_SIZE
                        Check proxies in batches of limited size.
  -l LIMIT, --limit LIMIT
                        Stop tests when we have enough good proxies.
  -ic IGNORE_COUNTRY, --ignore-country IGNORE_COUNTRY
                        Ignore proxies from countries in this list.
  --proxychains         Output in proxychains-ng format.
  --kinancity           Output in Kinan City format.
  --clean               Output proxy list without protocol.
```


# PGProxy:

## Setting up PGProxy

1. Copy `config/config.ini.sample` to `config/config.ini`.
2. Adjust settings for listening host:port and your database in `config.ini`.
3. Adjust any additional settings to meet your requirements in `config.ini`.
4. Run ProxyPool with `python proxy_pool.py`.

You can also provide a custom configuration file using `-cf`:

`python proxy_pool.py -cf config/config.ini`

## Importing Existing Proxies

After setting up configuration, you can import proxies listed in a text file:

```
127.0.0.1:12345
127.0.0.2:12345
127.0.0.3:12345
```

Then using the `--proxy-file` argument, pass in the text file:

`python proxy_pool.py -cf config/config.ini --proxy-file import_proxies.txt`

This will then validate each proxy provided and import them into the database. Their state (working, banned, failed) will be recorded during the import.

# API

Let's assume ProxyPool runs at the default URL `http://localhost:4343`. Then the following requests are possible:

## Requesting Proxies

**Method: GET**
**URL:** `http://localhost:4343/proxy/request`

If no parameter is provided, only `working` proxies will be returned. You can combine the parameters to get a mixed list of proxies.

Parameter | Required | Default | Description
--------- | -------- | ------- | -----------
`working` | No  | true | Return proxies that have been determined as working.
`banned`  | Yes | true | Return proxies that are NPC/Niantic banned.
`failed` | No  | true | Return proxies that recently had network connection issues. (even if temporary)
`invalid` | No  | true | Return proxies that have been determined invalid due to reaching their "maximum" retry count.
`format`  | No | json | Value should be: `txt`, `list` or `json`. If not provided, will default to JSON.

### Response Format

**JSON**
Returns a JSON object or a list of JSON objects representing proxies and their state:
```
[
	{
		"url": "http://127.0.0.1:12345",
		"working": false,
		"banned": true,
		"failed": true
	}
]
```

**TXT**
Returns a list of just the proxies, each on their own line:
```
127.0.0.1:12345
127.0.0.2:12345
127.0.0.3:12345
```

**LIST**
Returns the proxies as a list structure:
```
[127.0.0.1:12345, 127.0.0.2:12345, 127.0.0.3:12345]
```

## Updating Proxies

**Method: POST**
**URL:** `http://localhost:4343/proxy/update`

Request data is either a single JSON object or a list of JSON objects that contain one or more attributes to set on the proxy. If you send more than one attribute, the proxy will be flagged with each one, so be careful what you send.

Attribute | Required | Description
--------- | -----------
`url` | Yes | The proxy URL to update.
`working` | No | Update proxy as working.
`banned`  | No | Update proxy as banned.
`failed` | No | Update proxy as failed.
`invalid` | No | Update proxy as invalid.
