"""Run the HTTP suite through socket pairs when a sandbox forbids TCP bind.

Uses the real request parser, handlers, authentication, database and responses.
Only the transport is replaced; normal unittest commands still use TCP.
"""
import itertools
from pathlib import Path
import socket
import sys
import threading
import unittest

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import server

registry={}
ports=itertools.count(28000)
original_connect=socket.create_connection

class PairServer:
    def __init__(self,address,handler):
        self.server_port=next(ports);self.handler=handler;self.done=threading.Event()
        registry[self.server_port]=self
    def serve_forever(self):self.done.wait()
    def shutdown(self):self.done.set()
    def server_close(self):registry.pop(self.server_port,None)

class PairSocket:
    def __init__(self,sock):self.sock=sock
    def __getattr__(self,key):return getattr(self.sock,key)
    def setsockopt(self,level,option,value):
        if level!=socket.IPPROTO_TCP:self.sock.setsockopt(level,option,value)

def create_pair(address,timeout=socket._GLOBAL_DEFAULT_TIMEOUT,source_address=None,**kwargs):
    service=registry.get(address[1])
    if not service:return original_connect(address,timeout,source_address,**kwargs)
    client,remote=socket.socketpair()
    if isinstance(timeout,(int,float)):client.settimeout(timeout)
    def handle():
        try:service.handler(remote,('127.0.0.1',0),service)
        except (BrokenPipeError,ConnectionResetError):pass
        finally:remote.close()
    threading.Thread(target=handle,daemon=True).start()
    return PairSocket(client)

if __name__=='__main__':
    server.ThreadingHTTPServer=PairServer
    socket.create_connection=create_pair
    suite=unittest.defaultTestLoader.loadTestsFromNames(sys.argv[1:] or ['test_mvp','test_features','test_leave','test_live','test_academy'])
    result=unittest.TextTestRunner(verbosity=2).run(suite)
    sys.exit(not result.wasSuccessful())
