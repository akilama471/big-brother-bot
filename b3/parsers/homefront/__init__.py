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
# 2011-03-30 - 0.1   - first alpha test
# 2011-03-31 - 0.2   - remove try: catch: around the asyncore loop
# 2011-04-08 - 0.3   - do not create client without guid as name are not reliable alone
# 2011-04-08 - 0.4   - refactor get_player_list() and retrieve_playerlist() with cron interval
# 2011-04-08 - 0.5   - fix the "empty name in database bug" reported by Platanos
# 2011-04-09 - 0.6   - unban using UID if available
# 2011-04-16 - 0.6.1 - get_player_scores do not raise an exception when client has no kills attribute
# 2011-04-17 - 0.7.0 - implements sync()
#                    - fix bug with UID '0'
# 2011-04-18 - 0.7.1 - clear clients list on HF connection loss
# 2011-04-18 - 0.7.2 - remove color codes before sending each line in say, saybig and message
# 2011-04-25 - 0.8.0 - read game server info through Source Query Protocol
# 2011-05-03 - 0.9.0 - add custom penalty 'kill'
# 2011-05-20 - 0.9.1 - changes to support dedicated server version 0.0.0.201105181447
#                    - support [pm] using adminpm
#                    - changed adminbigsay and adminsay
# 2011-05-22 - 0.9.2 - do not rely on RETRIEVE BANLIST response to unban
# 2011-05-22 - 1.0   - fix onServerVotestart
# 2011-05-24 - 1.0.1 - "kill" penalty rcon command now uses SteamID instead of player name
# 2011-05-27 - 1.0.2 - kill event correctly parsed with player names or player SteamID
# 2011-06-05 - 1.1.0 - change data format for EVT_CLIENT_BAN_TEMP and EVT_CLIENT_BAN events
# 2011-07-14 - 1.1.1 - changes to support new dedicated server version 420003
#                    - implemented get_player_pings()
# 2011-08-27 - 1.1.2 - added DLC maps that come with patch 1.0.5
# 2011-08-31 - 1.1.3 - fixed typo in mapname
# 2011-11-05 - 1.1.4 - makes sure to release the self.exiting lock
# 2014-05-02 - 1.1.5 - rewrote import statements
#                    - remove class attribute duplicates
#                    - rewrote dictionary creation as literal
#                    - correctly initialize class attributes
#                    - replaced variable names using python built-in names
# 2014-07-16 - 1.1.6 - added admin key in EVT_CLIENT_KICK data dict when available
# 2014-07-18 - 1.1.7 - updated parser to comply with the new get_wrap implementation
#                    - updated rcon command patterns
# 2014-08-12 - 1.1.8 - syntax cleanup
# 2015-04-16 - 1.1.9 - fixed regression introduced in 1.1.7


import asyncore
import ftplib
import os
import re
import string
import sys
import time
from ftplib import FTP

import b311
import b311.cron
import b311.events
import protocol
import rcon
from b311 import functions
from b311.clients import Client
from b311.functions import prefixText
from b311.lib.sourcelib import SourceQuery
from b311.parser import Parser
from b311.parsers.homefront.protocol import ChannelType
from b311.parsers.homefront.protocol import MessageType

__author__ = 'Courgette, xlr8or, Freelander, 82ndab-Bravo17'
__version__ = '1.1.9'


class HomefrontParser(b311.parser.Parser):
    """
    The HomeFront B3 parser class
    """
    gameName = "homefront"
    privateMsg = True
    OutputClass = rcon.Rcon
    PunkBuster = None

    prefix = '%s: '
    ftpconfig = None
    maplist = None
    mapgamelist = None

    _serverConnection = None

    # homefront engine does not support color code, so we
    # need this property in order to get stripColors working
    _reColor = re.compile(r'(\^[0-9])')

    # map related
    _currentmap = None
    _ini_file = None
    _original_connection_handle_close_method = None
    _mapline = re.compile(r'^(?P<start>Map=)(?P<mapname>[^\?]+)\?(?P<sep>GameMode=)(?P<gamemode>.*)$', re.IGNORECASE)
    _reSteamId64 = re.compile(r'^[0-9]{17}$')
    _nbConsecutiveConnFailure = 0
    _ftplib_debug_level = 0  # 0: no debug, 1: normal debug, 2: extended debug
    _connectionTimeout = 30
    _playerlistInterval = 15
    _server_banlist = {}

    _commands = {
        'message': 'adminpm %(uid)s %(message)s',
        'say': 'adminsay %(message)s',
        'saybig': 'adminbigsay %(message)s',
        'kick': 'admin kick "%(playerid)s"',
        'ban': 'admin kickban "%(playerid)s" "%(admin)s" "[B3] %(reason)s"',
        'unban': 'admin unban %(playerId)s',
        'tempban': 'admin kick "%(playerid)s"',
        'maprotate': 'admin nextmap'
    }

    _settings = {
        'line_length': 90,
        'line_color_prefix': '',
    }

    ####################################################################################################################
    #                                                                                                                  #
    #   PARSER INITIALIZATION                                                                                          #
    #                                                                                                                  #
    ####################################################################################################################

    def startup(self):
        """
        Called after the parser is created before run().
        """
        # create the 'Server' client
        self.clients.newClient('Server', guid='Server', name='Server', hide=True, pbid='Server', team=b311.TEAM_UNKNOWN)

        if self.config.has_option('server', 'inifile'):
            # open ini file
            ini_file = self.config.get('server', 'inifile')
            if ini_file[0:6] == 'ftp://':
                self.ftpconfig = functions.splitDSN(ini_file)
                self._ini_file = 'ftp'
                self.bot('FTP supported')
            elif ini_file[0:7] == 'sftp://':
                self.bot('SFTP currently not supported')
            else:
                self.bot('Getting configs from %s', ini_file)
                f = self.config.getpath('server', 'inifile')
                if os.path.isfile(f):
                    self.input = file(f, 'r')
                    self._ini_file = f

        if not self._ini_file:
            self.debug('Incorrect ini file or no ini file specified: map commands other than nextmap not available')

        # start crontab to trigger playerlist events
        self.cron.add(b311.cron.CronTab(self.retrievePlayerList, second='*/%s' % self._playerlistInterval))

        # add specific events
        self.Events.createEvent('EVT_SERVER_SAY', 'Server Chatter')
        self.Events.createEvent('EVT_CLIENT_CLAN_CHANGE', 'Client Clan Change')
        self.Events.createEvent('EVT_CLIENT_VOTE_START', 'Client Vote Start')
        self.Events.createEvent('EVT_CLIENT_VOTE', 'Client Vote')
        self.Events.createEvent('EVT_SERVER_VOTE_END', 'Server Vote End')

        ## read game server info and store as much of it in self.game wich
        ## is an instance of the b311.game.Game class
        sq = SourceQuery.SourceQuery(self._publicIp, self._port, timeout=10)
        try:
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
            self.exception(err)

    def run(self):
        """
        Main worker thread for B3.
        """
        self.bot('Start listening ...')

        self.screen.write('Startup complete : B3 is running! Let\'s get to work!\n\n')
        self.screen.write('(If you run into problems, check %s in the B3 root directory for '
                          'detailed log info)\n' % self.config.getpath('b311', 'logfile'))

        self.updateDocumentation()

        while self.working:
            # While we are working, connect
            # to the Homefront server
            if self._paused:
                if self._pauseNotice is False:
                    self.bot('PAUSED - not parsing any lines: B3 will be out of sync')
                    self._pauseNotice = True
            else:
                if self._serverConnection is None:
                    self.bot('Connecting to Homefront server ...')
                    self._serverConnection = protocol.Client(self, self._rconIp, self._rconPort,
                                                             self._rconPassword, keepalive=True)

                    # hook on handle_close to protocol.Client
                    self._original_connection_handle_close_method = self._serverConnection.handle_close
                    self._serverConnection.handle_close = self._handle_connection_close

                    # listen for incoming HF packets
                    self._serverConnection.add_listener(self.routePacket)

                    # setup Rcon
                    self.output.set_homefront_client(self._serverConnection)

                self._nbConsecutiveConnFailure = 0

                while self.working and not self._paused \
                        and (self._serverConnection.connected or not self._serverConnection.authed):
                    # self.verbose2("\t%s" % (time.time() - self._serverConnection.last_pong_time))
                    if time.time() - self._serverConnection.last_pong_time > 6 \
                            and self._serverConnection.last_ping_time < self._serverConnection.last_pong_time:
                        self._serverConnection.ping()
                    asyncore.loop(timeout=3, use_poll=True, count=1)

        self.bot('Stop listening...')

        with self.exiting:
            self._serverConnection.close()
            if self.exitcode:
                sys.exit(self.exitcode)

    ####################################################################################################################
    #                                                                                                                  #
    #   OTHER METHODS                                                                                                  #
    #                                                                                                                  #
    ####################################################################################################################

    def routePacket(self, packet):
        if packet is None:
            self.warning('Cannot route empty packet')
        if packet.message == MessageType.SERVER_TRANSMISSION \
                and packet.data == "PONG":
            self.verbose2("%s" % packet)
        else:
            self.console("%s" % packet)

        if packet.message == MessageType.SERVER_TRANSMISSION:
            if packet.channel == ChannelType.SERVER:
                if packet.data == "PONG":
                    return
                match = re.search(r"^(?P<event>[A-Z ]+): (?P<data>.*)$", packet.data, re.MULTILINE | re.DOTALL)
                if match:
                    func = 'onServer%s' % (string.capitalize(match.group('event').replace(' ', '_')))
                    data = match.group('data')
                    # self.debug('DATA: %s' % data)
                    # self.debug("-==== FUNC!!: " + func)

                    if hasattr(self, func):
                        # self.debug('routing ----> %s' % func)
                        func = getattr(self, func)
                        event = func(data)
                        if event:
                            self.queueEvent(event)
                    else:
                        self.warning('TODO: handle: %s(%s)' % (func, data))
                else:
                    self.warning('TODO: handle packet : %s' % packet)
                    self.queueEvent(self.getEvent('EVT_UNKNOWN', packet))

            elif packet.channel == ChannelType.CHATTER:
                if packet.data.startswith('BROADCAST:'):
                    data = packet.data[10:]
                    func = 'onChatterBroadcast'
                    if hasattr(self, func):
                        func = getattr(self, func)
                        event = func(data)
                        if event:
                            self.queueEvent(event)
                    else:
                        self.warning('TODO: handle: %s(%s)' % (func, data))
                else:
                    data = packet.data
                    func = 'onChatter'
                    if hasattr(self, func):
                        # self.debug('routing ----> %s' % func)
                        func = getattr(self, func)
                        event = func(data)
                        if event:
                            self.queueEvent(event)
                    else:
                        self.warning('TODO handle: %s(%s)' % (func, data))
            else:
                self.warning("unhandled channel type : %s" % packet.getChannelTypeAsStr())
        else:
            self.warning("unhandled message type : %s" % packet.getMessageTypeAsStr())

    def _handle_connection_close(self):
        if len(self.clients.getList()):
            self.debug("clearing player list")
            self.clients.empty()
        self._original_connection_handle_close_method()

    def getTeam(self, team):
        team = str(team).lower()
        if team == '0':
            result = b311.TEAM_RED
        elif team == '1':
            result = b311.TEAM_BLUE
        elif team == '2':
            result = b311.TEAM_SPEC
        elif team == '3':
            result = b311.TEAM_UNKNOWN
        else:
            result = b311.TEAM_UNKNOWN
        return result

    def getClient(self, name):
        """
        Return a already connected client by searching the clients cid index.
        This method can return None.
        """
        client = self.clients.getByCID(name)
        if client:
            return client
        return None

    def getClientByUidOrCreate(self, uid, name):
        """
        Return a already connected client by searching the clients guid index or create a new client.
        This method can return None.
        """
        client = self.clients.getByGUID(uid)
        if client is None and name:
            client = self.clients.newClient(name, guid=uid, name=name, team=b311.TEAM_UNKNOWN)
            client.last_update_time = time.time()
        return client

    def getftpini(self):
        def handleDownload(line):
            # self.debug('received %s bytes' % len(block))
            line += '\n'
            mapline = self.checkMapline(line)
            if mapline:
                self.maplist.append(mapline[0])
                self.mapgamelist.append(self.getEasyName(mapline[0]) + ' [' + mapline[1] + ']')

        ftp = None
        try:
            ftp = self.ftpconnect()
            self._nbConsecutiveConnFailure = 0
            remoteSize = ftp.size(os.path.basename(self.ftpconfig['path']))
            self.verbose("Connection successfull: remote file size is %s" % remoteSize)
            ftp.retrlines('RETR ' + os.path.basename(self.ftpconfig['path']), handleDownload)
        except ftplib.all_errors, e:
            self.debug(str(e))
            try:
                ftp.close()
                self.debug('FTP connection closed')
            except:
                pass
            ftp = None

        try:
            ftp.close()
        except:
            pass

    def ftpconnect(self):
        # self.debug('Python Version %s.%s, so setting timeout of 10 seconds' % (versionsearch.group(2), versionsearch.group(3)))
        self.verbose('Connecting to %s:%s ...' % (self.ftpconfig["host"], self.ftpconfig["port"]))
        ftp = FTP()
        ftp.set_debuglevel(self._ftplib_debug_level)
        ftp.connect(self.ftpconfig['host'], self.ftpconfig['port'], self._connectionTimeout)
        ftp.login(self.ftpconfig['user'], self.ftpconfig['password'])
        ftp.voidcmd('TYPE I')
        d = os.path.dirname(self.ftpconfig['path'])
        self.debug('Trying to cwd to [%s]' % d)
        ftp.cwd(d)
        return ftp

    def retrieveBanList(self):
        """
        Send RETRIEVE BANLIST to the server.
        """
        self.verbose2('retrieving banlist')
        self.write('RETRIEVE BANLIST')

    def retrievePlayerList(self):
        """
        Send RETRIEVE PLAYERLIST to the server to trigger onServerPlayer return events
        """
        self.verbose2('Retrieving Playerlist')
        self.write('RETRIEVE PLAYERLIST')

    ####################################################################################################################
    #                                                                                                                  #
    #   GAME EVENTS HANDLERS                                                                                           #
    #                                                                                                                  #
    ####################################################################################################################

    def onServerHello(self, data):
        ## [int: Version]
        self.bot("HF server (v %s) says hello to B3" % data)

    def onServerAuth(self, data):
        ## [boolean: Result]
        if data == 'true':
            self.bot("B3 correctly authenticated on game server")
            self.clients.sync()
            self.retrieveBanList()
        else:
            self.warning("B3 failed to authenticate on game server (%s)" % data)

    def onServerLogin(self, data):
        # [string: Name] [int: SteamID]
        # (onServerLogin also occurs after a mapchange...)
        # example : cou"rgette\u3010\u30c4\u3011 76561197963239764
        match = re.search(r"^(?P<name>.+) (?P<uid>[0-9]+)$", data)
        if not match:
            self.error("Could not parse LOGIN event [%s]" % data)
            return None
        if match.group('uid') == '00':
            self.info("Banned player connecting")
            return
        client = self.getClientByUidOrCreate(match.group('uid'), match.group('name'))
        if client:
            # we need this event for xlrstats (counting playerrounds)
            self.queueEvent(self.getEvent('EVT_CLIENT_JOIN', None, client))

    def onServerUid(self, data):
        # [string: Name] [int: SteamID]
        # example : courgette 1100012402D1245
        match = re.search(r"^(?P<name>.+) (?P<uid>[0-9]+)$", data)
        if not match:
            self.error("Could not get UID in [%s]" % data)
            return None
        if match.group('uid') == '00':
            self.info("Banned player connecting")
            return
        self.getClientByUidOrCreate(match.group('uid'), match.group('name'))

    def onServerLogout(self, data):
        ## [int: SteamID]
        client = self.clients.getByGUID(data)
        if client:
            client.disconnect()
            self.debug('%s (%s) disconnected' % (client.name, data))

    def onServerTeam_change(self, data):
        # [int: SteamID] [int: Team ID]
        self.debug('onServerTeam_change: %s' % data)
        match = re.search(r"^(?P<uid>[0-9]+) (?P<team>.*)$", data)
        if not match:
            self.error('onServerTeam_change failed match')
            return
        client = self.clients.getByGUID(match.group('uid'))
        if client is None:
            self.debug("Could not find client")
            return
        # This next line will also raise the EVT_CLIENT_TEAM_CHANGE event
        client.team = self.getTeam(match.group('team'))
        self.debug('%s (%s) has switched team to %s' % (client.name, client.guid, client.team))

    def onServerClan_change(self, data):
        # [int: SteamID] [string: Clan Name]
        match = re.search(r"^(?P<uid>[0-9]+) (?P<clan>.*)$", data)
        if not match:
            self.error('onServerClan_change failed match')
            return
        client = self.clients.getByGUID(match.group('uid'))
        if client is None:
            self.debug("Could not find client")
            return
        client.clan = match.group('clan')
        return self.getEvent('EVT_CLIENT_CLAN_CHANGE', client.clan, client)

    def onServerKill(self, data):
        # [string: Killer Name] [string: DamageType] [string: Victim Name]
        # kill example: courgette EXP_Frag Freelander
        # kill example: 1100012402D1245 EXP_Frag 1100012402D1217
        # suicide example#1: Freelander Suicided Freelander (triggers when player leaves the server)
        # suicide example#2: Freelander EXP_Frag Freelander
        match = re.search(r"^(?P<data>(?P<attacker>[^;]+)\s+(?P<aweap>[A-z0-9_-]+)\s+(?P<victim>[^;]+))$", data)
        ## [int: Killer SteamID] [string: DamageType] [int: Victim SteamID]
        # match = re.search(r"^(?P<data>(?P<auid>.*)\s+(?P<aweap>[A-z0-9_-]+)\s+(?P<vuid>.*))$", data)
        if not match:
            self.error("Can't parse kill line: %s" % data)
            return
        else:
            attackerid = match.group('attacker')
            if self._reSteamId64.match(attackerid):
                attacker = self.clients.getByGUID(attackerid)
            else:
                # not a SteamID ? must be a player name
                attacker = self.getClient(attackerid)
            if not attacker:
                self.debug('No attacker!')
                return

            victimid = match.group('victim')
            if self._reSteamId64.match(victimid):
                victim = self.clients.getByGUID(victimid)
            else:
                # not a SteamID ? must be a player name
                victim = self.getClient(victimid)
            if not victim:
                self.debug('No victim')
                return

            weapon = match.group('aweap')
            if not weapon:
                self.debug('No weapon')
                return

            if not hasattr(victim, 'hitloc'):
                victim.hitloc = 'body'

        eventkey = 'EVT_CLIENT_KILL'
        if weapon == 'Suicided' or attacker == victim:
            eventkey = 'EVT_CLIENT_SUICIDE'
            self.verbose('%s suicided' % attacker.name)
        elif attacker.team != b311.TEAM_UNKNOWN and attacker.team == victim.team:
            eventkey = 'EVT_CLIENT_KILL_TEAM'
            self.verbose('Team kill: attacker: %s, victim: %s' % (attacker.name, victim.name))
        else:
            self.verbose('%s killed %s using %s' % (attacker.name, victim.name, weapon))

        return self.getEvent(eventkey, (100, weapon, victim.hitloc), attacker, victim)

    def onServerRound_over(self, data):
        ## [int: Team ID]
        match = re.search(r"^(?P<team>.*)$", data)
        if not match:
            self.error('onServerRound_over failed match')
            return

        # teamid = The ID of the winning team
        # 0 = KPA
        # 1 = USA
        # 2 = TIE
        teamid = match.group('team')
        self.verbose('onServerRound_over: %s, winning team id: %s' % (data, teamid))
        return self.getEvent('EVT_GAME_ROUND_END', teamid)

    def onServerChange_level(self, data):
        ## [string: Map]
        ## example : fl-harbor
        match = re.search(r"^(?P<level>.*)$", data)
        if not match:
            self.error('onServerChange_level failed match')
            return

        # resync players to get rid of eventual 'phantom' players
        self.clients.sync()

        levelname = match.group('level')
        self.verbose('onServerChange_level, levelname: %s' % levelname)
        self._currentmap = levelname.lower()
        self.game.mapName = levelname.lower()
        return self.getEvent('EVT_GAME_ROUND_START', levelname)

    def onServerPlayerping(self, data):
        # [int: SteamID] [int: Ping]
        # example: 74569798001346241 48
        match = re.search(r"^(?P<uid>[0-9]+) (?P<ping>[0-9]+)$", data)
        if not match:
            self.error('onServerPlayerping failed match')
            return

        guid = match.group('uid')
        ping = match.group('ping')
        client = self.clients.getByGUID(guid)
        if client:
            client.ping = ping

    def onChatterBroadcast(self, data):
        # [string: Name] [string: Context]: [string: Text]
        # example : courgette says: !register
        match = re.search(r"^(?P<name>.+) (\((?P<type>team|squad)\))?says: (?P<text>.*)$", data)
        if not match:
            self.error("Could not understand broadcast format [%s]" % data)
            raise
        else:
            typo = match.group('type')
            name = match.group('name')
            text = match.group('text')
            client = self.getClient(name)
            if client is None:
                self.debug("Could not find client")
                return
            if typo == 'team':
                return self.getEvent('EVT_CLIENT_TEAM_SAY', text, client)
            elif typo == 'squad':
                return self.getEvent('EVT_CLIENT_SQUAD_SAY', text, client)
            else:
                return self.getEvent('EVT_CLIENT_SAY', text, client)

    def onChatter(self, data):
        """
        Everything that is said by the server or a player is sent over this channel.
        All onChatterBroadcast messages also reappear here.
        """
        # [string: Text]
        self.verbose2('Received chatter: %s' % data)
        return self.getEvent('EVT_SERVER_SAY', data)

    def onServerBan_remove(self, data):
        """
        [int: SteamID]
        """
        # we are using storage instead of self.clients because the player 
        # is obviously not connected when banned
        client = self.storage.getClient(Client(guid=data))
        if client:
            self.write(self.getCommand('saybig', prefix='', message="%s removed from server banlist" % client.name))
        else:
            self.write(self.getCommand('saybig', prefix='', message="%s unbanned" % data))
        # update banlist
        self.retrieveBanList()

    def onServerBan_added(self, data):
        # [string: Name] [int: SteamID]
        match = re.search(r"^(?P<data>(?P<name>[^ ]+)\s+(?P<uid>[0-9]+))$", data)
        if not match:
            self.error('onServerBan_added failed match')
            return
        # we are using storage instead of self.clients because the player might already
        # have been kick
        client = self.storage.getClient(Client(guid=match.group('uid')))
        if client:
            self.write(self.getCommand('saybig', prefix='', message="%s added to server banlist" % client.name))
        else:
            self.error('Cannot find banned client')
        # update banlist
        self.retrieveBanList()

    def onServerPlayer(self, data):
        # [string: Uid] [int: Team] [string: Clan] [string: Name] [int: Kills] [int: Deaths]
        # example: 71897609803318218\n1\nB3bot\nFreelander\n0\n0
        match = re.search(
            r"^(?P<data>(?P<uid>[0-9]+)\n(?P<team>[0-9])\n(?P<clan>.*)\n(?P<name>[^ ]+)\n(?P<kills>[0-9]+)\n(?P<deaths>[0-9]+))$",
            data)
        if not match:
            self.error("onServerPlayer failed match")
            return

        uid = match.group('uid')
        if uid == '0':
            # connecting player with no UID resolved yet --> ignore
            return

        if len(uid) != 17:
            self.warning(u"weird UID : [%s]" % uid)

        # try to get the client by guid
        client = self.clients.getByGUID(uid)
        if not client:
            client = self.clients.newClient(match.group('name'), guid=uid, name=match.group('name'),
                                            team=b311.TEAM_UNKNOWN)

        # update client data
        client.name = match.group('name')
        client.team = self.getTeam(match.group('team'))
        client.clan = match.group('clan')
        client.kills = match.group('kills')
        client.deaths = match.group('deaths')
        client.last_update_time = time.time()  ## save the timestamp so sync() can use that info
        self.verbose2('onServerPlayer: name: %s, clan: %s, team: %s, kills: %s, deaths: %s' % (
        client.name, client.clan, client.team, client.kills, client.deaths))

    def onServerBan_item(self, data):
        # [string: Name] [string: Uid]
        match = re.match(r"^(?P<data>(?P<name>[^ ]+) (?P<uid>[0-9]+))$", data)
        if not match:
            self.error('onServerBan_item failed match')
            return
        name = match.group('name')
        guid = match.group('uid')
        self._server_banlist[guid] = name

    def onServerVotestart(self, data):
        # [int: SteamID] [string: VoteType] [optional string: Target]
        match = re.match(r"^(?P<data>(?P<uid>[0-9]+) (?P<vtype>[^ ]+)( (?P<target>.*))?)$", data)
        if not match:
            self.error('onServerVotestart: failed match')
            return

        client = self.clients.getByGUID(match.group('uid'))
        votetype = match.group('vtype')
        if match.group('target'):
            target = self.clients.getByGUID(match.group('target'))
        else:
            target = None

        return self.getEvent('EVT_CLIENT_VOTE_START', data=votetype, client=client, target=target)

    def onServerVote(self, data):
        # [int: SteamID] [boolean: Yes]
        # boolean: 1 is vote for, 0 is vote against
        match = re.match(r"^(?P<data>(?P<uid>[0-9]+) (?P<vote>[01]))$", data)
        if not match:
            self.error('onServerVote failed match')
            return

        client = self.clients.getByGUID(match.group('uid'))
        vote = match.group('vote')
        return self.getEvent('EVT_CLIENT_VOTE', data=vote, client=client)

    def onServerVoteend(self, data):
        # [int: YesVotes] [float: PercentFor] [string: Pass]
        # YesVotes: Number of players that voted yes
        # PercentFor: Percent of total players that voted yes (as a float)
        # Pass: "passed" for success, "failed" for failure
        match = re.match(
            r"^(?P<data>(?P<yesvotes>[0-9]+) (?P<percentfor>[0-9]+(\.[0-9]+)?) (?P<vresult>passed|failed))$", data)
        if not match:
            self.error('onServerVoteend failed match')
            return

        yesvotes = match.group('yesvotes')
        percentfor = match.group('percentfor')
        voteresult = match.group('vresult')

        return self.getEvent('EVT_SERVER_VOTE_END',
                             data={'yesvotes': yesvotes, 'percentfor': percentfor, 'voteresult': voteresult})

    ####################################################################################################################
    #                                                                                                                  #
    #   B3 PARSER INTERFACE IMPLEMENTATION                                                                             #
    #                                                                                                                  #
    ####################################################################################################################

    def getPlayerList(self):
        """
        Returns a list of client objects
        """
        return self.clients.getList()

    def authorizeClients(self):
        """
        For all connected players, fill the client object with properties allowing to find 
        the user in the database (usualy guid, or punkbuster id, ip) and call the 
        Client.auth() method 
        """
        ## in Homefront, there is no synchronous way to obtain a player guid
        ## the onServerUid event will be the one calling Client.auth()
        pass

    def sync(self):
        """
        For all connected players returned by self.getPlayerList(), get the matching Client
        object from self.clients (with self.clients.getByCID(cid) or similar methods) and
        look for inconsistencies. If required call the client.disconnect() method to remove
        a client from self.clients.
        """
        ## we are unable to get the exact list of connected players in a synchronous
        ## way. So we use .last_update_time timestamp to detect player we still
        ## have in self.clients but that are no longer on the game server
        self.debug("synchronizing clients")
        mlist = {}
        now = time.time()
        for client in self.clients.getList():
            howlongago = now - client.last_update_time
            self.debug(u"%s last seen %d seconds ago" % (client, howlongago))
            if howlongago < (self._playerlistInterval * 2):
                mlist[client.cid] = client
            else:
                self.info(u"%s last update is too old" % client)
                client.disconnect()
        return mlist

    def say(self, text):
        """
        Broadcast a message to all players.
        :param text: The message to be sent.
        """
        message = self.stripColors(prefixText([self.msgPrefix], text)).strip()
        for line in self.getWrap(message):
            self.write(self.getCommand('say', message=line))

    def saybig(self, msg):
        """
        Broadcast a message to all players in a way that will catch their attention.
        :param msg: The message to be sent.
        """
        message = self.stripColors(prefixText([self.msgPrefix], msg)).strip()
        for line in self.getWrap(message):
            self.write(self.getCommand('saybig', message=line))

    ## @TODO Change private messages when the rcon protocol will allow us to
    def message(self, client, text):
        """
        Send a private message to a client.
        :param client: The client to who send the message.
        :param text: The message to be sent.
        """
        # actually send private messages
        message = prefixText([self.msgPrefix, self.pmPrefix], text)
        message = self.stripColors(message).strip()
        for line in self.getWrap(message):
            self.write(self.getCommand('message', uid=client.guid, message=line))

    def kick(self, client, reason='', admin=None, silent=False, *kwargs):
        """
        Kick a given client.
        :param client: The client to kick
        :param reason: The reason for this kick
        :param admin: The admin who performed the kick
        :param silent: Whether or not to announce this kick
        """
        self.debug('KICK : client: %s, reason: %s', client.cid, reason)
        if admin:
            variables = self.getMessageVariables(client=client, reason=reason, admin=admin)
            fullreason = self.getMessage('kicked_by', variables)
        else:
            variables = self.getMessageVariables(client=client, reason=reason)
            fullreason = self.getMessage('kicked', variables)

        fullreason = self.stripColors(fullreason)
        reason = self.stripColors(reason)

        if not silent and fullreason != '':
            self.say(fullreason)

        if client.guid:
            self.write(self.getCommand('kick', playerid=client.guid))
        else:
            self.write(self.getCommand('kick', playerid=client.cid))

        self.queueEvent(
            b311.events.Event(self.getEventID('EVT_CLIENT_KICK'), {'reason': reason, 'admin': admin}, client))
        client.disconnect()

    def ban(self, client, reason='', admin=None, silent=False, *kwargs):
        """
        Ban a given client.
        :param client: The client to ban
        :param reason: The reason for this ban
        :param admin: The admin who performed the ban
        :param silent: Whether or not to announce this ban
        """
        self.debug('BAN : client: %s, reason: %s', client.cid, reason)

        if admin:
            variables = self.getMessageVariables(client=client, reason=reason, admin=admin)
            fullreason = self.getMessage('banned_by', variables)
        else:
            variables = self.getMessageVariables(client=client, reason=reason)
            fullreason = self.getMessage('banned', variables)

        fullreason = self.stripColors(fullreason)
        reason = self.stripColors(reason)

        if not silent and fullreason != '':
            self.say(fullreason)

        banid = client.guid
        if banid is None:
            banid = client.cid
            self.debug('using name to ban : %s' % banid)
            # saving banid in the name column in database
            # so we can unban a unconnected player using name
            client._name = banid
            client.save()

        self.write(self.getCommand('ban', playerid=banid, admin=admin.name.replace('"', '\"'), reason=reason))
        self.queueEvent(self.getEvent('EVT_CLIENT_BAN', {'reason': reason, 'admin': admin}, client))
        client.disconnect()

    ## @TODO Need to test response from the server
    def unban(self, client, reason='', admin=None, silent=False, *kwargs):
        """
        Unban a client.
        :param client: The client to unban
        :param reason: The reason for the unban
        :param admin: The admin who unbanned this client
        :param silent: Whether or not to announce this unban
        """
        if client.guid:
            self.debug('using guid to unban')
            banid = client.guid
        else:
            self.debug('using name to unban')
            banid = client.name

        self.write(self.getCommand('unban', playerId=banid))
        if admin:
            admin.message('Unbanned: removed %s from banlist' % client.name)
        self.queueEvent(self.getEvent('EVT_CLIENT_UNBAN', reason, client))

    def tempban(self, client, reason='', duration=2, admin=None, silent=False, *kwargs):
        """
        Tempban a client.
        :param client: The client to tempban
        :param reason: The reason for this tempban
        :param duration: The duration of the tempban
        :param admin: The admin who performed the tempban
        :param silent: Whether or not to announce this tempban
        """
        self.debug('TEMPBAN : client: %s, reason: %s', client.cid, reason)
        if admin:
            banduration = b311.functions.minutesStr(duration)
            variables = self.getMessageVariables(client=client, reason=reason, admin=admin, banduration=banduration)
            fullreason = self.getMessage('temp_banned_by', variables)
        else:
            banduration = b311.functions.minutesStr(duration)
            variables = self.getMessageVariables(client=client, reason=reason, banduration=banduration)
            fullreason = self.getMessage('temp_banned', variables)

        fullreason = self.stripColors(fullreason)
        reason = self.stripColors(reason)

        if not silent and fullreason != '':
            self.say(fullreason)

        if client.guid:
            self.write(self.getCommand('kick', playerid=client.guid))
        else:
            self.write(self.getCommand('kick', playerid=client.cid))

        self.queueEvent(
            self.getEvent('EVT_CLIENT_BAN_TEMP', {'reason': reason, 'duration': duration, 'admin': admin}, client))
        client.disconnect()

    def getMap(self):
        """
        Return the current map/level name
        """
        if self._currentmap is None:
            return "Unknown"
        else:
            return self._currentmap

    def getNextMap(self):
        """
        Return the name of the next map
        """
        self.getMaps()
        no_maps = len(self.maplist)
        currentmap = self.getMap()
        if self.maplist.count(currentmap) == 1:
            i = self.maplist.index(currentmap)
            if i < no_maps - 1:
                nextmap = self.mapgamelist[i + 1]
            else:
                nextmap = self.mapgamelist[0]
        else:
            nextmap = 'Unknown'
        return nextmap

    def getMaps(self):
        """
        Return the available maps/levels name
        """
        self.maplist = []
        self.mapgamelist = []
        if self._ini_file:
            if self._ini_file == 'ftp':
                self.getftpini()
            else:
                _input = open(self._ini_file, 'r')
                for line in _input:
                    mapline = self.checkMapline(line)
                    if mapline:
                        if mapline[1] == 'FL':
                            mapline[1] = 'GC'
                        if mapline[1] == 'FL,BC':
                            mapline[1] = 'GC,BC'
                        self.maplist.append(mapline[0])
                        self.mapgamelist.append(self.getEasyName(mapline[0]) + ' [' + mapline[1] + ']')

                _input.close()
            return self.mapgamelist

    def checkMapline(self, line):
        mapname = re.match(self._mapline, line)
        if mapname:
            d = mapname.groupdict()
            d2 = [d['mapname'], d['gamemode']]
            return d2
        else:
            return None

    def rotateMap(self):
        """
        Load the next map/level
        """
        # CT admin NextMap
        self.write(self.getCommand('maprotate'))

    def changeMap(self, mapname):
        """
        Load a given map/level.
        Return a list of suggested map names in cases it fails to recognize the map that was provided.
        """
        raise NotImplementedError

    def getEasyName(self, mapname):
        """
        Change levelname to real name.
        """
        if mapname == 'fl-angelisland':
            return 'Angel Island'
        elif mapname == 'fl-crossroads':
            return 'Crossroads'
        elif mapname == 'fl-culdesac':
            return 'Cul-de-Sac'
        elif mapname == 'fl-farm':
            return 'Farm'
        elif mapname == 'fl-harbor':
            return 'Green Zone'
        elif mapname == 'fl-lowlands':
            return 'Lowlands'
        elif mapname == 'fl-borderlands':
            return 'Borderlands'
        elif mapname == 'fl-spillway':
            return 'Spillway'
        elif mapname == 'fl-bigbox':
            return 'Big Box'
        elif mapname == 'fl-alcatraz':
            return 'Alcatraz'
        elif mapname == 'fl-bridge':
            return 'Bridge'
        elif mapname == 'fl-tdmspillway':
            return 'Waterway'
        elif mapname == 'fl-overpass':
            return 'Overpass'
        else:
            self.warning('unknown level name \'%s\' : please report this on B3 forums' % mapname)
            return mapname

    def getPlayerPings(self, filter_client_ids=None):
        """
        Returns a dict having players' id for keys and players' ping for values.
        """
        pings = {}
        clients = self.clients.getList()
        if filter_client_ids:
            clients = filter(lambda client: client.cid in filter_client_ids, clients)

        for c in clients:
            try:
                pings[c.name] = int(c.ping)
            except AttributeError:
                pass
        return pings

    def getPlayerScores(self):
        """
        Returns a dict having players' id for keys and players' scores for values.
        """
        # trigger a 'retrieve playerlist' command
        # self.retrievePlayerList()
        scores = {}
        clients = self.clients.getList()
        for c in clients:
            try:
                scores[c.name] = int(c.kills)
            except AttributeError:
                pass
        return scores

    def inflictCustomPenalty(self, penalty_type, client, reason=None, duration=None, admin=None, data=None):
        """
        Called if b311.admin.penalizeClient() does not know a given penalty type.
        Overwrite this to add customized penalties for your game like 'slap', 'nuke', 
        'mute' or anything you want.
        /!\ This method must return True if the penalty was inflicted.
        """
        if penalty_type == 'kill' and client:
            self.write('admin kill "%s"' % client.guid)
            if reason:
                client.message("%s" % reason)
            return True
