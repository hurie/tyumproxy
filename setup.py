#!/bin/env python
import os
import sys

try:
    from setuptools import setup
except ImportError:
    from distutils.core import setup

from tyumproxy import VERSION

if sys.version_info < (3, 3):
    sys.exit('requires python 3.3 and up')

here = os.path.dirname(__file__)

setup(
    name='tyumproxy',
    version=VERSION,
    description='A tornado base yum cache proxy',
    long_description=open('README.rst').read(),
    author='A. Azhar Mashuri',
    author_email='hurie83@gmail.com',
    url='https://github.com/hurie/tyumproxy',
    install_requires=[
        'tornado==4.1',
        'PyYAML==3.11',
        'parse',
    ],
    include_package_data=True,
    packages=[
        'tyumproxy',
    ],
    package_data={'tyumproxy': [
        'template/default.cfg',
        'template/template.cfg.txt',
    ]},
    entry_points={
        'console_scripts': [
            'tyumproxy = tyumproxy.main:main',
        ],
    },
    zip_safe=False,
    keywords='yum tornado proxy',
    classifiers=[
        'Environment :: Web Environment',
        'Intended Audience :: Developers',
        'Intended Audience :: System Administrators',
        'Operating System :: OS Independent',
        'Programming Language :: Python :: 3.3',
        'Topic :: Software Development :: Libraries :: Python Modules',
    ]
)
