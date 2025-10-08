import http.server
import socketserver
import urllib
import posixpath
import os
from functools import partial

PORT = 31238

class RequestHandler(http.server.SimpleHTTPRequestHandler):
    def translate_path(self, path):
        path = super().translate_path(path)
        if not path.endswith(".png"):
            path += ".png"
        return path

Handler = partial(RequestHandler, directory="./archive")
with socketserver.TCPServer(("", PORT), Handler) as httpd:
    print("Serving at port", PORT)
    httpd.serve_forever()
