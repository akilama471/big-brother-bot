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
# 08/01/2012 - 0.1 - NTAuthority - parser created
# 02/05/2014 - 0.2 - Fenix       - rewrote dictionary creation as literal
# 30/07/2014 - 0.3 - Fenix       - fixes for the new getWrap implementation
# 04/08/2014 - 0.4 - Fenix       - syntax cleanup

__author__ = 'NTAuthority'
__version__ = '0.4'

import re

import b311.parsers.cod6


class Cod8Parser(b311.parsers.cod6.Cod6Parser):
    gameName = 'cod8'

    _guidLength = 16

    _regPlayer = re.compile(r'(?P<slot>[0-9]+)\s+'
                            r'(?P<score>[0-9-]+)\s+'
                            r'(?P<ping>[0-9]+)\s+'
                            r'(?P<guid>[a-z0-9]+)\s+'
                            r'(?P<name>.*?)\s+'
                            r'(?P<last>[0-9]+)\s+'
                            r'(?P<ip>[0-9.]+):'
                            r'(?P<port>[0-9-]+)', re.IGNORECASE)

    ####################################################################################################################
    #                                                                                                                  #
    #   PARSER INITIALIZATION                                                                                          #
    #                                                                                                                  #
    ####################################################################################################################

    def startup(self):
        """
        Called after the parser is created before run().
        """
        b311.parsers.cod6.Cod6Parser.startup(self)
