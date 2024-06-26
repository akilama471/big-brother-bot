# coding: UTF-8
#
# BigBrotherBot(B3) (www.bigbrotherbot.net)
# Copyright (C) 2012 Thomas LEVEIL
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
# 1.0  - 2012-10-19 - feature complete - need live testing with real gameplay
# 1.1  - 2012-10-19 - recognize a new type of game event when a player dies by crashing a vehicule
#                   - add getNextMap()
#                   - fix changeMap()
#                   - improve getMapsSoundingLike()
# 1.2  - 2012-10-20 - fix: wasn't saving player names to database
#                   - change: reduce maximum line length in chat (or it would be truncated by the server)
# 1.3  - 2012-10-22 - fix: kill events so stats and xlrstats plugin can do their job
#                   - change: make getMap() crash proof
# 1.4  - 2012-10-26 - new: recognize game type from map names
# 1.5  - 2012-11-14 - new: get the game server hostname by querying the game server on its Source Query port
# 1.6  - 2014-05-02 - rewrote import statements
#                   - correctly declare getPlayerPings() method to match the one in Parser class
#                   - removed some warnings
#                   - fixed client retrieval in kick, ban and tempban function
# 1.7  - 2014-07-18 - updated parser to comply with the new getWrap implementation
# 1.8  - 2014-08-15 - produce EVT_CLIENT_KICK when a player gets kicked from the server
# 1.9  - 2014-08-29 - syntax cleanup
# 1.10 - 2015-04-16 - uniform class variables (dict -> variable)

import logging
import re
import sys
import time
import traceback

from Queue import Empty
from Queue import Full
from Queue import Queue

from b311 import TEAM_BLUE
from b311 import TEAM_RED
from b311 import TEAM_UNKNOWN
from b311 import version as b3_version
from b311.clients import Clients
from b311.decorators import GameEventRouter
from b311.functions import getStuffSoundingLike
from b311.functions import minutesStr
from b311.functions import time2minutes
from b311.lib.sourcelib import SourceQuery
from b311.parser import Parser
from b311.parsers.ravaged.ravaged_rcon import RavagedServer
from b311.parsers.ravaged.ravaged_rcon import RavagedServerCommandError
from b311.parsers.ravaged.ravaged_rcon import RavagedServerCommandTimeout
from b311.parsers.ravaged.ravaged_rcon import RavagedServerError
from b311.parsers.ravaged.ravaged_rcon import RavagedServerNetworkError
from b311.parsers.ravaged.rcon import Rcon as RavagedRcon

__author__ = 'Courgette'
__version__ = '1.10'

ger = GameEventRouter()

# how long should the bot try to connect to the Frostbite server before giving out (in second)
GAMESERVER_CONNECTION_WAIT_TIMEOUT = 600

"""
Note for developers
===================
The Ravaged game events do not have any cid info but always a guid.
In this parser the guid will be used in place of the cid.
"""

TEAM_RESISTANCE = TEAM_BLUE
TEAM_SCAVENGERS = TEAM_RED


class RavagedParser(Parser):
    """
    Ravaged B3 parser.
    """
    gameName = 'ravaged'
    privateMsg = True
    OutputClass = RavagedRcon
    PunkBuster = None

    game_event_queue = Queue(400)
    game_event_queue_stop_token = object()

    _line_length = 180
    _line_color_prefix = ''
    _private_message_color = '00FC48'
    _say_color = 'F2C880'
    _saybig_color = 'FC00E2'
    _use_color_codes = False

    _serverConnection = None
    _nbConsecutiveConnFailure = 0

    # this game engine does not support color code, so we
    # need this property in order to get stripColors working
    _reColor = re.compile(r'(\^[0-9])')

    ####################################################################################################################
    #                                                                                                                  #
    #   PARSER INITIALIZATION                                                                                          #
    #                                                                                                                  #
    ####################################################################################################################

    def __new__(cls, *args, **kwargs):
        patch_b3()
        return Parser.__new__(cls)

    def startup(self):
        """
        Called after the parser is created before run().
        Overwrite this in parsers for anything you need to initialize you parser with.
        """
        self.clients.newClient('Server', guid='Server', name='Server', hide=True, pbid='Server', team=TEAM_UNKNOWN)

        # add game specific events
        # TODO check if have game specific events

        if not self._publicIp:
            self.warning("server/public_ip not set in the main config file: cannot query the game server for info")
        else:
            ## read game server info and store as much of it in self.game which is an instance of the b311.game.Game class
            self.info("Querying game server Source Query at %s:%s" % (self._publicIp, self._port))
            try:
                sq = SourceQuery.SourceQuery(self._publicIp, self._port, timeout=10)
                serverinfo = sq.info()
                self.debug("server info : %r", serverinfo)
                if 'map' in serverinfo:
                    self.game.mapName = serverinfo['map'].lower()
                if 'steamid' in serverinfo:
                    self.game.steamid = serverinfo['steamid']
                if 'hostname' in serverinfo:
                    self.game.sv_hostname = serverinfo['hostname']
                if 'maxplayers' in serverinfo:
                    self.game.sv_maxclients = serverinfo['maxplayers']
            except Exception as err:
                self.error("could not retrieve server info using Source Query protocol", exc_info=err)

    def pluginsStarted(self):
        """
        Called once all plugins were started.
        Handy if some of them must be monkey-patched.
        """
        pass

    ####################################################################################################################
    #                                                                                                                  #
    #   GAME EVENTS HANDLERS                                                                                           #
    #   Read http://www.2dawn.com/wiki/index.php?title=Ravaged_RCon                                                    #
    #                                                                                                                  #
    ####################################################################################################################

    @ger.gameEvent(r'''^"(?P<name>.*?)<(?P<guid>\d+)><(?P<team>.*)>" connected, address "(?P<ip>\S+)"$''')
    def on_connected(self, name, guid, team, ip):
        # "<12312312312312312><>" connected, address "192.168.0.1"
        player = self.getClientOrCreate(guid, name=None)
        if ip:
            player.ip = ip
            player.save()
            # self.getClientOrCreate will send the EVT_CLIENT_CONNECT event

    @ger.gameEvent(r'''^"(?P<name>.+?)<(?P<guid>\d+)><(?P<team>.*)>" entered the game$''')
    def on_entered_the_game(self, name, guid, team):
        # "courgette<12312312312312312><0>" entered the game
        return self.getEvent('EVT_CLIENT_JOIN', client=self.getClientOrCreate(guid, name, team))

    @ger.gameEvent(r'''^"(?P<name>.+?)<(?P<guid>\d+)><(?:.*)>" joined team "(?P<new_team>.+)"$''')
    def on_joined_team(self, name, guid, new_team):
        # "courgette<12312312312312312><1>" joined team "1"
        self.getClientOrCreate(guid, name, new_team)

    @ger.gameEvent(r'''^"(?P<name>.+?)<(?P<guid>\d+)><(?P<team>.*)>"\s*disconnected$''')
    def on_disconnected(self, name, guid, team):
        # "courgette<12312312312312312><0>"disconnected
        player = self.getClientOrCreate(guid, name, team)
        player.disconnect()

    @ger.gameEvent(r'''^Server say "(?P<data>.*)"$''')
    def on_server_say(self, data):
        # Server say "Admin: B\xb311: www.bigbrotherbot.net (b311) v1.10dev [nt] [Coco] [ONLINE]"
        pass

    @ger.gameEvent(r'''^Server say_team "(?P<text>.*)" to team "(?P<team>.*)"$''')
    def on_server_say(self, text, team):
        # Server say_team "f00" to team "1"
        pass

    @ger.gameEvent(r'''^Loading map "(?P<map_name>\S+)"$''')
    def on_loading_map(self, map_name):
        # Loading map "CTR_Derelict"
        self.set_map(map_name)

    @ger.gameEvent(r'''^Round started$''')
    def on_round_started(self):
        # Round started
        self.game.startRound()
        return self.getEvent('EVT_GAME_ROUND_START', data=self.game)

    @ger.gameEvent(r'''^Round finished, winning team is "(?P<team>.*)"$''')
    def on_round_finished(self, team):
        # Round finished, winning team is "0"
        return self.getEvent('EVT_GAME_ROUND_END', data=self.getTeam(team))

    @ger.gameEvent(
        r'''^"(?P<name>.+?)<(?P<guid>\d+)><(?P<team>.*)>" say "(?:<FONT COLOR='#[A-F0-9]+'> )?(?P<text>.+)"$''')
    def on_say(self, name, guid, team, text):
        # "courgette<12312312312312312><1>" say "<FONT COLOR='#FF0000'> hi"
        return self.getEvent('EVT_CLIENT_SAY', data=text, client=self.getClientOrCreate(guid, name, team))

    @ger.gameEvent(
        r'''^"(?P<name>.+?)<(?P<guid>\d+)><(?P<team>.*)>" say_team "\(Team\) (?:<FONT COLOR='#[A-F0-9]+'> )?(?P<text>.+)"$''')
    def on_say_team(self, name, guid, team, text):
        # "courgette<12312312312312312><1>" say_team "(Team) <FONT COLOR='#66CCFF'> hi team"
        return self.getEvent('EVT_CLIENT_TEAM_SAY', data=text, client=self.getClientOrCreate(guid, name, team))

    @ger.gameEvent(
        r'''^"(?P<name>.+?)<(?P<guid>\d+)><(?P<team>.*)>" committed suicide with "(?P<weapon>\S+)"$''',
        r'''^"(?P<name>.+?)<(?P<guid>\d+)><(?P<team>.*)>" killed  with (?P<weapon>\S+)$''')
    def on_committed_suicide(self, name, guid, team, weapon):
        # "courgette<12312312312312312><1>" committed suicide with "R_DmgType_M26Grenade"
        player = self.getClientOrCreate(guid, name, team)
        return self.getEvent('EVT_CLIENT_SUICIDE', data=(100, weapon, 'body'), client=player, target=player)

    @ger.gameEvent(
        r'''^"(?P<name_a>.+?)<(?P<guid_a>\d+)><(?P<team_a>.*)>" killed "(?P<name_b>.+?)<(?P<guid_b>\d+)><(?P<team_b>.*)>" with "?(?P<weapon>\S+?)"?$''')
    def on_killed(self, name_a, guid_a, team_a, name_b, guid_b, team_b, weapon):
        # "Name1<11111111111111><0>" killed "Name2<2222222222222><1>" with "the_weapon"
        attacker = self.getClientOrCreate(guid_a, name_a, team_a)
        victim = self.getClientOrCreate(guid_b, name_b, team_b)
        event_type = 'EVT_CLIENT_KILL'
        if attacker.team == victim.team:
            event_type = 'EVT_CLIENT_KILL_TEAM'
        return self.getEvent(event_type, data=(100, weapon, 'body'), client=attacker, target=victim)

    @ger.gameEvent(r'''^\((?P<ip>.+):(?P<port>\d+) has connected remotely\)$''')
    def on_connected_remotely(self, ip, port):
        # (127.0.0.1:3508 has connected remotely)
        pass

    @ger.gameEvent(r'''^RCon:\((?P<login>\S+)(?P<ip>.+):(?P<port>\d+) has disconnected from RCon\)$''')
    def on_disconnected_from_rcon(self, login, ip, port):
        # RCon:(Admin127.0.0.1:3508 has disconnected from RCon)
        pass

    # ------------------------------------- /!\  this one must be the last /!\ --------------------------------------- #

    @ger.gameEvent(r'''^(?P<data>.+)$''')
    def on_unknown_line(self, data):
        """
        Catch all lines that were not handled.
        """
        self.warning("unhandled log line : %s : please report this on the B3 forums" % data)

    ####################################################################################################################
    #                                                                                                                  #
    #   B3 PARSER INTERFACE IMPLEMENTATION                                                                             #
    #                                                                                                                  #
    ####################################################################################################################

    def getPlayerList(self):
        """
        Query the game server for connected players.
        return a dict having players' id for keys and Client objects as values
        """
        return self.getplayerlist()

    def authorizeClients(self):
        """
        For all connected players, fill the client object with properties allowing to find
        the user in the database (usualy guid, or punkbuster id, ip) and call the
        Client.auth() method
        """
        # no need as all game log lines have the client guid
        pass

    def sync(self):
        """
        For all connected players returned by self.getPlayerList(), get the matching Client
        object from self.clients (with self.clients.getByCID(cid) or similar methods) and
        look for inconsistencies. If required call the client.disconnect() method to remove
        a client from self.clients.
        """
        plist = self.getPlayerList()
        mlist = {}
        for cid, client in plist.iteritems():
            if client:
                mlist[cid] = client
        return mlist

    def say(self, msg, *args):
        """
        Broadcast a message to all players.
        :param msg: The message to be broadcasted
        """
        if msg and len(msg.strip()):
            msg = msg % args
            msg = "%s <FONT COLOR='#%s'> %s" % (self.msgPrefix, self._say_color, msg)
            for line in self.getWrap(msg):
                self.output.write("say <FONT COLOR='#%s'> %s" % (self._say_color, line))

    def saybig(self, msg, *args):
        """
        Broadcast a message to all players in a way that will catch their attention.
        :param msg: The message to be broadcasted
        """
        if msg and len(msg.strip()):
            msg = msg % args
            msg = "%s <FONT COLOR='#%s'> %s" % (self.msgPrefix, self._saybig_color, msg)
            for line in self.getWrap(msg):
                self.output.write("say <FONT COLOR='#%s'> %s" % (self._saybig_color, line))

    def message(self, client, msg, *args):
        """
        Display a message to a given client
        :param client: The client to who send the message
        :param msg: The message to be sent
        """
        if msg and len(msg.strip()):
            msg = msg % args
            msg = "%s <FONT COLOR='#%s'> %s" % (self.msgPrefix, self._private_message_color, msg)
            for line in self.getWrap(msg):
                self.output.write(
                    "playersay %s <FONT COLOR='#%s'> %s" % (client.cid, self._private_message_color, line))

    def kick(self, client, reason='', admin=None, silent=False, *kwargs):
        """
        Kick a given client.
        :param client: The client to kick
        :param reason: The reason for this kick
        :param admin: The admin who performed the kick
        :param silent: Whether or not to announce this kick
        """
        self.debug('kick reason: [%s]' % reason)
        if isinstance(client, basestring):
            clients = self.clients.getByMagic(client)
            if len(clients) != 1:
                return
            else:
                client = clients[0]

        if admin:
            variables = self.getMessageVariables(client=client, reason=reason, admin=admin)
            fullreason = self.getMessage('kicked_by', variables)
        else:
            variables = self.getMessageVariables(client=client, reason=reason)
            fullreason = self.getMessage('kicked', variables)

        fullreason = self.stripColors(fullreason)
        reason = self.stripColors(reason)

        self.do_kick(client, reason)
        if not silent and fullreason != '':
            self.say(fullreason)

        self.queueEvent(self.getEvent('EVT_CLIENT_KICK', data={'reason': reason, 'admin': admin}, client=client))
        client.disconnect()

    def ban(self, client, reason='', admin=None, silent=False, *kwargs):
        """
        Ban a given client.
        :param client: The client to ban
        :param reason: The reason for this ban
        :param admin: The admin who performed the ban
        :param silent: Whether or not to announce this ban
        """
        if client.hide:
            return

        self.debug('BAN : client: %s, reason: %s', client, reason)
        if isinstance(client, basestring):
            clients = self.clients.getByMagic(client)
            if len(clients) != 1:
                return
            else:
                client = clients[0]

        if admin:
            variables = self.getMessageVariables(client=client, reason=reason, admin=admin)
            fullreason = self.getMessage('banned_by', variables)
        else:
            variables = self.getMessageVariables(client=client, reason=reason)
            fullreason = self.getMessage('banned', variables)

        fullreason = self.stripColors(fullreason)
        reason = self.stripColors(reason)

        self.do_ban(client, reason)
        if admin:
            admin.message('Banned: %s (@%s) has been added to banlist' % (client.exactName, client.id))

        if not silent and fullreason != '':
            self.say(fullreason)

        self.queueEvent(self.getEvent("EVT_CLIENT_BAN", {'reason': reason, 'admin': admin}, client))

    def unban(self, client, reason='', admin=None, silent=False, *kwargs):
        """
        Unban a client.
        :param client: The client to unban
        :param reason: The reason for the unban
        :param admin: The admin who unbanned this client
        :param silent: Whether or not to announce this unban
        """
        if client.hide:  # exclude bots
            return

        self.debug('UNBAN: name: %s, ip: %s, guid: %s' % (client.name, client.ip, client.guid))
        self.do_unban(client)
        self.verbose('UNBAN: removed guid (%s) from banlist' % client.guid)
        if admin:
            admin.message('Unbanned: removed %s guid from banlist' % client.exactName)

    def tempban(self, client, reason='', duration=2, admin=None, silent=False, *kwargs):
        """
        Tempban a client.
        :param client: The client to tempban
        :param reason: The reason for this tempban
        :param duration: The duration of the tempban
        :param admin: The admin who performed the tempban
        :param silent: Whether or not to announce this tempban
        """
        if client.hide:  # exclude bots
            return

        self.debug('TEMPBAN : client: %s, duration: %s, reason: %s', client, duration, reason)
        if isinstance(client, basestring):
            clients = self.clients.getByMagic(client)
            if len(clients) != 1:
                return
            else:
                client = clients[0]

        if admin:
            banduration = minutesStr(duration)
            variables = self.getMessageVariables(client=client, reason=reason, admin=admin, banduration=banduration)
            fullreason = self.getMessage('temp_banned_by', variables)
        else:
            banduration = minutesStr(duration)
            variables = self.getMessageVariables(client=client, reason=reason, banduration=banduration)
            fullreason = self.getMessage('temp_banned', variables)

        fullreason = self.stripColors(fullreason)
        reason = self.stripColors(reason)

        self.do_tempban(client, duration, reason)

        if not silent and fullreason != '':
            self.say(fullreason)

        self.queueEvent(
            self.getEvent("EVT_CLIENT_BAN_TEMP", {'reason': reason, 'duration': duration, 'admin': admin}, client))

    def getMap(self):
        """
        Return the current map/level name.
        """
        re_current_map = re.compile(r"^0 (?P<map_name>\S+)$", re.MULTILINE)
        rv = self.output.write("getmaplist false")
        if rv:
            m = re.search(re_current_map, rv)
            if m:
                current_map = m.group('map_name')
                self.set_map(current_map)
                return current_map

    def getNextMap(self):
        """
        Return the next map in the map rotation list.
        """
        re_next_map = re.compile(r"^1 (?P<map_name>\S+)$", re.MULTILINE)
        m = re.search(re_next_map, self.output.write("getmaplist false"))
        if m:
            return m.group('map_name')

    def getMaps(self):
        """
        Return the available maps/levels name.
        """
        # TODO should call getavailablemaps but does not seem to work
        return self.getmaplist()

    def rotateMap(self):
        """
        Load the next map/level
        """
        self.output.write("nextmap")

    def changeMap(self, map_name):
        """
        Load a given map/level
        Return a list of suggested map names in cases it fails to recognize the map that was provided
        """
        rv = self.getMapsSoundingLike(map_name)
        if isinstance(rv, basestring):
            self.output.write("addmap %s 1" % rv)
            self.output.write("nextmap")
        else:
            return rv

    def getPlayerPings(self, filter_client_ids=None):
        """
        Returns a dict having players' id for keys and players' ping for values
        """
        rv = {}
        for cid, client in self.getplayerlist().items():
            data = getattr(client, 'ping', None)
            if data:
                rv[cid] = data
        return rv

    def getPlayerScores(self):
        """
        Returns a dict having players' id for keys and players' scores for values
        """
        rv = {}
        for cid, client in self.getplayerlist().items():
            data = getattr(client, 'score', None)
            if data:
                rv[cid] = data
        return rv

    def inflictCustomPenalty(self, penalty_type, client, reason=None, duration=None, admin=None, data=None):
        """
        Called if b311.admin.penalizeClient() does not know a given penalty type.
        Overwrite this to add customized penalties for your game like 'slap', 'nuke',
        'mute', 'kill' or anything you want.
        /!\ This method must return True if the penalty was inflicted.
        """
        # TODO see if inflictCustomPenalty is applicable
        pass

    ####################################################################################################################
    #                                                                                                                  #
    #   OTHER METHODS                                                                                                  #
    #                                                                                                                  #
    ####################################################################################################################

    def getClientOrCreate(self, guid, name, team=None):
        """
        Return an already connected client by searching the clients guid index or create a new client.
        """
        client = self.clients.getByCID(guid)
        if client is None:
            client = self.clients.newClient(guid, guid=guid, team=TEAM_UNKNOWN)
            client.last_update_time = time.time()
            client.save()
            client.ping = None
            client.score = None
            client.kills = None
            client.deaths = None
        if name:
            old_name = client.name
            client.name = name
            if old_name != name:
                client.save()
        if team:
            client.team = self.getTeam(team)
        return client

    def getTeam(self, team):
        """
        Convert Ravaged team id to B3 team numbers
        """
        if not team:
            return TEAM_UNKNOWN
        elif team == "0":
            return TEAM_SCAVENGERS
        elif team == "1":
            return TEAM_RESISTANCE
        else:
            self.debug("Unexpected team id : %s" % team)
            return TEAM_UNKNOWN

    def do_kick(self, client, reason=None):
        if not client.cid:
            self.warning("Trying to kick %s which has no cid" % client)
        else:
            if reason:
                self.output.write('kick %s "%s"' % (client.cid, reason))
            else:
                self.output.write("kick %s" % client.cid)

    def do_ban(self, client, reason=None):
        # kickban <steamid> reason <days>
        # Fenix: duration was 356d (converted into int to remove a warning)
        self.do_tempban(client, duration=525600, reason=reason)

    def do_tempban(self, client, duration=2, reason=None):
        # kickban <steamid> reason <days>
        days = float(time2minutes(duration)) / 1440.0
        if reason:
            self.output.write('kickban %s "%s" %s' % (client.guid, reason, days))
        else:
            self.output.write('kickban %s "%s"' % (client.guid, days))

    def do_unban(self, client):
        # unban <steamid>
        self.output.write('unban %s' % client.guid)

    def getmaplist(self):
        """
        Return the available maps on the server, even if not in the map rotation list
        """
        re_maps = re.compile(r"^(?P<index>\d+) (?P<map_name>\S+)$", re.MULTILINE)
        response = []
        raw_maps = self.output.write("getmaplist false")
        if raw_maps:
            for m in re.finditer(re_maps, raw_maps):
                response.append(m.group('map_name'))
        return response

    def getMapsSoundingLike(self, mapname):
        """
        Return a valid mapname.
        If no exact match is found, then return close candidates as a list
        """
        supportedMaps = self.getmaplist()
        wanted_map = mapname.lower()
        if wanted_map in [m.lower() for m in supportedMaps]:
            return wanted_map

        matches = getStuffSoundingLike(wanted_map, supportedMaps)
        if len(matches) == 1:
            # one match, get the map id
            return matches[0]
        else:
            # multiple matches, provide suggestions
            return matches

    def getplayerlist(self):
        """
        - query the server for connected players' info
        - create Client objects for never seen before players
        - update Client objects info
        - return a dict<cid, Client>
        """
        rv = self.output.write("getplayerlist")
        clients = {}
        if rv:
            re_player = re.compile(r'^(?P<name>.+?) '
                                   r'(?P<score>-?\d+) pts '
                                   r'(?P<kills>-?\d+):'
                                   r'(?P<deaths>-?\d+) '
                                   r'(?P<ping>-?\d+)ms steamid: '
                                   r'(?P<guid>\d+)$', re.MULTILINE)

            for m in re.finditer(re_player, rv):
                client = self.getClientOrCreate(m.group('guid'), m.group('name'))
                client.score = int(m.group('score'))
                client.kills = int(m.group('kills'))
                client.deaths = int(m.group('deaths'))
                client.ping = int(m.group('ping'))
                clients[client.cid] = client

        return clients

    def set_map(self, new_map):
        """
        update self.game with mapName and gameType
        :param new_map: new map name
        :return: None
        """
        self.game.mapName = new_map
        parts = new_map.split('_', 1)
        if len(parts) == 2:
            self.game.gameType = parts[0]

    ####################################################################################################################
    #                                                                                                                  #
    #   B3 PARSER GAME EVENT THREAD STUFF                                                                              #
    #                                                                                                                  #
    ####################################################################################################################

    def run(self):
        """
        Main worker thread for B3.
        """
        self.bot('Start listening...')

        self.screen.write('Startup complete : B3 is running! Let\'s get to work!\n\n')
        self.screen.write('If you run into problems check your B3 log file for more information\n')
        self.screen.flush()
        self.updateDocumentation()

        ## the block below can activate additional logging for the RavagedServer class
        #        ravagedServerLogger = logging.getLogger("RavagedServer")
        #        for handler in logging.getLogger('output').handlers:
        #            ravagedServerLogger.addHandler(handler)
        #        ravagedServerLogger.setLevel(logging.getLogger('output').level)

        ravagedDispatcher_logger = logging.getLogger("RavagedDispatcher")
        ravagedDispatcher_logger.setLevel(logging.WARNING)
        for handler in logging.getLogger('output').handlers:
            ravagedDispatcher_logger.addHandler(handler)
        ravagedDispatcher_logger.setLevel(logging.WARNING)

        while self.working:
            if not self._serverConnection or not self._serverConnection.connected:
                try:
                    self.setup_game_connection()
                except RavagedServerError, err:
                    self.error("RavagedServerError %s" % err)
                    continue
                except IOError, err:
                    self.error("IOError: %s" % err)
                    continue
                except Exception as err:
                    self.error(err)
                    self.exitcode = 220
                    break

            try:
                added, expire, packet = self.game_event_queue.get(timeout=5)
                if packet is self.game_event_queue_stop_token:
                    break
                self.route_game_event(packet)
            except Empty:
                pass
            except RavagedServerCommandError, err:
                # it does not matter from the parser perspective if Frostbite command failed
                # (timeout or bad reply)
                self.warning(err)
            except RavagedServerNetworkError, e:
                # the connection to the frostbite server is lost
                self.warning(e)
                self.close_game_connection()
            except Exception as e:
                self.error("Unexpected error: please report this on the B3 forums")
                self.error(e)
                self.error('%s: %s', e, traceback.extract_tb(sys.exc_info()[2]))
                # unexpected exception, better close the frostbite connection
                self.close_game_connection()

        self.info("Stop listening for Ravaged events")
        # exiting B3
        with self.exiting:
            # If !die or !restart was called, then  we have the lock only after parser.handleevent Thread releases it
            # and set self.working = False and this is one way to get this code is executed.
            # Else there was an unhandled exception above and we end up here. We get the lock instantly.
            self.output.frostbite_server = None

            # The Frostbite connection is running its own thread to communicate with the game server. We need to tell
            # this thread to stop.
            self.close_game_connection()

            # If !die was called, exitcode have been set to 222
            # If !restart was called, exitcode have been set to 221
            # In both cases, the SystemExit exception that triggered exitcode to be filled with an exit value was
            # caught. Now that we are sure that everything was gracefully stopped, we can re-raise the SystemExit
            # exception.
            if self.exitcode:
                sys.exit(self.exitcode)

    def setup_game_connection(self):
        self.info('Connecting to Ravaged server ...')
        if self._serverConnection:
            self.close_game_connection()
        try:
            self._serverConnection = RavagedServer(self._rconIp, self._rconPort, self._rconPassword)
        except RavagedServerNetworkError, err:
            self.error(err)
            time.sleep(10)

        timeout = GAMESERVER_CONNECTION_WAIT_TIMEOUT + time.time()
        while time.time() < timeout and (not self._serverConnection or not self._serverConnection.connected):
            self.close_game_connection()
            time.sleep(10)
            self.info("Retrying to connect to game server...")
            try:
                self._serverConnection = RavagedServer(self._rconIp, self._rconPort, self._rconPassword)
            except RavagedServerNetworkError, err:
                self.error(err)

        if self._serverConnection is None:
            self.error("Could not connect to Ravaged server")
            self.close_game_connection()
            self.shutdown()
            raise SystemExit()

        # listen for incoming game server events
        self._serverConnection.subscribe(self.handle_game_event)

        try:
            self._serverConnection.auth()
        except RavagedServerCommandTimeout, err:
            self.warning(err)
            try:
                self._serverConnection.auth()
            except RavagedServerCommandTimeout, err:
                self.error(err)
                self._serverConnection.stop()
                self._serverConnection = None
                raise err

        self._serverConnection.command('enableevents true')

        # setup Rcon
        self.output.set_server_connection(self._serverConnection)
        self.queueEvent(self.getEvent('EVT_GAMESERVER_CONNECT'))
        self.say('%s ^2[ONLINE]' % b3_version)
        self.getMap()
        self.clients.sync()

    def close_game_connection(self):
        try:
            self._serverConnection.stop()
        except Exception:
            pass
        self._serverConnection = None

    def handle_game_event(self, ravaged_event):
        if not self.working:
            self.verbose("Dropping Ravaged event %r" % ravaged_event)
        self.console(ravaged_event)
        try:
            self.game_event_queue.put((self.time(), self.time() + 10, ravaged_event), timeout=2)
        except Full:
            self.error("Ravaged event queue full, dropping event %r" % ravaged_event)

    def route_game_event(self, game_event):
        hfunc, param_dict = ger.getHandler(game_event)
        if hfunc:
            self.verbose2("Calling %s%r" % (hfunc.func_name, param_dict))
            event = hfunc(self, **param_dict)
            if event:
                self.queueEvent(event)

    def shutdown(self):
        self.game_event_queue.put((None, None, self.game_event_queue_stop_token))
        Parser.shutdown(self)


########################################################################################################################
##                                                                                                                    ##
##  APPLY PATCHES TO B3 CORE MODULES                                                                                  ##
##                                                                                                                    ##
########################################################################################################################

def patch_b3():
    # disable the authorizing timer that come by default with the b311.clients.Clients class
    Clients.authorizeClients = lambda *args, **kwargs: None
