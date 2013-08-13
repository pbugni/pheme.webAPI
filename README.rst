pheme.webAPI
============

**Public Health EHR Message Engine (PHEME), Web API**

The ``pheme.webAPI`` exposes RESTful web services to act on documents.
The documents typically represent generated public health reports.
Available endpoints provide the standard document store, update,
delete and retrieve mechanisms, supporting an unlimited set of
meta-data on each document.  Versioning of documents is also
supported.  Additional endpoints implement transfer protocols for
secure transfer of stored reports to configured entities.

Requirements
------------

``pheme.webAPI``, a `Pyramid`_ application, uses the `MongoDB`_ as a
backing store.  Mongo must be installed and running for ``pheme.webAPI``
to properly function.  Connection details are specified in the
development and production initiation files at the root of this
project.  Alter these defaults if necessary::

    [app:main]
    db_uri = mongodb://localhost/
    db_name = report_archive

For transmission via `PHIN Messaging System`_ additional entries in
the pheme config file (see ``pheme.util.config``) must specify the
polled directories per report type.  Configure PHIN-MS accordingly,
and detail the locations such as::

    [phinms]
    essence=/opt/PHINms/shared/essence/outgoing/
    essence_pcE=/opt/PHINms/shared/essence_er/outgoing/
    essence_pcI=/opt/PHINms/shared/essence_in/outgoing/
    essence_pcO=/opt/PHINms/shared/essence_out/outgoing/
    longitudinal=/opt/PHINms/shared/longitudinal/outgoing/

Finally, to protect from sending test data to production servers, like
most ``pheme`` modules, safeguards are in place.  When ready for
production, add to the ``pheme.util.config`` file.  Note also the need
for a log directory writable by the same user running the app::

    [general]
    in_production=True
    log_dir=/var/log/pheme

Install
-------

Beyond the requirements listed above, ``pheme.webAPI`` is dependent on
the ``pheme.util`` module.  Although future builds may automatically
pick it up, for now, clone and build it in the same virtual
environment (or native environment) being used for ``pheme.webAPI``::

    git clone https://github.com/pbugni/pheme.util.git
    cd pheme.util
    ./setup.py develop
    cd ..

Then clone and build this web app::

    git	clone https://github.com/pbugni/pheme.webAPI.git
    cd pheme.webAPI
    ./setup.py develop

Running
-------

The following invocation, run from the root directory of the
``pheme.webAPI`` project, uses the debug settings and captures logging
information in the configured directory.  The production
initialization file should be used when ready::

    pserve development.ini &> `configvar general log_dir`/webAPI.log

Testing
-------

Many of the tests expect the web app to be running (see `Running` above).  It is also strongly suggested that `in_production` be set to False before invoking the tests.  Run the tests from the ``pheme.webAPI`` as follows::

    ./setup.py test

To completely clean up any testing artifacts, destroy and recreate the
mongo database named in the initialization files.

Security
--------

At this time, no security measures are built into ``pheme.webAPI``.  It
is expected that the port hosting this web app (see ``[servers:main]port``
in the development and production initiation files) is only accessible from
localhost requests.  Localhost access should be limited appropriately.

License
-------

BSD 3 clause license - See LICENSE.txt


.. _Pyramid: http://www.pylonsproject.org/
.. _MongoDB: http://www.mongodb.org/
.. _PHIN Messaging System: http://www.cdc.gov/phin/tools/PHINms/