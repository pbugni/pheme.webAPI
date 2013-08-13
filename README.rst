pheme.webAPI
============

Public Health EHR Message Engine (PHEME), Web API

The pheme.webAPI exposes RESTful web services to act on documents.  The 
documents tend to represent generated public health reports.  Available
endpoints provide the standard document store, update, delete and retrieve
mechanisms, supporting an unlimited set of meta-data on each document.
Additional endpoints implement transfer protocols for secure transfer of
stored reports to configured entities.

Requirements
------------

pheme.webAPI uses the MongoDB as a backing store.  After installing
mongo, the connection details must be added to the pheme config file.
For example (using mongo defaults and localhost):

.. code::
    [WebAPI]
    host=localhost
    port=6543

License
-------

BSD 3 clause license - See LICENSE.txt

