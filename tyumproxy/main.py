"""
Created on Aug 15, 2014

@author: Azhar
"""
import argparse
import logging
import logging.config
import os
from datetime import timedelta
from pathlib import Path

import tornado.ioloop
import tornado.template
import tornado.web
from tornado.log import app_log
from tornado.web import StaticFileHandler
import yaml

from . import template, yaml_anydict
from .handler import ProxyHandler
from tyumproxy.util import UrlTranspose
from .util import LoaderMapAsOrderedDict


logging.basicConfig()
_log = logging.getLogger(__name__)

CONFIG_FILENAME = 'tyumproxy.yml'


class Application(tornado.web.Application):
    def __init__(self, cfg, debug=False):
        self.cache_path = Path(cfg['cache']['path']).resolve()

        if 'transpose' in cfg:
            self.url_transpose = UrlTranspose(cfg['transpose'])
        else:
            self.url_transpose = lambda: None

        handlers = [
            (r"/~/(.*)", StaticFileHandler, {'path': cfg['cache']['path']}),
            (r"(.*)", ProxyHandler, {'path': self.cache_path}),
        ]

        tornado.web.Application.__init__(self, handlers,
                                         debug=debug,
                                         **cfg)


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
    filename = Path(filename).resolve()
    if not filename.is_file():
        raise Exception('{} not found'.format(filename))

    default_file = Path(template.__file__).resolve().parent / 'config.yml'
    default_cfg = yaml.load(default_file.open('r'))

    try:
        cfg = yaml.load(filename.open('r')) or {}
    except:
        raise Exception('Unable to load configuration file {}'.format(filename))

    merge_dict(default_cfg, cfg)

    cfg = default_cfg
    cfg['path'] = {}
    cfg['path']['base'] = str(filename.parent)
    return cfg


def setup_logging(cfg):
    logging_cfg = cfg['logging']

    path = Path(cfg['path']['base'])
    for handler in logging_cfg['handlers'].values():
        fname = handler.get('filename')
        if fname is None:
            continue

        fpath = Path(fname)
        if fpath.is_absolute():
            continue

        handler['filename'] = str(path / fpath)

    logging.config.dictConfig(logging_cfg)


def setup(args):
    config = os.getcwd() / Path(args.config if 'config' in args else CONFIG_FILENAME)
    root = config.parent
    template_dir = Path(template.__file__).parent

    if not args.replace and config.exists():
        print('{} already exists'.format(config))
        return

    def ask(question, error=None, default=None, info=None, cast=None):
        if default is None:
            question = '-> {}? '.format(question)
        else:
            question = '-> {} [{}]? '.format(question, default)

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

    LoaderMapAsOrderedDict.load_map_as_anydict()
    yaml_anydict.dump_anydict_as_map(LoaderMapAsOrderedDict.anydict)

    template_file = template_dir / 'config.yml'
    template_cfg = yaml.load(template_file.open('r'), Loader=LoaderMapAsOrderedDict)

    try:
        port = ask('Port to listen', 'Port range is 0 - 65535', 5000, cast=int)
        cache_dir = ask_path('Cache directory', default=template_cfg['cache']['path'])
        log_dir = ask_path('Application log path', default='.')
    except KeyboardInterrupt:
        print()
        print('Setup canceled!')
        return

    cache_dir = root / cache_dir
    if not cache_dir.exists():
        cache_dir.mkdir(parents=True)
    cache_dir = cache_dir.resolve()

    log_dir = root / log_dir
    if not log_dir.exists():
        log_dir.mkdir(parents=True)
    log_dir = log_dir.resolve()
    template_cfg['server']['port'] = port
    template_cfg['cache']['dir'] = str(cache_dir)

    for handler in template_cfg['logging']['handlers'].values():
        fname = handler.get('filename')
        if fname is None:
            continue

        fpath = Path(fname)
        if fpath.is_absolute():
            continue

        handler['filename'] = str(log_dir / fpath)

    template_file = template_dir / 'config.template'
    text = template_file.open('r').read()

    print('write configuration to {}'.format(config))
    t = tornado.template.Template(text)
    with config.open('w') as f:
        f.write(t.generate(**template_cfg).decode())


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

    setup_logging(cfg)
    start(args, cfg)


if __name__ == "__main__":
    main()
