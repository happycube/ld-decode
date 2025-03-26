"""
    It provides a way to pipe a float32 stream to GNU Radio
    For measurements and addons
"""

try:
    import zmq

    ZMQ_AVAILABLE = True
except ImportError:
    ZMQ_AVAILABLE = False
import os
import numpy as np
import socket


def find_available_port(start_port, end_port):
    for port in range(start_port, end_port + 1):
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
            try:
                s.bind(("localhost", port))
                return port
            except OSError:
                continue
    return None


class ZMQSend:
    def __init__(self, port=5555):
        self.pid = os.getpid()
        print("Initializing ZMQSend (REP) at pid %d, port %d" % (self.pid, port))
        self._port = port
        self.context = zmq.Context()
        self.socket = self.context.socket(zmq.REP)
        self.socket.bind("tcp://*:%s" % port)

    @property
    def port(self):
        return self._port

    def chekcpid(self):
        pid = os.getpid()
        assert (
            pid == self.pid
        ), "You cannot call send from another thread: expected %d found %d" % (
            self.pid,
            pid,
        )

    def send(self, data):
        self.chekcpid()
        null = self.socket.recv()
        self.socket.send(data.astype(np.float32))

    def send_complex(self, complex):
        self.chekcpid()
        null = self.socket.recv()
        data = np.empty((complex.real.size + complex.imag.size,), dtype=np.float32)
        data[0::2] = complex.real.astype(np.float32)
        data[1::2] = complex.imag.astype(np.float32)
        self.socket.send(data)


class ZMQReceive:
    def __init__(self, port=None):
        if port is None:
            port = find_available_port(5555, 6666)
        self.pid = os.getpid()
        print("Initializing ZMQReceive (REQ) at pid %d, port %d" % (self.pid, port))
        self._port = port
        self.context = zmq.Context()
        self.socket = self.context.socket(zmq.REQ)
        self.socket.connect("tcp://localhost:%s" % port)

    @property
    def port(self):
        return self._port

    def chekcpid(self):
        pid = os.getpid()
        assert (
            pid == self.pid
        ), "You cannot call receive from another thread: expected %d found %d" % (
            self.pid,
            pid,
        )

    def receive(self, samples):
        self.chekcpid()

        floats = []
        reads = 0
        read_size = 0
        while read_size < samples:
            try:
                # print('asking for data')
                self.socket.send_string("0", encoding="ascii")
                byte_stream = self.socket.recv()
                floats = np.append(floats, np.fromstring(byte_stream, dtype=np.float32))
                read_size = len(floats)
                # print('received data %d' % read_size)
                reads += 1
            except zmq.error.ZMQError as e:
                print("Got ZMQ error, %s" % e)
                break
        # print('got data, after %d reads' % reads)
        return floats
