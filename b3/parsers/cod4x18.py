__author__ = 'Leiizko'
__version__ = '0.2'

import re

import b311.clients
import b311.functions
import b311.parsers.cod4


class Cod4X18Parser(b311.parsers.cod4.Cod4Parser):
    gameName = 'cod4'
    IpsOnly = False
    _guidLength = 0
    _commands = {
        'message': 'tell %(cid)s %(message)s',
        'say': 'say %(message)s',
        'set': 'set %(name)s "%(value)s"',
        'kick': 'kick %(cid)s %(reason)s ',
        'ban': 'permban %(cid)s %(reason)s ',
        'unban': 'unban %(guid)s',
        'tempban': 'tempban %(cid)s %(duration)sm %(reason)s',
        'kickbyfullname': 'kick %(cid)s'
    }

    def startup(self):
        """
        Called after the parser is created before run().
        """
        blank = self.write('sv_usesteam64id  1', maxRetries=3)
        data = self.write('plugininfo b3hide', maxRetries=3)
        if data and len(data) < 50:
            self._regPlayer = re.compile(r'^\s*(?P<slot>[0-9]+)\s+'
                                         r'(?P<score>[0-9-]+)\s+'
                                         r'(?P<ping>[0-9]+)\s+'
                                         r'(?P<guid>[0-9]+)\s+'
                                         r'(?P<steam>[0-9]+)\s+'
                                         r'(?P<name>.*?)\s+'
                                         r'(?P<ip>(?:(?:25[0-5]|2[0-4][0-9]|1[0-9][0-9]|[1-9]?[0-9])\.){3}'
                                         r'(?:25[0-5]|2[0-4][0-9]|1[0-9][0-9]|[1-9]?[0-9])):?'
                                         r'(?P<port>-?[0-9]{1,5})\s*', re.IGNORECASE | re.VERBOSE)
            self._regPlayerShort = re.compile(r'^\s*(?P<slot>[0-9]+)\s+'
                                              r'(?P<score>[0-9-]+)\s+'
                                              r'(?P<ping>[0-9]+)\s+'
                                              r'(?P<guid>[0-9]+)\s+'
                                              r'(?P<steam>[0-9]+)\s+'
                                              r'(?P<name>.*?)\s+', re.IGNORECASE | re.VERBOSE)

    def unban(self, client, reason='', admin=None, silent=False, *kwargs):
        """
        Unban a client.
        :param client: The client to unban
        :param reason: The reason for the unban
        :param admin: The admin who unbanned this client
        :param silent: Whether or not to announce this unban
        """
        result = self.write(self.getCommand('unban', guid=client.guid))
        if admin:
            admin.message(result)

    def tempban(self, client, reason='', duration=2, admin=None, silent=False, *kwargs):
        """
        Tempban a client.
        :param client: The client to tempban
        :param reason: The reason for this tempban
        :param duration: The duration of the tempban
        :param admin: The admin who performed the tempban
        :param silent: Whether or not to announce this tempban
        """
        duration = b311.functions.time2minutes(duration)
        if isinstance(client, b311.clients.Client) and not client.guid:
            # client has no guid, kick instead
            return self.kick(client, reason, admin, silent)
        elif isinstance(client, str) and re.match('^[0-9]+$', client):
            self.write(self.getCommand('tempban', cid=client, reason=reason))
            return
        elif admin:
            banduration = b311.functions.minutesStr(duration)
            variables = self.getMessageVariables(client=client, reason=reason, admin=admin, banduration=banduration)
            fullreason = self.getMessage('temp_banned_by', variables)
        else:
            banduration = b311.functions.minutesStr(duration)
            variables = self.getMessageVariables(client=client, reason=reason, banduration=banduration)
            fullreason = self.getMessage('temp_banned', variables)

        duration = 43200 if int(duration) > 43200 else int(duration)
        self.write(self.getCommand('tempban', cid=client.cid, reason=reason, duration=duration))

        if not silent and fullreason != '':
            self.say(fullreason)

        self.queueEvent(self.getEvent('EVT_CLIENT_BAN_TEMP', {'reason': reason,
                                                              'duration': duration,
                                                              'admin': admin}, client))
        client.disconnect()
