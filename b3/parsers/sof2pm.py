#
# BigBrotherBot(B3) (www.bigbrotherbot.net)
# Copyright (C) 2011 Mark Weirath (xlr8or@xlr8or.com)
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
# 15/01/2014 - 1.1 - Fenix - PEP8 coding standards
# 18/07/2014 - 1.2 - Fenix - updated abstract parser to comply with the new get_wrap implementation
#                          - updated rcon command patterns
# 11/08/2014 - 1.3 - Fenix - syntax cleanup

from b311.functions import prefixText
from b311.parsers.sof2 import Sof2Parser

__author__ = 'xlr8or, ~cGs*Pr3z, ~cGs*AQUARIUS'
__version__ = '1.3'


class Sof2PmParser(Sof2Parser):
    gameName = 'sof2pm'
    privateMsg = True

    _commands = {
        'ban': 'addip %(cid)s',
        'kick': 'clientkick %(cid)s',
        'message': 'tell %(cid)s %(message)s',
        'say': 'say %(message)s',
        'set': 'set %(name)s "%(value)s"',
        'tempban': 'clientkick %(cid)s',
    }

    ####################################################################################################################
    #                                                                                                                  #
    #   B3 PARSER INTERFACE IMPLEMENTATION                                                                             #
    #                                                                                                                  #
    ####################################################################################################################

    def message(self, client, text):
        """
        Send a private message to a client.
        :param client: The client to who send the message.
        :param text: The message to be sent.
        """
        if client is None:
            # do a normal say
            self.say(text)
            return

        if client.cid is None:
            # skip this message
            return

        lines = []
        message = prefixText([self.msgPrefix, self.pmPrefix], text)
        message = message.strip()
        for line in self.getWrap(message):
            lines.append(self.getCommand('message', cid=client.cid, message=line))
        self.writelines(lines)
