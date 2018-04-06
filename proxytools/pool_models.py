#!/usr/bin/python
# -*- coding: utf-8 -*-

import logging
import time
from datetime import datetime
from threading import Lock

from peewee import DeleteQuery, DateTimeField, CharField, SmallIntegerField, \
    IntegerField, BooleanField, InsertQuery, fn, OperationalError
from playhouse.flask_utils import FlaskDB
# from playhouse.migrate import migrate, MySQLMigrator
from playhouse.pool import PooledMySQLDatabase
from playhouse.shortcuts import RetryOperationalError


log = logging.getLogger('pgproxy')

flaskDb = FlaskDB()

request_lock = Lock()

db_schema_version = 1


class MyRetryDB(RetryOperationalError, PooledMySQLDatabase):
    pass


# Reduction of CharField to fit max length inside 767 bytes for utf8mb4 charset
class Utf8mb4CharField(CharField):
    def __init__(self, max_length=191, *args, **kwargs):
        self.max_length = max_length
        super(CharField, self).__init__(*args, **kwargs)


class Version(flaskDb.Model):
    key = Utf8mb4CharField()
    val = SmallIntegerField()

    class Meta:
        primary_key = False


class ProxyPool(flaskDb.Model):

    url = Utf8mb4CharField(primary_key=True)

    # proxy health
    working = BooleanField(null=False, default=False)
    invalid = BooleanField(null=False, default=False)
    banned = BooleanField(null=False, default=False)
    banned_retry_count = IntegerField(null=False, default=0)
    failed = BooleanField(null=False, default=False)
    failed_retry_count = IntegerField(null=False, default=0)
    last_modified = DateTimeField(index=True, default=datetime.now)

    def serialize(self):
        return {
            'url': self.url,
            'working': self.working,
            'invalid': self.invalid,
            'banned': self.banned,
            'failed': self.failed,
            'last_modified': self.last_modified
        }


def init_database(args, app):
    log.info('Connecting to MySQL database on %s:%i...',
             args.db_host, args.db_port)
    db = MyRetryDB(
        args.db_name,
        user=args.db_user,
        password=args.db_pass,
        host=args.db_host,
        port=args.db_port,
        max_connections=args.db_max_connections,
        stale_timeout=300,
        charset='utf8mb4')
    app.config['DATABASE'] = db
    flaskDb.init_app(app)
    db.connect()

    if not ProxyPool.table_exists():
        create_tables(db)
        InsertQuery(Version, {Version.key: 'schema_version',
                              Version.val: db_schema_version}).execute()
        old_schema_version = db_schema_version
    elif not Version.table_exists():
        old_schema_version = 1
    else:
        old_schema_version = Version.get(Version.key == 'schema_version').val
    if old_schema_version < db_schema_version:
        migrate_database(db, old_schema_version)

    # Last, fix database encoding
    verify_table_encoding(args, db)

    log.info('MySQL database ready.')

    return db


def verify_table_encoding(args, db):
    with db.execution_context():
        cmd_sql = '''
            SELECT table_name FROM information_schema.tables WHERE
            table_collation != "utf8mb4_unicode_ci"
            AND table_schema = "{}";
            '''.format(args.db_name)
        change_tables = db.execute_sql(cmd_sql)

        if change_tables.rowcount > 0:
            log.info('Changing collation and charset on database.')
            cmd_sql = '''ALTER DATABASE {} CHARACTER SET
                utf8mb4 COLLATE utf8mb4_unicode_ci'''.format(args.db_name)
            db.execute_sql(cmd_sql)

            log.info('Changing collation and charset on {} tables.'
                     .format(change_tables.rowcount))
            db.execute_sql('SET FOREIGN_KEY_CHECKS=0;')
            for table in change_tables:
                log.debug('Changing collation and charset on table {}.'
                          .format(table[0]))
                cmd_sql = '''ALTER TABLE {} CONVERT TO CHARACTER SET utf8mb4
                    COLLATE utf8mb4_unicode_ci;'''.format(str(table[0]))
                db.execute_sql(cmd_sql)
            db.execute_sql('SET FOREIGN_KEY_CHECKS=1;')


def migrate_database(db, old_ver):

    log.info('Detected database version {}, updating to {}...'
             .format(old_ver, db_schema_version))
    # migrator = MySQLMigrator(db)

    # Version.update(val=db_schema_version).where(
    #    Version.key == 'schema_version').execute()
    # log.info("Done migrating database.")


def migrate_varchar_columns(db, *fields):
    stmts = []
    cols = []
    table = None
    for field in fields:
        if isinstance(field, Utf8mb4CharField):
            if table is None:
                table = field.model_class._meta.db_table
            elif table != field.model_class._meta.db_table:
                log.error(
                    "Can only migrate varchar cols of same table: {} vs. {}"
                    .format(table, field.model_class._meta.db_table))
            column = field.db_column
            cols.append(column)
            max_length = field.max_length
            stmt = "CHANGE COLUMN {} {} VARCHAR({}) ".format(
                column, column, max_length)
            stmt += "DEFAULT NULL" if field.null else "NOT NULL"
            stmts.append(stmt)

    log.info("Converting VARCHAR columns {} on table {}"
             .format(', '.join(cols), table))
    db.execute_sql("ALTER TABLE {} {};"
                   .format(table, ', '.join(stmts)))


def db_updater(args, q, db):
    # The forever loop.
    while True:
        try:

            while True:
                try:
                    flaskDb.connect_db()
                    break
                except Exception as e:
                    log.warning('%s... Retrying...', repr(e))
                    time.sleep(5)

            # Loop the queue.
            while True:
                data = q.get()
                update_proxy(args, data, db)
                q.task_done()

                # Helping out the GC.
                del data

        except Exception as e:
            log.exception('Exception in db_updater: %s', repr(e))
            time.sleep(5)


def create_tables(db):
    db.connect()

    tables = [ProxyPool, Version]
    for table in tables:
        if not table.table_exists():
            log.info('Creating table: %s', table.__name__)
            db.create_tables([table], safe=True)
        else:
            log.debug('Skipping table %s, it already exists.', table.__name__)
    db.close()


def update_proxy(args, data, db):
    with db.atomic():
        try:
            proxy, created = ProxyPool.get_or_create(url=data['url'])
            metadata = {}
            for key, value in data.items():
                if not key.startswith('_'):
                    setattr(proxy, key, value)
                else:
                    metadata[key] = value
            proxy.last_modified = datetime.now()
            proxy.save()
            if args.log_db_updates:
                log.info("Processed update for {}".format(proxy.url))
        except Exception as e:
            # If there is a constraint error, dump the data and don't retry.
            # Unrecoverable error strings:
            unrecoverable = ['constraint', 'has no attribute',
                             'peewee.IntegerField object at']
            has_unrecoverable = filter(
                lambda x: x in str(e), unrecoverable)
            if has_unrecoverable:
                log.warning('%s. Data is:', repr(e))
                log.warning(data.items())
            else:
                log.warning('%s... Retrying...', repr(e))
                time.sleep(1)


def working_proxy_count():

    query = (ProxyPool
             .select(fn.Count(ProxyPool.url+0).alias('count')).dicts()
             .where(ProxyPool.working == 1))

    # We need a total count. Use reduce() instead of sum() for O(n)
    # instead of O(2n) caused by list comprehension.
    total = reduce(lambda x, y: x + y['count'], query, 0)

    return total


def get_all_proxies():

    # Return all proxies EXCEPT invalid one's.
    # Invalid may or may not be purged later, regardless, we don't want them.
    query = (ProxyPool.select().where(ProxyPool.invalid != 1))

    proxies = []
    for p in query:
        proxies.append(p)

    return proxies


def get_working_proxies():

    query = (ProxyPool.select().where(ProxyPool.working == 1))

    proxies = []
    for p in query:
        proxies.append(p)

    return proxies


def get_filtered_proxies(working, banned, failed, invalid):

    expression = (ProxyPool.url != '')
    first = True

    if working:
        if first:
            expression &= (ProxyPool.working == 1)
        else:
            expression |= (ProxyPool.working == 1)
        first = False

    if banned:
        if first:
            expression &= (ProxyPool.banned == 1)
        else:
            expression |= (ProxyPool.banned == 1)
        first = False

    if failed:
        if first:
            expression &= (ProxyPool.failed == 1)
        else:
            expression |= (ProxyPool.failed == 1)
        first = False

    if invalid:
        if first:
            expression &= (ProxyPool.invalid == 1)
        else:
            expression |= (ProxyPool.invalid == 1)

    query = (ProxyPool.select().where(expression))

    proxies = []
    for p in query:
        proxies.append(p)

    return proxies


def purge_invalid_proxies():

    # Set a limit of 15 to ensure we don't grab more than we can handle.
    limit = 15
    urls = []

    try:
        query = (ProxyPool
                 .select()
                 .where(ProxyPool.invalid == 1)
                 .limit(limit))
        for p in query:
            urls.append(p.url)
        if len(urls) > 0:
            log.info('Retrieved proxies for deletion: {}'.format(urls))
            result = DeleteQuery(ProxyPool).where(
                ProxyPool.url << urls).execute()
            log.info('Deleted {} invalid proxies.'.format(result))
    except OperationalError as e:
        log.error('Failed purge invalid proxies query: {}'.format(e))


def add_proxy_direct(url, working, banned, failed):

    proxy, created = ProxyPool.get_or_create(url=url)
    proxy.working = working
    proxy.invalid = False
    proxy.banned = banned
    proxy.failed = failed
    proxy.last_modified = datetime.now()

    if working:
        proxy.banned_retry_count = 0
        proxy.failed_retry_count = 0

    proxy.save()
    log.info("add_proxy for {}. working: {}, failed: {}, banned: {}"
             .format(url, working, failed, banned))
    return created
