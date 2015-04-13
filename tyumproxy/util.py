"""
Created on Apr 4, 2015

@author: Azhar
"""
from collections import OrderedDict

from parse import with_pattern, Parser
import yaml

from . import yaml_anydict


class UrlTranspose(object):
    FIELD = ['releasename', 'releasever', 'reponame', 'basearch', 'filename']

    def __init__(self, options):
        self._options = options
        self._path = options.get('pathformat')

        extra_types = {
            'parse_netloc': self.parse_netloc,
            'parse_releasename': self.parse_releasename,
            'parse_reponame': self.parse_reponame,
            'parse_releasever': self.parse_releasever,
            'parse_basearch': self.parse_basearch,
            'parse_filename': self.parse_filename,
            'parse_skip': self.parse_skip,
        }

        self._parsers = []
        for fmt in options['urlformat']:
            pattern = self.fix(fmt['pattern'])
            self._parsers.append((
                Parser(pattern, extra_types=extra_types),
                {k: fmt[k] for k in fmt if k != 'pattern'}
            ))

    @with_pattern(
        '(.+)?')
    def parse_skip(self, string):
        return string

    @with_pattern(
        '((([0-9]|[1-9][0-9]|1[0-9]{2}|2[0-4][0-9]|25[0-5])\.){3}([0-9]|[1-9][0-9]|1[0-9]{2}|2[0-4][0-9]|25[0-5])|'
        '(([a-zA-Z0-9]|[a-zA-Z0-9][a-zA-Z0-9\-]*[a-zA-Z0-9])\.)*([A-Za-z0-9]|[A-Za-z0-9][A-Za-z0-9\-]*[A-Za-z0-9]))'
        '(:[0-9]+)?')
    def parse_netloc(self, string):
        return string.lower()

    @with_pattern(
        '(?i)fedora|centos')
    def parse_releasename(self, string):
        return string.lower()

    @with_pattern(
        '[^/]+')
    def parse_reponame(self, string):
        return string

    @with_pattern(
        '[0-9.]+')
    def parse_releasever(self, string):
        return string

    @with_pattern(
        '(?i)x86_64|i386|SRPMS')
    def parse_basearch(self, string):
        return string.lower()

    def parse_filename(self, string):
        names = string.split('/')
        if names[0] == 'repodata':
            return string
        return names[-1]

    @classmethod
    def fix(cls, pattern):
        pattern = pattern.replace('{scheme}', '{scheme:w}')
        pattern = pattern.replace('{netloc}', '{netloc:parse_netloc}')
        pattern = pattern.replace('{releasename}', '{releasename:parse_releasename}')
        pattern = pattern.replace('{releasever}', '{releasever:parse_releasever}')
        pattern = pattern.replace('{reponame}', '{reponame:parse_reponame}')
        pattern = pattern.replace('{basearch}', '{basearch:parse_basearch}')
        pattern = pattern.replace('{filename}', '{filename:parse_filename}')

        i, old = 0, pattern
        pattern = pattern.replace('{opt}', '{s%d:parse_skip}' % i)
        while old != pattern:
            i, old = i + 1, pattern
            pattern = pattern.replace('{opt}', '{s%d:parse_skip}' % i)

        return pattern

    def format(self, value):
        filename = self._path.format(**value).lower()
        return filename

    def __call__(self, url):
        if self._path is None:
            return None

        for parser, template in self._parsers:
            match = parser.parse(url)
            if match:
                break
        else:
            template = {}
            match = None

        if match:
            value = {k: template[k].format(**match.named) for k in template}
            value.update({k: v for k, v in match.named.items() if k in self.FIELD})

            try:
                filename = self.format(value)
            except Exception as e:
                pass
            else:
                return filename

        return None


class OrderedDictObj(OrderedDict):
    def __getattr__(self, item):
        try:
            return OrderedDict.__getattribute__(self, item)
        except AttributeError:
            try:
                return self.__getitem__(item)
            except KeyError:
                try:
                    return self.__getitem__(item.replace('-', '_'))
                except KeyError:
                    raise AttributeError("'%s' object has no attribute '%s'", (self.__class__.__name__, item))


class LoaderMapAsOrderedDict(yaml_anydict.LoaderMapAsAnydict, yaml.Loader):
    anydict = OrderedDictObj

    @classmethod  # and call this
    def load_map_as_anydict(cls):
        yaml.add_constructor('tag:yaml.org,2002:map', cls.construct_yaml_map)
