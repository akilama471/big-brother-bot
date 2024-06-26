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
# 27/06/2009 - 1.1.1 - xlr8or       - added CLIENT_ACTION event
# 11/11/2009 - 1.1.2 - Courgette    - minor transparent changes to the code
# 30/03/2011 - 1.1.3 - SGT          - add EVT_CLIENT_UNBAN
# 06/06/2011 - 1.1.4 - Courgette    - add EventsStats class
# 26/03/2011 - 1.2   - Courgette    - add event EVT_GAME_MAP_CHANGE
# 27/08/2012 - 1.3   - Courgette    - add getKey(event_id) method
# 19/02/2013 - 1.4   - Courgette    - fix EventsStats.dumpStats which would fail if called before any event was seen
#                                   - make EventsStats.dumpStats computations abort if B3 log level lower than required
#                                     to display the results
# 15/07/2013 - 1.5   - Courgette    - add events EVT_CLIENT_WARN and EVT_CLIENT_NOTICE
# 15/04/2014 - 1.5.1 - Fenix        - PEP8 coding standards
# 21/07/2014 - 1.6   - Fenix        - syntax cleanup
# 09/08/2014 - 1.7   - Courgette    - define new event EVT_CLIENT_TEAM_CHANGE2
# 09/03/2014 - 1.8   - Fenix        - added EVT_PLUGIN_ENABLED, EVT_PLUGIN_DISABLED, EVT_PLUGIN_LOADED,
#                                     EVT_PLUGIN_UNLOADED
# 19/03/2015 - 1.8.1 - Fenix        - fixed test for membership using 'if not X in Y' (now use 'if X not in Y')
# 04/05/2015 - 1.8.2 - Fenix        - removed reference to global variable b311.console on b311.console.time(): using
#                                     time.time() instead (changed after reply mode removal)

__author__ = 'ThorN, xlr8or, Courgette'
__version__ = '1.8.2'

import re
import time
from collections import deque
from logging import DEBUG

from b311.decorators import Memoize
from b311.functions import meanstdv
from b311.output import VERBOSE


class Events:

    def __init__(self):
        """
        Object constructor.
        """
        self._events = {}
        self._eventNames = {}

        self.loadEvents((
            ('EVT_EXIT', 'Program Exit'),
            ('EVT_STOP', 'Stop Process'),
            ('EVT_UNKNOWN', 'Unknown Event'),
            ('EVT_CUSTOM', 'Custom Event'),
            ('EVT_PLUGIN_ENABLED', 'Plugin Enabled'),
            ('EVT_PLUGIN_DISABLED', 'Plugin Disabled'),
            ('EVT_PLUGIN_LOADED', 'Plugin Loaded'),
            ('EVT_PLUGIN_UNLOADED', 'Plugin Unloaded'),
            ('EVT_CLIENT_SAY', 'Say'),
            ('EVT_CLIENT_TEAM_SAY', 'Team Say'),
            ('EVT_CLIENT_SQUAD_SAY', 'Squad Say'),
            ('EVT_CLIENT_PRIVATE_SAY', 'Private Message'),
            ('EVT_CLIENT_CONNECT', 'Client Connect'),
            ('EVT_CLIENT_AUTH', 'Client Authenticated'),
            ('EVT_CLIENT_DISCONNECT', 'Client Disconnect'),
            ('EVT_CLIENT_UPDATE', 'Client Update'),
            ('EVT_CLIENT_KILL', 'Client Kill'),
            ('EVT_CLIENT_GIB', 'Client Gib'),
            ('EVT_CLIENT_GIB_TEAM', 'Client Gib Team'),
            ('EVT_CLIENT_GIB_SELF', 'Client Gib Self'),
            ('EVT_CLIENT_SUICIDE', 'Client Suicide'),
            ('EVT_CLIENT_KILL_TEAM', 'Client Team Kill'),
            ('EVT_CLIENT_DAMAGE', 'Client Damage'),
            ('EVT_CLIENT_DAMAGE_SELF', 'Client Damage Self'),
            ('EVT_CLIENT_DAMAGE_TEAM', 'Client Team Damage'),
            ('EVT_CLIENT_JOIN', 'Client Join Team'),
            ('EVT_CLIENT_NAME_CHANGE', 'Client Name Change'),
            ('EVT_CLIENT_TEAM_CHANGE', 'Client Team Change'),  # provides only the new team
            ('EVT_CLIENT_TEAM_CHANGE2', 'Client Team Change 2'),  # provides the previous and new team
            ('EVT_CLIENT_ITEM_PICKUP', 'Client Item Pickup'),
            ('EVT_CLIENT_ACTION', 'Client Action'),
            ('EVT_CLIENT_KICK', 'Client Kicked'),
            ('EVT_CLIENT_BAN', 'Client Banned'),
            ('EVT_CLIENT_BAN_TEMP', 'Client Temp Banned'),
            ('EVT_CLIENT_UNBAN', 'Client Unbanned'),
            ('EVT_CLIENT_WARN', 'Client Warned'),
            ('EVT_CLIENT_NOTICE', 'Client given a notice'),
            ('EVT_GAME_ROUND_START', 'Game Round Start'),
            ('EVT_GAME_ROUND_END', 'Game Round End'),
            ('EVT_GAME_WARMUP', 'Game Warmup'),
            ('EVT_GAME_EXIT', 'Game Exit'),
            ('EVT_GAME_MAP_CHANGE', 'map changed'),
        ))

    def createEvent(self, key, name=None):
        """
        Create an event.
        :param key: The event key
        :param name: An optional name to associate to the event
        """
        g = globals()

        try:
            _id = self._events[key] = g[key]
        except KeyError:
            _id = self._events[key] = len(self._events) + 1

        if name:
            self._eventNames[_id] = name
        else:
            self._eventNames[_id] = 'Unnamed (%s)' % key

        g[key] = _id
        return _id

    def getId(self, key):
        """
        Return an event ID given its key.
        :param key: The event key
        """
        if re.match('^[0-9]+$', str(key)):
            return int(key)
        else:
            try:
                return self._events[key]
            except KeyError:
                return None

    @Memoize
    def getKey(self, event_id):
        """
        Get the key of a given event ID.
        :param event_id: The event ID
        """
        matching_keys = [k for k, v in self._events.iteritems() if v == event_id]
        if not len(matching_keys):
            raise KeyError('could not find any B3 event with ID %s' % event_id)
        assert len(matching_keys) == 1, 'expecting only one event key per event ID: %r' % matching_keys
        return matching_keys[0]

    def getName(self, key):
        """
        Return an event name given its key.
        :param key: The event key
        """
        try:
            return self._eventNames[self.getId(key)]
        except KeyError:
            return 'Unknown (%s)' % key

    def loadEvents(self, events):
        """
        Load default events.
        :param events: A collection of Event tuples
        """
        for k, n in events:
            self.createEvent(k, n)

    def _get_events(self):
        """
        Return the Event dict.
        """
        return self._events

    events = property(_get_events)


class Event(object):

    def __init__(self, type, data, client=None, target=None):
        """
        Object constructor.
        :param type: The event ID
        :param data: Event data
        :param client: The client source of this event
        :param target: The target of this event
        """
        self.time = int(time.time())
        self.type = type
        self.data = data
        self.client = client
        self.target = target

    def __str__(self):
        return "Event<%s>(%r, %s, %s)" % (eventManager.getKey(self.type), self.data, self.client, self.target)


class EventsStats(object):

    def __init__(self, console, max_samples=100):
        """
        Object constructor.
        :param console: The console class instance
        :param max_samples: The size of the event queue
        """
        self.console = console
        self._max_samples = max_samples
        self._handling_timers = {}
        self._queue_wait = deque(maxlen=max_samples)

    def add_event_handled(self, plugin_name, event_name, milliseconds_elapsed):
        """
        Add an event to the dict of handled ones.
        :param plugin_name: The name of the plugin which handled the event
        :param event_name: The event name
        :param milliseconds_elapsed: The amount of milliseconds necessary to handle the event
        """
        if plugin_name not in self._handling_timers:
            self._handling_timers[plugin_name] = {}
        if event_name not in self._handling_timers[plugin_name]:
            self._handling_timers[plugin_name][event_name] = deque(maxlen=self._max_samples)
        self._handling_timers[plugin_name][event_name].append(milliseconds_elapsed)
        self.console.verbose2("%s event handled by %s in %0.3f ms", event_name, plugin_name, milliseconds_elapsed)

    def add_event_wait(self, milliseconds_wait):
        """
        Add delay to the event processing.
        :param milliseconds_wait: The amount of milliseconds to wait
        """
        self._queue_wait.append(milliseconds_wait)

    def dumpStats(self):
        """
        Print event stats in the log file.
        """
        if self.console.log.isEnabledFor(VERBOSE):
            for plugin_name, plugin_timers in self._handling_timers.iteritems():
                for event_name, event_timers in plugin_timers.iteritems():
                    mean, stdv = meanstdv(event_timers)
                    if len(event_timers):
                        self.console.verbose("%s %s : (ms) min(%0.1f), max(%0.1f), mean(%0.1f), "
                                             "stddev(%0.1f)", plugin_name, event_name, min(event_timers),
                                             max(event_timers), mean, stdv)

        if self.console.log.isEnabledFor(DEBUG):
            mean, stdv = meanstdv(self._queue_wait)
            if len(self._queue_wait):
                self.console.debug("Events waiting in queue stats : (ms) min(%0.1f), max(%0.1f), mean(%0.1f), "
                                   "stddev(%0.1f)", min(self._queue_wait), max(self._queue_wait), mean, stdv)


class VetoEvent(Exception):
    """
    Raised to cancel event processing.
    """
    pass


eventManager = Events()
