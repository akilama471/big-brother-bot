#
# Netblocker Plugin for BigBrotherBot(B3) (www.bigbrotherbot.com)
# Copyright (C) 2014 Mark Weirath (xlr8or@xlr8or.com)
# 
# This program is free software; you can redistribute it and/or modify
# it under the terms of the GNU General Public License as published by
# the Free Software Foundation; either version 2 of the License, or
# (at your option) any later version.

# This program is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY; without even the implied warranty of
# MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.    See the
# GNU General Public License for more details.
# 
# You should have received a copy of the GNU General Public License
# along with this program; if not, write to the Free Software
# Foundation, Inc., 51 Franklin St, Fifth Floor, Boston, MA    02110-1301    USA
#
# netblocker module provided by siebenmann: https://github.com/siebenmann/python-netblock


__version__ = '1.0.2beta'
__author__ = 'xlr8or'

import b311
import b311.events
import b311.plugin
import b311.plugins.netblocker.netblock as netblock


class NetblockerPlugin(b311.plugin.Plugin):
    _adminPlugin = None
    _blocks = []
    _maxLevel = 1

    ####################################################################################################################
    #                                                                                                                  #
    #    STARTUP                                                                                                       #
    #                                                                                                                  #
    ####################################################################################################################

    def onStartup(self):
        """
        Initialize plugin.
        """
        # get the admin plugin so we can register commands
        self._adminPlugin = self.console.getPlugin('admin')
        if not self._adminPlugin:
            raise AttributeError('could not find admin plugin')

        if self.console.isFrostbiteGame():
            self.registerEvent('EVT_PUNKBUSTER_NEW_CONNECTION', self.onPlayerConnect)
        else:
            self.registerEvent('EVT_CLIENT_AUTH', self.onPlayerConnect)

        self.debug('plugin started')

    def onLoadConfig(self):
        """
        Load plugin configuration
        """
        self._blocks = self.getSetting('settings', 'netblock', b311.LIST, [])
        self._maxLevel = self.getSetting('settings', 'maxlevel', b311.LEVEL, self._maxLevel)

    ####################################################################################################################
    #                                                                                                                  #
    #    EVENTS                                                                                                        #
    #                                                                                                                  #
    ####################################################################################################################

    def onPlayerConnect(self, event):
        """
        Examine players ip address and allow/deny connection.
        """
        client = event.client
        self.debug('checking client: %s, name: %s, ip: %s, level: %s', client.cid, client.name, client.ip,
                   client.maxLevel)

        # check the level of the connecting client before applying the filters
        if client.maxLevel > self._maxLevel:
            self.debug('%s is a higher level user, and allowed to connect', client.name)
        else:
            # transform ip address
            ip = netblock.convert(client.ip)
            # cycle through our blocks
            for block in self._blocks:
                # convert each block
                b = netblock.convert(block)
                # check if clients ip is in the disallowed range
                if b[0] <= ip[0] <= b[1]:
                    # client not allowed to connect
                    self.debug('client refused: %s (%s)', client.ip, client.name)
                    client.kick("Netblocker: Client %s refused!" % client.name)
