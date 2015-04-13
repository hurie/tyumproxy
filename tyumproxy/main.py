"""
Created on Aug 15, 2014

@author: Azhar
"""
import argparse
from configparser import ConfigParser
import logging
import logging.config
from datetime import timedelta
import os

import pathlib
from pathlib import Path
from tornado.log import app_log
import tornado.web
import tornado.ioloop
from tornado.web import StaticFileHandler
import tyumproxy
from tyumproxy.handler import ProxyHandler
import tyumproxy.template


logging.basicConfig()
_log = logging.getLogger(__name__)

CONFIG_FILENAME = 'tyumproxy.cfg'


class Application(tornado.web.Application):
    def __init__(self, cfg, debug=False):
        for k in cfg['loggers']['keys'].split(','):
            del cfg['logger_' + k.strip()]

        for k in cfg['handlers']['keys'].split(','):
            del cfg['handler_' + k.strip()]

        for k in cfg['formatters']['keys'].split(','):
            del cfg['formatter_' + k.strip()]

        del cfg['loggers']
        del cfg['handlers']
        del cfg['formatters']

        handlers = [
            (r"/~/(.*)", StaticFileHandler, {'path': cfg['cache']['dir']}),
            (r"(.*)", ProxyHandler),
        ]

        tornado.web.Application.__init__(self, handlers,
                                         debug=debug,
                                         **cfg)

    def get_cache_path(self):
        base = pathlib.Path(self.settings['cache']['dir'])
        return base

    def get_pattern(self, host):
        if 'pattern/default' in self.settings:
            patterns = [self.settings['pattern/default']]
        else:
            patterns = []

        section = 'pattern/%s' % host
        if section in self.settings:
            patterns.insert(0, self.settings['pattern/%s' % host])

        return patterns


def merge_dict(source, other):
    for key in other:
        if key in source:
            if isinstance(source[key], dict) and isinstance(other[key], dict):
                merge_dict(source[key], other[key])
            elif source[key] != other[key]:
                source[key] = other[key]
        else:
            source[key] = other[key]


def load_config(filename):
    default_file = Path(tyumproxy.template.__file__).resolve().parent / 'default.cfg'
    config_file = Path(filename)

    cfg = ConfigParser(interpolation=None)
    cfg['server'] = {}
    cfg['server']['path'] = str(config_file.parent.resolve())
    cfg.read([str(default_file), str(config_file)])
    return cfg


def setup_logging(filename):
    default_file = Path(tyumproxy.template.__file__).resolve().parent / 'default.cfg'
    config_file = Path(filename)

    if config_file.exists():
        logging.config.fileConfig(str(config_file))
    else:
        logging.config.fileConfig(str(default_file))


def setup(args):
    config = os.getcwd() / Path(args.config if 'config' in args else CONFIG_FILENAME)
    root = config.parent

    if not args.replace and config.exists():
        print('{} already exists'.format(config))
        return

    def ask(question, error=None, default=None, info=None, cast=None):
        if default is None:
            question = '-> {} ? '.format(question)
        else:
            question = '-> {} [{}] ? '.format(question, default)

        if error is None:
            error = 'Invalid value'

        while True:
            res = input(question)
            if res == '':
                if default is not None:
                    res = default
                else:
                    print(info)
                    continue

            if cast is not None:
                try:
                    res = cast(res)
                except:
                    print(error)
                    continue

            return res

    def ask_file(question, default=None):
        if default is None:
            default = '.'

        while True:
            file = ask(question, default=default, cast=Path)
            if file.is_dir():
                print('{} is an existing directory'.format(file))
                continue
            return file

    def ask_path(question, default=None):
        if default is None:
            default = '.'

        while True:
            path = ask(question, default=default, cast=Path)
            if path.exists() and not path.is_dir():
                print('{} is an existing file'.format(path))
                continue
            return path

    default_file = Path(tyumproxy.template.__file__).resolve().parent / 'default.cfg'

    template_cfg = ConfigParser()
    template_cfg.read(str(default_file))

    try:
        port = ask('Port to listen', 'Port range is 0 - 65535', 5000, cast=int)
        cache_dir = ask_path('Cache directory', default=template_cfg['cache']['dir'])
    except KeyboardInterrupt:
        print()
        print('Setup canceled!')
        return

    cache_dir = root / cache_dir
    if not cache_dir.exists():
        cache_dir.mkdir(parents=True)
    cache_dir = cache_dir.resolve()

    template_cfg = ConfigParser()
    template_cfg.read(str(default_file))

    template_cfg['server']['port'] = str(port)
    template_cfg['cache']['dir'] = str(cache_dir)

    template_file = Path(tyumproxy.template.__file__).resolve().parent / 'template.cfg.txt'
    text = template_file.open('r').read()

    print('write configuration to {}'.format(config))
    config.open('w').write(text.format(**template_cfg))


def start(args, cfg):
    application = Application(cfg, args.debug)

    if args.debug:
        args.level = logging.DEBUG

    # setup logging level if specify
    if args.level is not None:
        logging.root.setLevel(args.level)

    # listen to port
    port = cfg['server']['port']
    try:
        application.listen(port)
        app_log.info('listening port %s', port)
    except OSError:
        app_log.error('unable to listen port %s', port)
        return

    ioloop = tornado.ioloop.IOLoop.instance()

    # prevent block for IO allowed ctrl-c to pass
    # http://stackoverflow.com/a/9578595
    def set_ping(timeout):
        ioloop.add_timeout(timeout, lambda: set_ping(timeout))

    set_ping(timedelta(seconds=0.5))

    # start main loop
    try:
        ioloop.start()
    except KeyboardInterrupt:
        app_log.info('Keyboard interrupt')
    except SystemExit:
        pass
    except Exception:
        app_log.exception('Error')
        raise

    ioloop.stop()
    app_log.info('Closed')
    return True


def main():
    # base parser
    parser = argparse.ArgumentParser()
    parser.add_argument('--config', default=CONFIG_FILENAME)
    parser.add_argument('--logging', dest='level',
                        choices=[v for k, v in logging._levelToName.items() if isinstance(k, int) and k != 0])

    subparsers = parser.add_subparsers()

    # start and daemon related command
    cmd = subparsers.add_parser('start')
    cmd.add_argument('--debug', default=False, action='store_true')
    cmd.set_defaults(cmd='start')

    # configuration setup
    cmd = subparsers.add_parser('setup')
    cmd.add_argument('--replace', default=False, action='store_true')
    cmd.set_defaults(cmd='setup')

    # parse
    args = parser.parse_args()

    # default command is start if not specify
    if 'cmd' not in args:
        args.cmd = 'start'
        args.debug = False

    # stop here if this ask for setup
    if args.cmd == 'setup':
        setup(args)
        return

    # load configuration
    try:
        cfg = load_config(args.config)
    except Exception as e:
        logging.basicConfig()
        logging.exception('')
        parser.error(e)
        raise

    setup_logging(args.config)
    start(args, cfg)


if __name__ == "__main__":
    main()
