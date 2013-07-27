from bson.objectid import ObjectId
import gzip
import re
import os
from datetime import datetime, timedelta
import json
from cStringIO import StringIO
from gridfs import GridFS
from gridfs.errors import NoFile
import pymongo
import requests
from tempfile import NamedTemporaryFile
import unittest
from pyramid import testing
from pyramid.traversal import traverse

from pheme.util.config import Config
from pheme.util.util import inProduction
from pheme.util.compression import expand_file, zip_file
from pheme.webAPI.resources import Root, BaseReport, EssenceReport
from pheme.webAPI.resources import LongitudinalReport, Search
from pheme.webAPI.resources import DistributeTransfer, PHINMS_Transfer


def add_testdb_to_request(request):
    """Insert fake mongodb for testing purposes

    Turns out this is WAY TOO SLOW.  Keeping around for occasional
    use, but tests using it are generally fenced out

    """
    # Emulate what is done in pheme.webAPI.__init__.add_mongo_db
    conn = pymongo.Connection()
    db_name = 'just-for-test'
    # Start clean - blow away the old
    conn.drop_database(db_name)
    db = conn[db_name]
    request.db = db
    request.fs = GridFS(db)
    request.document_store = db['fs.files']


class TestFile(unittest.TestCase):
    """Manages creation and clean up of a test file"""
    def setUp(self):
        super(TestFile, self).setUp()
        self.test_text = "A few simple words"

    def tearDown(self):
        super(TestFile, self).tearDown()
        if hasattr(self, 'tempfile'):
            os.remove(self.tempfile.name)

    def create_test_file(self, compression=None):
        """Helper to generate a temporary file to save

        Returns the filename, potenially pointing to a file containing
        the content of self.text and compressed as requested.

        NB File will need to be opened to use.

        """
        # Some tests loop over file used - clean as we go
        if hasattr(self, 'tempfile'):
            os.remove(self.tempfile.name)
            del self.tempfile

        # Generate a safe filename - deletion is tearDown's job
        if compression is None:
            self.tempfile = NamedTemporaryFile(prefix='unittest',
                                               delete=False)
            self.tempfile.write(self.test_text)
            self.tempfile.close()
        elif compression == 'gzip':
            self.tempfile = NamedTemporaryFile(prefix='unittest',
                                               suffix='.gz',
                                               delete=False)
            self.tempfile.close()
            fh = gzip.open(self.tempfile.name, 'wb')
            fh.write(self.test_text)
            fh.close()
        elif compression == 'zip':
            self.tempfile = NamedTemporaryFile(prefix='unittest',
                                               suffix='.zip',
                                               delete=False)
            self.tempfile.close()
            os.remove(self.tempfile.name)
            content = StringIO(self.test_text)
            self.tempfile.name = zip_file(self.tempfile.name, content,
                                          compression)
        else:
            raise ValueError("Can't handle compression '%s'",
                             compression)
        return self.tempfile.name


class PersistTestFile(TestFile):
    """Specialize TestFile, saving then deleting from database"""
    report_type = 'essence_pcE'  # just picking default at random

    def setUp(self):
        super(PersistTestFile, self).setUp()

    def tearDown(self):
        super(PersistTestFile, self).tearDown()
        if hasattr(self, 'oid'):
            self.fs.delete(self.oid)

    def create_test_file(self, **kwargs):
        """Helper to generate and persist a temporary file"""

        if kwargs.get('report_type'):
            self.report_type = kwargs.get('report_type')
        else:
            kwargs['report_type'] = self.report_type

        super(PersistTestFile, self).\
            create_test_file(kwargs.get('compression'))

        # Some tests re-create.  Clean as we go
        if hasattr(self, 'oid'):
            self.fs.delete(self.oid)
            del self.oid

        """Creation of test db makes unit tests too slow, using
        the real one - be careful with naming"""
        conn = pymongo.Connection()
        db_name = 'report_archive'
        db = conn[db_name]
        self.db = db
        self.fs = GridFS(db)

        # GridFS uses two collections, under the default 'fs'
        # namespace.  One for metadata ('fs.files') and one for the
        # file chunks ('fs.chunks').
        self.document_store = self.db['fs.files']

        filename = os.path.basename(self.tempfile.name)
        with open(self.tempfile.name, 'rb') as fh:
            self.oid = self.fs.put(fh,
                                   filename=filename,
                                   **kwargs)
        return self.oid


class ViewTests(TestFile):
    def setUp(self):
        super(ViewTests, self).setUp()
        self.config = testing.setUp()

    def tearDown(self):
        super(ViewTests, self).tearDown()
        testing.tearDown()

    def SLOWtest_upload_view(self):
        """Direct call to upload via view, using test db"""
        from pheme.webAPI.views import upload_report
        request = testing.DummyRequest()
        add_testdb_to_request(request)
        context = BaseReport()
        test_file = self.create_test_file(compression=None)
        context.file = open(test_file, 'rb')
        context.filename = test_file
        context.report_type = 'ESSENCE'
        upload_report(context, request)
        # Confirm the file can now be found in the db
        count = 0
        oid = None
        for row in request.document_store.find({'report_type': 'ESSENCE'}):
            count += 1
            self.assertEqual(row['filename'], test_file)
            oid = row['_id']
        self.assertEqual(count, 1)

        # Does the attachment match?
        attachment = request.fs.get(oid)
        self.assertEqual(attachment.read(), self.test_text)


class ReportTraversalTests(unittest.TestCase):
    def test_essence_traversal(self):
        root = Root(None)
        context = root['essence']
        self.assertTrue(isinstance(context, EssenceReport))

    def test_essence_traversal_E(self):
        root = Root(None)
        context = root['essence_pcE']
        self.assertTrue(isinstance(context, EssenceReport))

    def test_essence_traversal_I(self):
        root = Root(None)
        context = root['essence_pcI']
        self.assertTrue(isinstance(context, EssenceReport))

    def test_essence_traversal_O(self):
        root = Root(None)
        context = root['essence_pcO']
        self.assertTrue(isinstance(context, EssenceReport))

    def test_essence_traversal_invalid(self):
        root = Root(None)
        self.assertRaises(KeyError, root.__getitem__, 'essence_pcQ')

    def test_longitudinal_traversal(self):
        root = Root(None)
        context = root['longitudinal']
        self.assertTrue(isinstance(context, LongitudinalReport))

    def test_filename_key(self):
        root = Root(None)
        filename = '12345'
        for transport in ('essence', 'longitudinal'):
            context = root[transport][filename]
            self.assertEqual(context.filename, filename)

    def test_upload_traversal(self):
        root = Root(None)
        root.__parent__ = None
        out = traverse(root, '/essence/20111227')
        context = out['context']
        self.assertEqual(context.filename, u'20111227')

    def test_search_traversal(self):
        root = Root(None)
        root.__parent__ = None
        out = traverse(root, '/search')
        context = out['context']
        self.assertTrue(isinstance(context, Search))


class TransferAgentTraversalTests(unittest.TestCase):
    def test_phinms_traversal(self):
        root = Root(None)
        context = root['phin-ms']
        self.assertTrue(isinstance(context, PHINMS_Transfer))

    def test_distribute_traversal(self):
        root = Root(None)
        context = root['distribute']
        self.assertTrue(isinstance(context, DistributeTransfer))


class TransferAgentTests(PersistTestFile):
    """Unit test transfer agents"""
    def setUp(self):
        super(TransferAgentTests, self).setUp()

    def tearDown(self):
        super(TransferAgentTests, self).tearDown()

    def testDistributeTransfer(self):
        # need a document in the db
        self.create_test_file(compression='gzip',
                              reportable_region='wae')

        # fake a transfer of this object
        context = DistributeTransfer(testing.DummyRequest())
        context.request.fs = self.fs
        context.request.document_store = self.document_store
        context = context[str(self.oid)]
        self.assertFalse(inProduction())  # avoid accidental transfers!
        context.transfer_file()

    def testPhinmsTransfer(self):
        # need a document in the db
        self.create_test_file(compression='gzip',
                              report_type='longitudinal')

        # fake a transfer of this object
        context = PHINMS_Transfer(testing.DummyRequest())
        context.request.fs = self.fs
        context.request.document_store = self.document_store
        context = context[str(self.oid)]
        self.assertFalse(inProduction())  # avoid accidental transfers!
        context.transfer_file()

        self.assertEqual(self.report_type, 'longitudinal')
        config = Config()
        path = config.get('phinms', self.report_type)
        self.assertEqual(context.outbound_dir, path)

    def testReportTypes(self):
        "A number of report types are mapped to directories"
        for e in ('essence_pcE', 'essence_pcI', 'essence_pcO',
                  'essence'):
            doc_id = self.create_test_file(compression='gzip',
                                           reportable_region='wae',
                                           report_type=e)
            agent = PHINMS_Transfer(self.oid)
            document = self.document_store.find_one(doc_id)
            agent._set_report_type(document.get('report_type', None),
                                   document.get('patient_class', None))
            self.assertTrue(agent.outbound_dir)


class SearchTests(PersistTestFile):
    """Unit test search"""
    def setUp(self):
        super(SearchTests, self).setUp()

    def tearDown(self):
        super(SearchTests, self).tearDown()

    def testSearch(self):
        # stuff a document in the db
        self.create_test_file(report_type='test')

        # use API to find it
        search_criteria = {'report_type': self.report_type,
                           'filename': os.path.basename(self.tempfile.name)}
        url = 'http://localhost:6543/search?query=%s' %\
            json.dumps(search_criteria)
        r = requests.get(url)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.text, json.dumps(self.test_text))

    def testTimeRangeSearch(self):
        # stuff a document in the db
        self.test_text = 'a document with start and end times'
        end_time = datetime.now()
        start_time = end_time - timedelta(days=30)
        self.create_test_file(report_type='test',
                              start_time=start_time,
                              end_time=end_time)

        # use API to find it
        start = start_time - timedelta(hours=1)
        search_criteria = {'report_type': self.report_type,
                           'filename':
                           os.path.basename(self.tempfile.name),
                           'start_time': {'$gt': start.isoformat()},
                           'end_time': end_time.isoformat()}
        url = 'http://localhost:6543/search?query=%s' %\
            json.dumps(search_criteria)
        r = requests.get(url)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.text, json.dumps(self.test_text))


class ZipTests(TestFile):
    """Test the zip & expand compression functions"""
    def setUp(self):
        super(ZipTests, self).setUp()

    def tearDown(self):
        super(ZipTests, self).tearDown()

    def test_zip(self):
        filename = self.create_test_file(compression=None)
        result = zip_file(filename, open(filename, 'rb'), 'zip')
        # hand verified the contents were zipped and matched...
        self.assertTrue(os.path.exists(result))

    def test_gzip(self):
        filename = self.create_test_file(compression=None)
        result = zip_file(filename, open(filename, 'rb'), 'gzip')
        f = gzip.GzipFile(mode='rb', fileobj=open(result, 'rb'))
        self.assertEqual(f.read(), self.test_text)

    def test_gunzip_stream(self):
        compressed = self.create_test_file(compression='gzip')
        expanded = expand_file(fileobj=open(compressed, 'rb'),
                               zip_protocol='gzip')
        self.assertEqual(expanded.read(), self.test_text)

    def test_gunzip_file(self):
        compressed = self.create_test_file(compression='gzip')
        expanded = expand_file(filename=compressed, zip_protocol='gzip')
        self.assertEqual(expanded.read(), self.test_text)

    def test_unzip_stream(self):
        compressed = self.create_test_file(compression='zip')
        expanded = expand_file(fileobj=open(compressed, 'rb'),
                               zip_protocol='zip')
        self.assertEqual(expanded.read(), self.test_text)

    def test_unzip_file(self):
        compressed = self.create_test_file(compression='zip')
        expanded = expand_file(filename=compressed,
                               zip_protocol='zip')
        self.assertEqual(expanded.read(), self.test_text)


class TestReportSubmission(TestFile):
    """Functional tests using http - requires service"""

    def setUp(self):
        super(TestReportSubmission, self).setUp()

    def tearDown(self):
        super(TestReportSubmission, self).tearDown()

    def testReST(self):
        """Round trip http functional tests PUT/GET/DELETE reports

        This breaks away from the 'unit' cycle, as we build on the
        process moving through available steps.

        """
        filename = self.create_test_file(compression=None)
        url = 'http://localhost:6543/essence_pcE/%s' %\
            os.path.basename(filename)
        payload = {'compress_with': 'gzip'}
        files = {os.path.basename(filename): open(filename, 'rb')}
        r = requests.put(url, files=files, data=payload)
        self.assertEqual(r.status_code, 200)

        # Pull the doc id from the json reponse
        response = json.loads("".join([i for i in r.iter_content()]))
        self.assertTrue(response['document_id'])

        # Confirm the file is accessible
        conn = pymongo.Connection()
        db = conn['report_archive']  # db name in development.ini
        fs = GridFS(db)
        oid = ObjectId(response['document_id'])
        report = fs.get(oid)
        f = gzip.GzipFile(mode='rb', fileobj=report)
        self.assertEqual(f.read(), self.test_text)

        # Confirm duplicate submission fails
        r = requests.put(url, files=files, data=payload)
        self.assertEquals(r.status_code, 400)

        # Given the traversal included _pcE, test patient class
        self.assertEqual(report.patient_class, 'E')

        # confirm view for the uploaded document works
        url = 'http://localhost:6543/essence_pcE/%s' % oid
        r = requests.get(url)
        self.assertEqual(r.status_code, 200)
        pattern = re.compile(r'<span class="report">(.*?)</span>')
        match = pattern.search(r.text)
        self.assertEqual(match.groups()[0], self.test_text)

        # test delete, cleaning up the unwanted test doc too
        r = requests.delete(url)
        self.assertEqual(r.status_code, 200)
        self.assertRaises(NoFile, fs.get, oid)


class TestReportTransfer(PersistTestFile):
    """Functional tests using http - requires service"""

    def setUp(self):
        super(TestReportTransfer, self).setUp()

    def tearDown(self):
        super(TestReportTransfer, self).tearDown()

    def testDistribute(self):
        """Test distribute transfer via HTTP"""
        oid = self.create_test_file(compression='gzip',
                                    report_type='test')
        # Distribute requires a 'reportable_region'
        doc = self.document_store.find_one(ObjectId(oid))
        doc['reportable_region'] = 'just_testing'
        self.document_store.save(doc)
        url = 'http://localhost:6543/distribute/%s' % oid
        r = requests.post(url)
        self.assertEqual(r.status_code, 200)
        # Pretty difficult to confirm, hand tested

    def testPhinms(self):
        """Test PHIN-MS transfer via HTTP"""
        oid = self.create_test_file(compression=None,
                                    report_type='longitudinal')
        url = 'http://localhost:6543/phin-ms/%s' % oid
        r = requests.post(url)
        self.assertEqual(r.status_code, 200)
        # Pretty difficult to confirm, hand tested
