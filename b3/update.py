import json
import os
import re
import string
import sys
import urllib.request as urllib2
from distutils import version
from time import sleep

import b311
import b311.config

## url from where we can get the latest B3 version number
URL_B3_LATEST_VERSION = 'http://master.bigbrotherbot.net/version.json'

## supported update channels
UPDATE_CHANNEL_STABLE = 'stable'
UPDATE_CHANNEL_BETA = 'beta'
UPDATE_CHANNEL_DEV = 'dev'


class B3version(version.StrictVersion):
    """
    Version numbering for BigBrotherBot.
    Compared to version.StrictVersion this class allows version numbers such as :
        1.0dev
        1.0dev2
        1.0d3
        1.0a
        1.0a
        1.0a34
        1.0b
        1.0b1
        1.0b3
        1.9.0dev7.daily21-20121004
    And make sure that any 'dev' prerelease is inferior to any 'alpha' prerelease
    """
    version = None
    prerelease = None
    build_num = None

    version_re = re.compile(r'''^
(?P<major>\d+)\.(?P<minor>\d+)   # 1.2
(?:\. (?P<patch>\d+))?           # 1.2.45
(?P<prerelease>                  # 1.2.45b2
  (?P<tag>a|b|dev)
  (?P<tag_num>\d+)?
)?                                                                     # 1.2.45b2.devd94d71a-20120901
((?P<daily>\.daily(?P<build_num>\d+?))|(?P<dev>\.dev(?P<dev_num>\w+?)) # 1.2.45b2.daily4-20120901
)?
(?:-(?P<date>20\d\d\d\d\d\d))?   # 1.10.0dev-20150215
$''', re.VERBOSE)
    prerelease_order = {'dev': 0, 'a': 1, 'b': 2}

    def parse(self, vstring):
        """
        Parse the version number from a string.
        :param vstring: The version string
        """
        match = self.version_re.match(vstring)
        if not match:
            raise ValueError("invalid version number '%s'" % vstring)

        major = match.group('major')
        minor = match.group('minor')

        patch = match.group('patch')
        if patch:
            self.version = tuple(map(string.atoi, [major, minor, patch]))
        else:
            self.version = tuple(map(string.atoi, [major, minor]) + [0])

        prerelease = match.group('tag')
        prerelease_num = match.group('tag_num')
        if prerelease:
            self.prerelease = (prerelease, string.atoi(prerelease_num if prerelease_num else '0'))
        else:
            self.prerelease = None

        daily_num = match.group('build_num')
        if daily_num:
            self.build_num = string.atoi(daily_num if daily_num else '0')
        else:
            self.build_num = None

    def __cmp__(self, other):
        """
        Compare current object with another one.
        :param other: The other object
        """
        if isinstance(other, str):
            other = B3version(other)

        compare = cmp(self.version, other.version)
        if compare != 0:
            return compare

        # we have to compare prerelease
        compare = self.__cmp_prerelease(other)
        if compare != 0:
            return compare

        # we have to compare build num
        return self.__cmp_build(other)

    def __cmp_prerelease(self, other):
        # case 1: neither has prerelease; they're equal
        # case 2: self has prerelease, other doesn't; other is greater
        # case 3: self doesn't have prerelease, other does: self is greater
        # case 4: both have prerelease: must compare them!
        if not self.prerelease and not other.prerelease:
            return 0
        elif self.prerelease and not other.prerelease:
            return -1
        elif not self.prerelease and other.prerelease:
            return 1
        elif self.prerelease and other.prerelease:
            return cmp((self.prerelease_order[self.prerelease[0]], self.prerelease[1]),
                       (self.prerelease_order[other.prerelease[0]], other.prerelease[1]))

    def __cmp_build(self, other):
        # case 1: neither has build_num; they're equal
        # case 2: self has build_num, other doesn't; other is greater
        # case 3: self doesn't have build_num, other does: self is greater
        # case 4: both have build_num: must compare them!
        if not self.build_num and not other.build_num:
            return 0
        elif self.build_num and not other.build_num:
            return -1
        elif not self.build_num and other.build_num:
            return 1
        elif self.build_num and other.build_num:
            return cmp(self.build_num, other.build_num)


def getDefaultChannel(currentVersion):
    """
    Return an update channel according to the current B3 version.
    :param currentVersion: The B3 version to use to compute the update channel
    """
    if currentVersion is None:
        return UPDATE_CHANNEL_STABLE

    version_re = re.compile(r'''^
(?P<major>\d+)\.(?P<minor>\d+)   # 1.2
(?:\. (?P<patch>\d+))?           # 1.2.45
(?P<prerelease>                  # 1.2.45b2
  (?P<tag>a|b|dev)
  (?P<tag_num>\d+)?
)?
(?P<daily>                       # 1.2.45b2.daily4-20120901
    \.daily(?P<build_num>\d+?)
    (?:-20\d\d\d\d\d\d)?
)?
$''', re.VERBOSE)

    m = version_re.match(currentVersion)
    if not m or m.group('tag') is None:
        return UPDATE_CHANNEL_STABLE
    elif m.group('tag').lower() in ('dev', 'a'):
        return UPDATE_CHANNEL_DEV
    elif m.group('tag').lower() == 'b':
        return UPDATE_CHANNEL_BETA


def checkUpdate(currentVersion, channel=None, singleLine=True, showErrormsg=False, timeout=4):
    """
    Check if an update of B3 is available.
    """
    if channel is None:
        channel = getDefaultChannel(currentVersion)

    if not singleLine:
        sys.stdout.write("checking for updates... \n")

    message = None
    errormessage = None

    try:
        json_data = urllib2.urlopen(URL_B3_LATEST_VERSION, timeout=timeout).read()
        version_info = json.loads(json_data)
    except IOError as e:
        if hasattr(e, 'reason'):
            errormessage = '%s' % e.reason
        elif hasattr(e, 'code'):
            errormessage = 'error code: %s' % e.code
        else:
            errormessage = '%s' % e
    except Exception as e:
        errormessage = repr(e)
    else:
        latestVersion = None
        try:
            channels = version_info['B3']['channels']
        except KeyError as err:
            errormessage = repr(err) + '. %s' % version_info
        else:
            if channel not in channels:
                errormessage = "unknown channel '%s': expecting (%s)" % (channel, ', '.join(channels.keys()))
            else:
                try:
                    latestVersion = channels[channel]['latest-version']
                except KeyError as err:
                    errormessage = repr(err) + '. %s' % version_info

        if not errormessage:
            try:
                latestUrl = version_info['B3']['channels'][channel]['url']
            except KeyError:
                latestUrl = "www.bigbrotherbot.net"

            not singleLine and sys.stdout.write('latest B3 %s version is %s\n' % (channel, latestVersion))
            _lver = B3version(latestVersion)
            _cver = B3version(currentVersion)
            if _cver < _lver:
                if singleLine:
                    message = 'update available (v%s : %s)' % (latestVersion, latestUrl)
                else:
                    message = """
                 _\|/_
                 (o o)    {version:^21}
         +----oOO---OOo-----------------------+
         |                                    |
         |                                    |
         | A newer version of B3 is available |
         |                                    |
         | {url:^34} |
         |                                    |
         +------------------------------------+

        """.format(version=latestVersion, url=latestUrl)

    if errormessage and showErrormsg:
        return errormessage
    elif message:
        return message
    else:
        return None


class DBUpdate(object):
    """
    Console database update procedure.
    """

    def __init__(self, config=None):
        """
        Object constructor.
        :param config: The B3 configuration file path
        """
        if config:
            # use the specified configuration file
            config = b311.getAbsolutePath(config, True)
            if not os.path.isfile(config):
                console_exit('ERROR: configuration file not found (%s).\n'
                             'Please visit %s to create one.' % (config, B3_CONFIG_GENERATOR))
        else:
            # search a configuration file
            for p in ('b311.%s', 'conf/b311.%s', 'b311/conf/b311.%s',
                      os.path.join(HOMEDIR, 'b311.%s'), os.path.join(HOMEDIR, 'conf', 'b311.%s'),
                      os.path.join(HOMEDIR, 'b311', 'conf', 'b311.%s'), '@b311/conf/b311.%s'):
                for e in ('ini', 'cfg', 'xml'):
                    path = b311.getAbsolutePath(p % e, True)
                    if os.path.isfile(path):
                        print("Using configuration file: %s" % path)
                        config = path
                        sleep(3)
                        break

            if not config:
                console_exit('ERROR: could not find any valid configuration file.\n'
                             'Please visit %s to create one.' % B3_CONFIG_GENERATOR)
        try:
            self.config = b311.config.MainConfig(b311.config.load(config))
            if self.config.analyze():
                raise b311.config.ConfigFileNotValid("Fuck")
        except b311.config.ConfigFileNotValid:
            console_exit('ERROR: configuration file not valid (%s).\n'
                         'Please visit %s to generate a new one.' % (config, B3_CONFIG_GENERATOR))

    def run(self):
        """
        Run the DB update
        """
        clearscreen()
        print("""
                        _\|/_
                        (o o)    {:>32}
                +----oOO---OOo----------------------------------+
                |                                               |
                |             UPDATING B3 DATABASE              |
                |                                               |
                +-----------------------------------------------+

        """.format('B3 : %s' % b311.__version__))

        input("press any key to start the update...")

        def _update_database(storage, update_version):
            """
            Update a B3 database.
            :param storage: the initialized storage module
            :param update_version: the update version
            """
            if B3version(b311.__version__) >= update_version:
                sql = b311.getAbsolutePath('@b311/sql/%s/b311-update-%s.sql' % (storage.protocol, update_version))
                if os.path.isfile(sql):
                    try:
                        print('>>> updating database to version %s' % update_version)
                        sleep(.5)
                        storage.queryFromFile(sql)
                    except Exception as err:
                        print('WARNING: could not update database properly: %s' % err)
                        sleep(3)

        dsn = self.config.get('b311', 'database')
        dsndict = splitDSN(dsn)
        database = getStorage(dsn, dsndict, StubParser())

        _update_database(database, '1.3.0')
        _update_database(database, '1.6.0')
        _update_database(database, '1.7.0')
        _update_database(database, '1.8.1')
        _update_database(database, '1.9.0')
        _update_database(database, '1.10.0')

        console_exit('B3 database update completed!')


from b311 import B3_CONFIG_GENERATOR, HOMEDIR
from b311.functions import console_exit, splitDSN, clearscreen
from b311.parser import StubParser
from b311.storage import getStorage
