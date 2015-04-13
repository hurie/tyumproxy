"""
Created on Aug 15, 2014

@author: Azhar
"""
import hashlib
import socket
from tempfile import NamedTemporaryFile
from time import time
from urllib.parse import urlsplit
from pathlib import Path

from tornado.httpclient import AsyncHTTPClient
from tornado.httputil import HTTPHeaders
from tornado.log import app_log
import tornado.web
import tornado.iostream
import tornado.gen
from tornado.web import HTTPError


class ProxyHandler(tornado.web.StaticFileHandler):
    CHUNK_SIZE = 64 * 1024
    SUPPORTED_METHODS = ['GET', 'CONNECT']

    def initialize(self, path, default_filename=None):
        self.cache_dir = path
        self.url_transpose = self.application.url_transpose

        tornado.web.StaticFileHandler.initialize(self, str(self.cache_dir))

    def prepare(self):
        self.cacheable_exts = ('.rpm', '.img', '.sqlite.bz2', '.sqlite.gz', '.xml', '.xml.gz', '.qcow2', '.raw.xz',
                               '.iso', 'filelist.gz', 'vmlinuz')

        self.cacheable = False
        self.cache_used = False
        self.cache_file = None
        self.cache_fd = None
        self.cache_url = False

        self.req_code = None
        self.req_path = None
        self.req_headers = None

    def is_cacheable(self, path):
        return path.endswith(self.cacheable_exts)

    @tornado.gen.coroutine
    @tornado.web.asynchronous
    def get(self, path):
        self.req_path = path
        app_log.info('process %s', path)

        url = urlsplit(path)
        lifetime = time() - int(self.settings['cache']['lifetime']) * 60 * 60
        # lifetime = 2 ** 32 - 1

        cache_time = None
        self.cache_url = path.replace(url[0] + '://', '')
        self.cacheable = self.is_cacheable(url.path)
        app_log.debug('is cacheable %r', self.cacheable)
        if self.cacheable:
            cache_file = self.url_transpose(path)
            if not cache_file:
                netloc = [x for x in reversed(url.netloc.split('.'))]
                self.cache_file = self.cache_dir / '.'.join(netloc) / url.path[1:]
            else:
                self.cache_file = self.cache_dir / cache_file

        else:
            uri = self.request.uri.encode()
            cache_id = hashlib.sha1(uri).hexdigest()
            cache_path = self.cache_dir / '~' / cache_id[:2]

            cache_info = cache_path / (cache_id + '-url.txt')
            if not cache_info.exists():
                if not cache_info.parent.exists():
                    cache_info.parent.mkdir(parents=True)

                with cache_info.open('w') as f:
                    f.write(uri.decode())

            self.cache_file = cache_path / (cache_id + '-data.txt')

        if self.cache_file.exists():
            self.cache_file = self.cache_file.resolve()
            cache_time = self.cache_file.stat().st_mtime

            app_log.debug('cache time is %r lifetime is %r', cache_time, lifetime)
            if cache_time > lifetime:
                app_log.info('found %s', self.cache_file)

                cache_url = self.cache_file.relative_to(self.cache_dir).as_posix()
                return tornado.web.StaticFileHandler.get(self, cache_url)

            app_log.info('%s lifetime exceeded', self.cache_file)

        args = {k: v[0] for k, v in self.request.arguments.items()}

        app_log.info('fetch %s', self.request.uri)

        self.client = AsyncHTTPClient()
        self.client.fetch(self.request.uri,
                          method=self.request.method,
                          body=self.request.body,
                          headers=self.request.headers,
                          follow_redirects=False,
                          if_modified_since=cache_time,
                          allow_nonstandard_methods=True,
                          connect_timeout=int(self.settings['proxy']['timeout']),
                          request_timeout=99999999,
                          header_callback=self.process_header,
                          streaming_callback=self.process_body,
                          callback=self.process_finish)

    def process_header(self, line):
        header = line.strip()
        app_log.debug('header %s', header)
        if header:
            if self.req_headers is None:
                self.req_headers = HTTPHeaders()
                _, self.req_code, _ = header.split(' ', 2)
                self.req_code = int(self.req_code)
                if self.req_code in (599, 304):
                    self.req_code = 200
            else:
                self.req_headers.parse_line(line)
            return

        self.set_status(self.req_code)

        for header in ('Date', 'Cache-Control', 'Server', 'Content-Type', 'Location'):
            val = self.req_headers.get(header)
            if val:
                self.set_header(header, val)

        if 'content-encoding' not in self.req_headers:
            val = self.req_headers.get('Content-Length')
            if val:
                self.set_header('Content-Length', val)

        self.flush()

    def process_body(self, chunk):
        if self._finished:
            return

        if self.cache_file is not None:
            if self.cache_fd is None:
                app_log.debug('process body %s', self.req_path)
                self.cache_fd = NamedTemporaryFile(dir=str(self.cache_dir), delete=False)
            self.cache_fd.write(chunk)

        self.write(chunk)
        self.flush()

    def process_finish(self, response):
        app_log.debug('process finish %s', self.req_path)
        if self._finished or self.cache_used:
            app_log.debug('skip process finish')
            return

        if response.code in (599, 304):
            app_log.info('code %s fo %s', response.code, self.request.uri)
            if self.cache_file is not None and self.cache_file.exists():
                self.cache_file.touch()
                app_log.info('use %s', self.cache_file)
                self.cache_fd = self.cache_file.open('rb')
                self.process_file()
                return

        if self.cache_file is not None:
            if self.cache_fd is not None:
                self.cache_fd.close()

                if self.cache_file.exists():
                    self.cache_file.unlink()
                elif not self.cache_file.parent.exists():
                    self.cache_file.parent.mkdir(parents=True)

                temp_file = Path(self.cache_dir) / self.cache_fd.name
                temp_file.rename(self.cache_file)

                app_log.info('saved %s', self.cache_file)

        self.cache_fd = None

        if response.code == 599:
            self.set_status(599, 'network connect timeout error')
        else:
            try:
                self.set_status(response.code)
            except Exception as e:
                app_log.error(e)
                self.set_status(500, 'Internal server error')
        self.finish()

    def process_file(self):
        chunk = self.cache_fd.read(self.CHUNK_SIZE)
        if chunk:
            self.write(chunk)
            self.flush(callback=self.process_file)
            return

        self.cache_fd.close()
        self.cache_fd = None
        app_log.debug('process file %s finish', self.cache_file)
        self.finish()

    def compute_etag(self):
        if self.cache_file is None or not self.cache_file.exists():
            return None

        if not hasattr(self, 'absolute_path'):
            self.absolute_path = str(self.cache_file.absolute())

        return tornado.web.StaticFileHandler.compute_etag(self)

    def on_finish(self):
        app_log.debug('on finish')
        # sometimes, prepare is not called.
        if not hasattr(self, 'cache_fd') or self.cache_fd is None:
            return
        self.cache_fd.close()

    @tornado.web.asynchronous
    def connect(self, path):
        app_log.info('CONNECT to %s', self.request.uri)
        host, port = self.request.uri.split(':')
        client = self.request.connection.stream

        def read_from_client(data):
            app_log.debug('read from client\n%s', data)
            upstream.write(data)

        def read_from_upstream(data):
            app_log.debug('read from upstream\n%s', data)
            client.write(data)

        def client_close(data=None):
            app_log.debug('client close\n%s', data)
            if upstream.closed():
                return
            if data:
                upstream.write(data)
            upstream.close()

        def upstream_close(data=None):
            app_log.debug('upstream close\n%s', data)
            if client.closed():
                return
            if data:
                client.write(data)
            client.close()

        def start_tunnel():
            app_log.debug('start connect tunnel')
            client.read_until_close(client_close, read_from_client)
            upstream.read_until_close(upstream_close, read_from_upstream)
            client.write(b'HTTP/1.0 200 Connection established\r\n\r\n')

        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM, 0)
        upstream = tornado.iostream.IOStream(s)
        app_log.debug('connect to upstream')
        upstream.connect((host, int(port)), start_tunnel)
