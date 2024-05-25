import b311
import b311.events
import b311.plugin


# --------------------------------------------------------------------------------------------------
class TeamchatPlugin(b311.plugin.Plugin):
    _adminPlugin = None

    def onStartup(self):
        self._adminPlugin = self.console.getPlugin('admin')
        if not self._adminPlugin:
            return False
            # SET COMMAND LEVEL HERE
        self.registerEvent(b311.events.EVT_CLIENT_TEAM_SAY)

    def tell_admins(self, client, text):
        originalword = text
        text = text.replace('QUICKMESSAGE', '')
        if (text != originalword):
            return False
        else:
            a = self._adminPlugin.getAdmins()
            if len(a) > 0:
                for adm in a:
                    adm.message('^7%s: %s' % (client.name, originalword))

    def onEvent(self, event):
        if event.type == b311.events.EVT_CLIENT_TEAM_SAY:
            self.tell_admins(event.client, event.data)
