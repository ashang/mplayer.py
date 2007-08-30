"""pymplayer - MPlayer wrapper for Python.
"""

__author__ = "Darwin Bautista <djclue917@gmail.com>"

__version__ = "$Revision: 49 $"
# $Source$

__date__ = "$Date: $"

__copyright__ = """
Copyright (C) 2007  The MA3X Project (http://bbs.eee.upd.edu.ph)

This program is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

This program is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with this program.  If not, see <http://www.gnu.org/licenses/>.
"""

__license__ = "GPL-3"

try:
    import socket
    import cPickle
    import sys
    import re
    from subprocess import Popen, PIPE
    from threading import Thread
except ImportError, msg:
    exit(msg)


__all__ = ['MPlayer', 'MPlayerServer']


class MPlayer:
    """
    MPlayer wrapper for Python
    Provides the basic interface for sending commands and receiving responses
    to and from MPlayer.
    Responsible for starting up MPlayer in slave mode
    """
    def __init__(self, args=()):
        self.set_args(args)
        self.__subprocess = None

    def __del__(self):
        self.stop()

    def start(self):
        if not self.isrunning():
            self.__subprocess = Popen(self._command, stdin=PIPE)

    def stop(self):
        if self.isrunning():
            self.execute("quit")
            self.__subprocess.wait()
            return self.__subprocess.poll()
        else:
            return None

    def execute(self, cmd):
        if not isinstance(cmd, basestring):
            raise TypeError("command must be a string")
        if not cmd:
            raise ValueError("zero-length command")
        if self.isrunning():
            self.__subprocess.stdin.write("".join([cmd, '\n']))

    def isrunning(self):
        try:
            return True if self.__subprocess.poll() is None else False
        except AttributeError:
            return False

    def embed_into(self, window_id):
        if not isinstance(window_id, long):
            raise TypeError("window_id should be a long int")
        args = self.get_args()
        args.extend(["-wid", str(window_id)])
        self.set_args(args)

    def set_args(self, args):
        # args must either be a tuple or a list
        if not isinstance(args, (list, tuple)):
            raise TypeError("args should either be a tuple or list of strings")
        if args:
            for arg in args:
                if not isinstance(arg, basestring):
                    raise TypeError("args should either be a tuple or list of\
                                     strings")
        self._command = ["mplayer", "-slave", "-idle", "-quiet"]
        self._command.extend(args)

    def get_args(self):
        args = self._command[4:]
        try:
            idx = args.index('-wid')
        except ValueError:
            idx = None

        if idx is not None:
            args.remove(args[idx + 1])
            args.remove('-wid')

        return args

    def get_playlists(self):
        """
        Returns the list of playlists based on MPlayer cmdline
        """
        playlists = []
        idx = 0
        for match in range(self._command.count("-playlist")):
            try:
                idx = self._command.index("-playlist", idx) + 1
            except ValueError:
                break
            try:
                playlists.append(self._command[idx])
            except IndexError:
                break
        return playlists


class _ClientThread(Thread):
    """
    Thread for handling a client connection
    usage: ClientThread(mplayer, channel, details).start()
    The thread finishes after the connection is closed by the client
    """
    def __init__(self, mplayer_server, channel, details, timeout=None):
        if not isinstance(mplayer_server, MPlayerServer):
            raise TypeError("mplayer_server must be an instance of MPlayerServer")

        self.__mplayer_server = mplayer_server
        self.channel = channel
        self.details = details
        self.channel.settimeout(timeout)
        Thread.__init__(self)

    def run(self):
        print "Remote host %s connected at port %d" % self.details
        # RegExp for "quit" command in MPlayer
        quit_cmd = re.compile('^(qu?|qui?|quit?)( ?| .*)$', re.IGNORECASE)
        while self.__mplayer_server.isrunning():
            try:
                # Receive command from the client
                data = self.channel.recv(1024)
            except socket.error, msg:
                print >> sys.stderr, msg
                break
            except EOFError, msg:
                print >> sys.stderr, msg
                break
            except socket.timeout:
                print "Connection timed out."
                break
            # Unpickle data
            cmd = cPickle.loads(data)
            # Remote client closed the connection
            if quit_cmd.match(cmd):
                break
            elif cmd.lower() == "reload":
                # (Re)Loading a playlist makes MPlayer "jump out" of its XEmbed container
                self.__mplayer_server.restart_mp()
            else:
                # Send the command to MPlayer
                self.__mplayer_server.execute(cmd)
        # Close the connection
        try:
            self.channel.shutdown(socket.SHUT_RDWR)
            self.channel.close()
        except socket.error, msg:
            print >> sys.stderr, msg[1]

        self.__mplayer_server._connections.remove(self)
        print "Connection closed: %s at port %d" % self.details


class MPlayerServer(MPlayer, Thread):
    """
    MPlayer wrapper with commands implemented as functions
    This is useful for easily controlling MPlayer in Python
    """
    wait = Thread.join
    def __init__(self, args=(), host='', port=50001, max_connections=2):
        MPlayer.__init__(self, args)
        Thread.__init__(self)
        self.set_host(host)
        self.set_port(port)
        self.set_max_connections(max_connections)
        self._connections = []
        self.__socket = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        # Set option to re-use the address to prevent "Address already in use" errors
        self.__socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.__socket.settimeout(5.0)

    def __del__(self):
        MPlayer.__del__(self)
        self.stop()

    def start(self):
        Thread.start(self)

    def set_host(self, host):
        if not isinstance(host, basestring):
            raise TypeError("host must be a string")
        self._host = host

    def get_host(self):
        return self._host

    def set_port(self, port):
        if not isinstance(port, int):
            raise TypeError("port must be an integer")
        self._port = port

    def get_port(self):
        return self._port

    def set_max_connections(self, max_connections):
        if not isinstance(max_connections, int):
            raise TypeError("port must be an integer")
        self._max_connections = max_connections

    def get_max_connections(self):
        return self._max_connections

    def run(self):
        MPlayer.start(self)
        try:
            self.__socket.bind((self._host, self._port))
        except socket.error, msg:
            self.__socket.close()
            print >> sys.stderr, msg[1]
            return

        self.__socket.listen(1)

        while self.isrunning():
            # Wait for connection from client
            try:
                (conn, addr) = self.__socket.accept()
            except socket.timeout:
                continue
            except socket.error:
                break

            if len(self._connections) < self._max_connections:
                # Start separate client thread to handle connection (timeout: 30 seconds)
                client = _ClientThread(self, conn, addr, 30.0)
                self._connections.append(client)
                client.start()
            else:
                conn.close()
                print "Connection rejected: max number of connections reached"

    def stop(self):
        MPlayer.stop(self)
        try:
            self.__socket.close()
        except AttributeError:
            pass
        # Wait for _ClientThreads to terminate.
        for connection in self._connections:
            connection.join()

    def restart_mp(self):
        MPlayer.stop(self)
        MPlayer.start(self)
