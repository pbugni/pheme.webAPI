#!/usr/bin/env python

import os

from setuptools import setup, find_packages

here = os.path.abspath(os.path.dirname(__file__))
README = open(os.path.join(here, 'README.txt')).read()
CHANGES = open(os.path.join(here, 'CHANGES.txt')).read()

requires = [
    'pheme.util',
    'PyMongo',
    'pyramid',
    'pyramid_debugtoolbar',
    'requests',
    'waitress',
    ]

setup(name='pheme.webAPI',
      version='13.7',
      description='web API for PHEME',
      long_description=README + '\n\n' + CHANGES,
      license="BSD-3 Clause",
      namespace_packages=['pheme'],
      packages=['pheme.webAPI'],
      classifiers=[
        "Programming Language :: Python",
        "Framework :: Pyramid",
        "Topic :: Internet :: WWW/HTTP",
        "Topic :: Internet :: WWW/HTTP :: WSGI :: Application",
        ],
      author='',
      author_email='',
      url='',
      keywords='web pyramid pylons',
      include_package_data=True,
      zip_safe=False,
      install_requires=requires,
      tests_require=requires,
      test_suite="pheme.webAPI",
      entry_points="""\
      [paste.app_factory]
      main = pheme.webAPI:main
      """,
      )
