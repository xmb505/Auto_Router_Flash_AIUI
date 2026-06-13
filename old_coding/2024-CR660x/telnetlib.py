#!/usr/bin/env python3
"""
telnetlib.py - Compatibility shim for Python 3.13+
Reimplements telnetlib.Telnet using the standard telnetlib3 or socket.
Provides the same API as the removed stdlib telnetlib.
"""

import socket
import re
import time
import select

class Telnet:
    """Telnet client compatible with the old telnetlib.Telnet API."""

    def __init__(self, host=None, port=23, timeout=10):
        self.host = host
        self.port = port
        self.timeout = timeout
        self.sock = None
        self.prompt = None
        self._buf = b''
        
        if host is not None:
            self.open(host, port, timeout)

    def open(self, host, port=23, timeout=10):
        """Open connection to host:port."""
        self.host = host
        self.port = port
        self.timeout = timeout
        self.sock = socket.create_connection((host, port), timeout=timeout)
        self.sock.settimeout(timeout)
        self._buf = b''
        return self

    def close(self):
        """Close the connection."""
        if self.sock:
            try:
                self.sock.close()
            except Exception:
                pass
            self.sock = None

    def write(self, buffer):
        """Write bytes to the socket."""
        if isinstance(buffer, str):
            buffer = buffer.encode('ascii')
        if self.sock:
            self.sock.sendall(buffer)

    def read_until(self, expected, timeout=None):
        """Read until expected pattern is found."""
        if isinstance(expected, str):
            expected = expected.encode('ascii')
        deadline = time.time() + (timeout if timeout else self.timeout)
        while time.time() < deadline:
            if expected in self._buf:
                idx = self._buf.index(expected) + len(expected)
                data = self._buf[:idx]
                self._buf = self._buf[idx:]
                return data
            try:
                data = self.sock.recv(4096)
                if not data:
                    break
                self._buf += data
            except socket.timeout:
                break
            except Exception:
                break
        # Return whatever we have
        data = self._buf
        self._buf = b''
        return data

    def read_very_eager(self):
        """Read all available data without blocking."""
        data = b''
        if self.sock:
            self.sock.setblocking(0)
            try:
                while True:
                    chunk = self.sock.recv(4096)
                    if not chunk:
                        break
                    data += chunk
            except (BlockingIOError, socket.timeout):
                pass
            except Exception:
                pass
            finally:
                self.sock.setblocking(self.timeout or 10)
        if self._buf:
            data = self._buf + data
            self._buf = b''
        return data

    def read_all(self):
        """Read all data until EOF."""
        data = self._buf
        self._buf = b''
        if self.sock:
            try:
                while True:
                    chunk = self.sock.recv(4096)
                    if not chunk:
                        break
                    data += chunk
            except Exception:
                pass
        return data

    def expect(self, list, timeout=None):
        """
        Read until one of the regex patterns in list matches.
        Returns (index, match_object, text_before_match).
        Compatible with telnetlib.expect().
        """
        if timeout is None:
            timeout = self.timeout
        
        # Compile patterns
        compiled = []
        for p in list:
            if isinstance(p, bytes):
                compiled.append(re.compile(p))
            elif isinstance(p, str):
                compiled.append(re.compile(p.encode('ascii')))
            else:
                compiled.append(p)
        
        deadline = time.time() + timeout
        text = b''
        
        while time.time() < deadline:
            # Check if any pattern matches current buffer + accumulated text
            search_buf = text + self._buf
            
            for i, pattern in enumerate(compiled):
                m = pattern.search(search_buf)
                if m:
                    end_pos = m.end()
                    matched_text = search_buf[:end_pos]
                    remaining = search_buf[end_pos:]
                    self._buf = remaining
                    return (i, m, matched_text)
            
            # No match yet, read more data
            if self._buf:
                text += self._buf
                self._buf = b''
            
            try:
                ready, _, _ = select.select([self.sock], [], [], min(1.0, timeout))
                if ready:
                    data = self.sock.recv(4096)
                    if not data:
                        break
                    text += data
                else:
                    # Check timeout
                    if time.time() >= deadline:
                        break
            except socket.timeout:
                break
            except Exception:
                break
        
        # If timeout, return what we have
        result = text + self._buf
        self._buf = b''
        return (-1, None, result)

    def set_debuglevel(self, debuglevel):
        """Compatibility stub."""
        pass

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()
        return False

    def __del__(self):
        self.close()
