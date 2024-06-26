#
# BigBrotherBot(B3) (www.bigbrotherbot.net)
# Copyright (C) 2005 Michael "ThorN" Thornton
#
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.
#
# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE. See the
# GNU General Public License for more details.
#
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA 02110-1301 USA
#
# CHANGELOG
#
# 1.3               - add FakeConsole.saybig(msg)
#                   - FakeConsole.write() do not fail when arg is not a string
# 1.4  - 2010/11/01 - improve FakeStorage implementation
# 1.5  - 2010/11/21 - FakeConsole event mechanism does not involve a Queue anymore as this class is meant to test one
#                     plugin at a time there is no need for producer/consumer pattern. This speeds up tests and
#                     simplifies the use of a debugger. Also tests do not neet time.sleep() to make sure the events
#                     were handled before checking results and moving on (unittest friendly)
# 1.6  - 2010/11/21 - remove more time.sleep()
#                   - add message_history for FakeClient which allow to test if a client was sent a message afterward
# 1.7  - 2011/06/04 - replace FakeStorage with DatabaseStorage("sqlite://:memory:")
# 1.8  - 2011/06/06 - add ban()
#                   - change data format for EVT_CLIENT_BAN_TEMP and EVT_CLIENT_BAN events
# 1.9  - 2011/06/09 - FakeConsole now uses the logging module
# 1.10 - 2011/12/29 - fix issue with plugins' registered events when importing fakeconsole in different TestSuites
# 1.11 - 2012/04/15 - fix issue with message_history of FakeClient which was shared between instances
# 1.12 - 2014/07/16 - added admin key in EVT_CLIENT_KICK data dict when available
# 1.13 - 2014/08/05 - syntax cleanup
# 1.14 - 2014/09/06 - adapted FakeConsole to work with the new b311.ini configuration file format
# 1.15 - 2014/12/27 - new storage module initialization
# 1.16 - 2015/01/29 - make use of the new b311.config.MainConfig class
# 1.17 - 2015/02/07 - update write method to accept a socketTimeout=None parameter
# 1.18 - 2015/03/19 - removed deprecated usage of dict.has_key (us 'in dict' instead)

"""
This module make plugin testing simple. It provides you
with fakeConsole and joe which can be used to say commands
as if it where a player.
"""

__version__ = '1.18'

import logging
import re
import sys
import time
import traceback
from sys import stdout

import StringIO

import b311.events
import b311.output
import b311.parser
import b311.parsers.punkbuster
from b311.clients import Clients
from b311.cvar import Cvar
from b311.functions import splitDSN
from b311.game import Game
from b311.plugins.admin import AdminPlugin
from b311.storage.sqlite import SqliteStorage


class FakeConsole(b311.parser.Parser):
    """
    Console implementation to be used with automated tests.
    """
    Events = b311.events.eventManager = b311.events.Events()
    screen = stdout
    noVerbose = False
    input = None

    def __init__(self, config):
        """
        Object constructor.
        :param config: The main configuration file
        """
        b311.console = self
        self._timeStart = self.time()
        logging.basicConfig(level=b311.output.VERBOSE2, format='%(asctime)s\t%(levelname)s\t%(message)s')
        self.log = logging.getLogger('output')
        self.config = config

        if isinstance(config, b311.config.XmlConfigParser) or isinstance(config, b311.config.CfgConfigParser):
            self.config = b311.config.MainConfig(config)
        elif isinstance(config, b311.config.MainConfig):
            self.config = config
        else:
            self.config = b311.config.MainConfig(b311.config.load(config))

        self.storage = SqliteStorage("sqlite://:memory:", splitDSN("sqlite://:memory:"), self)
        self.storage.connect()
        self.clients = b311.clients.Clients(self)
        self.game = b311.game.Game(self, "fakeGame")
        self.game.mapName = 'ut4_turnpike'
        self.cvars = {}
        self._handlers = {}

        if not self.config.has_option('server', 'punkbuster') or self.config.getboolean('server', 'punkbuster'):
            self.PunkBuster = b311.parsers.punkbuster.PunkBuster(self)

        self.input = StringIO.StringIO()
        self.working = True

    def run(self):
        pass

    def queueEvent(self, event, expire=10):
        """
        Queue an event for processing.
        NO QUEUE, NO THREAD for faking speed up
        """
        if not hasattr(event, 'type'):
            return False
        elif event.type in self._handlers:
            self.verbose('Queueing event %s %s', self.Events.getName(event.type), event.data)
            self._handleEvent(event)
            return True
        return False

    def _handleEvent(self, event):
        """
        NO QUEUE, NO THREAD for faking speed up
        """
        if event.type == self.getEventID('EVT_EXIT') or event.type == self.getEventID('EVT_STOP'):
            self.working = False

        nomore = False
        for hfunc in self._handlers[event.type]:
            if not hfunc.isEnabled():
                continue
            elif nomore:
                break

            self.verbose('parsing event: %s: %s', self.Events.getName(event.type), hfunc.__class__.__name__)

            try:
                hfunc.parseEvent(event)
                time.sleep(0.001)
            except b311.events.VetoEvent:
                # plugin called for event hault, do not continue processing
                self.bot('Event %s vetoed by %s', self.Events.getName(event.type), str(hfunc))
                nomore = True
            except SystemExit, e:
                self.exitcode = e.code
            except Exception as msg:
                self.error('handler %s could not handle event %s: %s: %s %s',
                           hfunc.__class__.__name__, self.Events.getName(event.type),
                           msg.__class__.__name__, msg, traceback.extract_tb(sys.exc_info()[2]))

    def shutdown(self):
        """
        Shutdown B3 - needed to be changed in FakeConsole due to no thread for dispatching events.
        """
        try:
            if self.working and self.exiting.acquire():
                self.bot('shutting down...')
                self.working = False
                self._handleEvent(self.getEvent('EVT_STOP'))
                if self._cron:
                    self._cron.stop()
                self.bot('shutting down database connections...')
                self.storage.shutdown()
        except Exception as e:
            self.error(e)

    def getPlugin(self, name):
        if name == 'admin':
            return fakeAdminPlugin
        else:
            return b311.parser.Parser.getPlugin(self, name)

    def sync(self):
        return {}

    def getNextMap(self):
        return "ut4_theNextMap"

    def getPlayerScores(self):
        return {0: 5, 1: 4}

    def say(self, msg, *args):
        """
        Send text to the server.
        """
        print
        ">>> %s" % re.sub(re.compile('\^[0-9]'), '', msg % args).strip()

    def saybig(self, msg, *args):
        """
        Send bigtext to the server.
        """
        print
        "+++ %s" % re.sub(re.compile('\^[0-9]'), '', msg % args).strip()

    def write(self, msg, maxRetries=0, socketTimeout=None):
        """
        Send text to the console.
        """
        if type(msg) == str:
            print
            "### %s" % re.sub(re.compile('\^[0-9]'), '', msg).strip()
        else:
            # which happens for BFBC2
            print
            "### %s" % msg

    def writelines(self, lines):
        for line in lines:
            self.write(line)

    def authorizeClients(self):
        pass

    def ban(self, client, reason='', admin=None, silent=False, *kwargs):
        """
        Permban a client.
        """
        print
        '>>>permbanning %s (%s)' % (client.name, reason)
        self.queueEvent(self.getEvent('EVT_CLIENT_BAN', {'reason': reason, 'admin': admin}, client))
        client.disconnect()

    def tempban(self, client, reason='', duration=2, admin=None, silent=False, *kwargs):
        """
        Tempban a client.
        """
        from functions import minutesStr
        print
        '>>>tempbanning %s for %s (%s)' % (client.name, reason, minutesStr(duration))
        data = {'reason': reason, 'duration': duration, 'admin': admin}
        self.queueEvent(self.getEvent('EVT_CLIENT_BAN_TEMP', data=data, client=client))
        client.disconnect()

    def unban(self, client, reason='', admin=None, silent=False, *kwargs):
        """
        Unban a client.
        """
        print
        '>>>unbanning %s (%s)' % (client.name, reason)
        self.queueEvent(self.getEvent('EVT_CLIENT_UNBAN', reason, client))

    def kick(self, client, reason='', admin=None, silent=False, *kwargs):
        """
        Kick a client.
        """
        print
        '>>>kick %s for %s' % (client.name, reason)
        self.queueEvent(self.getEvent('EVT_CLIENT_KICK', data={'reason': reason, 'admin': admin}, client=client))
        client.disconnect()

    def message(self, client, text, *args):
        """
        Send a message to a client.
        """
        if client is None:
            self.say(text % args)
        elif client.cid is None:
            pass
        else:
            print
            "sending msg to %s: %s" % (client.name, re.sub(re.compile('\^[0-9]'), '', text % args).strip())

    def getCvar(self, key):
        """
        Get a server variable.
        """
        print
        "get cvar %s" % key
        return self.cvars.get(key)

    def setCvar(self, key, value):
        """
        Set a server variable.
        """
        print
        "set cvar %s" % key
        c = Cvar(name=key, value=value)
        self.cvars[key] = c


class FakeClient(b311.clients.Client):
    """
    Client object implementation to be used in automated tests.
    """
    console = None

    def __init__(self, console, **kwargs):
        """
        Object constructor.
        :param console: The console implementation
        """
        self.console = console
        self.message_history = []  # this allows unittests to check if a message was sent to the client
        b311.clients.Client.__init__(self, **kwargs)

    def clearMessageHistory(self):
        self.message_history = []

    def getMessageHistoryLike(self, needle):
        clean_needle = re.sub(re.compile('\^[0-9]'), '', needle).strip()
        for m in self.message_history:
            if clean_needle in m:
                return m
        return None

    def getAllMessageHistoryLike(self, needle):
        result = []
        clean_needle = re.sub(re.compile('\^[0-9]'), '', needle).strip()
        for m in self.message_history:
            if clean_needle in m:
                result.append(m)
        return result

    def message(self, msg, *args):
        msg = msg % args
        cleanmsg = re.sub(re.compile('\^[0-9]'), '', msg).strip()
        self.message_history.append(cleanmsg)
        print
        "sending msg to %s: %s" % (self.name, cleanmsg)

    def warn(self, duration, warning, keyword=None, admin=None, data=''):
        w = b311.clients.Client.warn(self, duration, warning, keyword=None, admin=None, data='')
        print(">>>>%s gets a warning : %s" % (self, w))

    def connects(self, cid):
        print
        "\n%s connects to the game on slot #%s" % (self.name, cid)
        self.cid = cid
        self.timeAdd = self.console.time()
        # self.console.clients.newClient(cid)
        clients = self.console.clients
        clients[self.cid] = self
        clients.resetIndex()

        self.console.debug('client connected: [%s] %s - %s (%s)', clients[self.cid].cid,
                           clients[self.cid].name, clients[self.cid].guid, clients[self.cid].data)

        self.console.queueEvent(self.console.getEvent('EVT_CLIENT_CONNECT', data=self, client=self))

        if self.guid:
            self.auth()
        elif not self.authed:
            clients._authorizeClients()

    def disconnects(self):
        print
        "\n%s disconnects from slot #%s" % (self.name, self.cid)
        self.console.clients.disconnect(self)
        self.cid = None
        self.authed = False
        self._pluginData = {}
        self.state = b311.STATE_UNKNOWN

    def says(self, msg):
        print
        "\n%s says \"%s\"" % (self.name, msg)
        self.console.queueEvent(self.console.getEvent('EVT_CLIENT_SAY', data=msg, client=self))

    def says2team(self, msg):
        print
        "\n%s says to team \"%s\"" % (self.name, msg)
        self.console.queueEvent(self.console.getEvent('EVT_CLIENT_TEAM_SAY', data=msg, client=self))

    def says2squad(self, msg):
        print
        "\n%s says to squad \"%s\"" % (self.name, msg)
        self.console.queueEvent(self.console.getEvent('EVT_CLIENT_SQUAD_SAY', data=msg, client=self))

    def says2private(self, msg):
        print
        "\n%s says privately \"%s\"" % (self.name, msg)
        self.console.queueEvent(self.console.getEvent('EVT_CLIENT_PRIVATE_SAY', data=msg, client=self, target=self))

    def damages(self, victim, points=34.0):
        print
        "\n%s damages %s for %s points" % (self.name, victim.name, points)
        if self == victim:
            eventkey = 'EVT_CLIENT_DAMAGE_SELF'
        elif self.team != b311.TEAM_UNKNOWN and self.team == victim.team:
            eventkey = 'EVT_CLIENT_DAMAGE_TEAM'
        else:
            eventkey = 'EVT_CLIENT_DAMAGE'

        data = (points, 1, 1, 1)
        self.console.queueEvent(self.console.getEvent(eventkey, data=data, client=self, target=victim))

    def kills(self, victim, weapon=1, hit_location=1):
        print
        "\n%s kills %s" % (self.name, victim.name)
        if self == victim:
            self.suicides()
            return
        elif self.team != b311.TEAM_UNKNOWN and self.team == victim.team:
            eventkey = 'EVT_CLIENT_KILL_TEAM'
        else:
            eventkey = 'EVT_CLIENT_KILL'

        data = (100, weapon, hit_location, 1)
        self.console.queueEvent(self.console.getEvent(eventkey, data=data, client=self, target=victim))

    def suicides(self):
        print
        "\n%s kills himself" % self.name
        data = (100, 1, 1, 1)
        self.console.queueEvent(self.console.getEvent('EVT_CLIENT_SUICIDE', data=data, client=self, target=self))

    def do_action(self, actiontype):
        self.console.queueEvent(self.console.getEvent('EVT_CLIENT_ACTION', data=actiontype, client=self))

    def trigger_event(self, type, data, target=None):
        print
        "\n%s trigger event %s" % (self.name, type)
        self.console.queueEvent(b311.events.Event(type, data, self, target))


#####################################################################################


print
"creating fakeConsole with @b311/conf/b311.distribution.ini"
fakeConsole = FakeConsole('@b311/conf/b311.distribution.ini')

print
"creating fakeAdminPlugin with @b311/conf/plugin_admin.ini"
fakeAdminPlugin = AdminPlugin(fakeConsole, '@b311/conf/plugin_admin.ini')
fakeAdminPlugin.onLoadConfig()
fakeAdminPlugin.onStartup()
