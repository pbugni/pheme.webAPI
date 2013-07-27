from bson.objectid import ObjectId
from datetime import datetime
import logging
import os
from pyramid.exceptions import NotFound
import re
import requests

from pheme.util.config import Config
from pheme.util.util import inProduction
from pheme.util.compression import expand_file, zip_file


class Root(object):
    def __init__(self, request=None):
        self.request = request

    def __getitem__(self, key):
        """Root traversal method

        Traversal starts here.  The first segment of the request is
        matched below, delegating subsequent segment lookup to the
        respective classes.

        """
        if key.startswith('essence'):
            return EssenceReport(self.request, key)
        elif key == 'longitudinal':
            return LongitudinalReport(self.request)
        elif key == 'phin-ms':
            return PHINMS_Transfer(self.request)
        elif key == 'distribute':
            return DistributeTransfer(self.request)
        elif key == 'search':
            return Search(self.request)
        else:
            # With no recognizable path, try BaseReport as context
            return BaseReport(self.request).__getitem__(key)


class TransferAgent(object):
    """Base transfer agent traversal class

    Each transfer agent subclassing this class is responsible for the
    details specific to that agent, other than the common task of
    pulling the document id during traversal.

    """
    def __init__(self, request=None):
        self.request = request

    def __getitem__(self, key):
        """Traversal method

        Called during pyramid traversal, likely on the second segment
        of the request, after matching one of the TransferAgents
        subclasses on the first request.  The segment 'key' refers to
        the document_id or object identifier to transfer from the
        database

        """
        # If this instance already has a document_id, stop traversal
        if hasattr(self, 'document_id'):
            logging.debug("stop traversal on key: %s", key)
            raise KeyError

        try:
            self.document_id = ObjectId(key)
        except:
            raise NotFound
        if not self.request.fs.exists(self.document_id):
            logging.error("Can't transfer non existent document_id "
                          "'%s'", self.document_id)
            raise NotFound
        self.content = self.request.fs.get(self.document_id)
        self.document = self.request.document_store.find_one(self.document_id)
        return self

    def extract_content(self, compress_with):
        content = self.content
        if compress_with is not None and\
                self.document.get('compression') is not None:
            # Note, we're compressing on the fly, not persisting
            content = zip_file(filename=self.document['filename'],
                               fileobj=content,
                               zip_protocol=compress_with)
        return content

    def record_transfer(self):
        # retain transfer metadata
        self.document['transfer_date'] = datetime.utcnow()
        self.document['transfer_agent'] = str(self.__class__)
        self.request.document_store.save(self.document)


class PHINMS_Transfer(TransferAgent):
    """PHIN-MS Transfer Agent

    Used to upload files via a configured PHIN-MS server.
    Expects localhost PHIN-MS configuration with a dedicated directory
    for each service/action pair.  This class need only copy the file
    into the correct directory, and PHIN-MS will send it off at the
    next polling interval.

    For each report_type sent, a respective value should exist in
    the pheme configuration file, similar to the following:

    [phinms]
    essence=/opt/phin-ms/shared/phi/outgoing/
    essence_pcE=/opt/phin-ms/shared/essence_er/outgoing/
    essence_pcI=/opt/phin-ms/shared/essence_in/outgoing/
    essence_pcO=/opt/phin-ms/shared/essence_out/outgoing/
    longitudinal=/opt/phin-ms/shared/longitudinal/outgoing/

    """
    def __init__(self, request):
        super(PHINMS_Transfer, self).__init__(request)
        self._outbound_dir = None

    def _get_outbound_dir(self):
        return self._outbound_dir

    def _set_report_type(self, report_type, patient_class=None):
        if report_type == 'essence' and patient_class:
            report_type += '_pc' + patient_class
        config = Config()
        self._outbound_dir = config.get('phinms', report_type)

    outbound_dir = property(_get_outbound_dir, _set_report_type)

    def transfer_file(self, compress_with=None):
        """Initiate transfer via PHIN-MS

        Copy the file into the directory PHIN-MS is configured to
        poll.  NB - this method is doing nothing to confirm it is
        sent, that is left to the watchdog.

        :param compress_with: if document isn't already compressed and
          this is set, compress the file before transfering.

        """
        self._set_report_type(self.document.get('report_type', None),
                              self.document.get('patient_class', None))
        filename = self.document['filename']
        dest = os.path.join(self.outbound_dir, filename)
        content = self.extract_content(compress_with)

        if inProduction():
            logging.info("write %s to %s" % (filename, dest))
            with open(dest, 'wb') as destination:
                destination.write(content.read())
            self.record_transfer()
        else:
            logging.warn("inProduction() check failed, not sending "
                         "file '%s' to '%s'", filename, dest)


class DistributeTransfer(TransferAgent):
    """Distribute Transfer Agent

    Used to upload files to Distribute's https server.

    """
    def __init__(self, request):
        super(DistributeTransfer, self).__init__(request)

    def transfer_file(self, compress_with=None):
        """Initiate transfer via HTTPS

        :param compress_with: if document isn't already compressed and
          this is set, compress the file before transfering.

        """
        filename = self.document['filename']

        config = Config()
        upload_url = config.get('distribute', 'upload_url')
        user = config.get('distribute', 'username')
        pw = config.get('distribute', 'password')
        payload = {'siteShortName': self.document['reportable_region']}

        content = self.extract_content(compress_with)
        files = {'userfile': content}

        if inProduction():
            logging.info("POST %s to %s" % (filename, upload_url))
            r = requests.post(upload_url, auth=(user, pw), files=files,
                              data=payload)
            # We only get redirected if successful!
            if r.status_code != 302:
                logging.error("failed distrbute POST")
                #Can't rely on status_code, as distribute returns 200
                #with problems in the body.
                logging.error("".join(list(r.iter_content())))
                r.raise_for_status()
            else:
                self.record_transfer()
        else:
            logging.warn("inProduction() check failed, not POSTing "
                         "file '%s' to '%s'", filename, upload_url)


class BaseReport(object):
    """Base report traversal class

    The report classes deriving from this handle details specific to
    the report type.
    """
    def __init__(self, request=None):
        self.request = request
        self.__persist_attributes = {}

    def add_save_attribute(self, key, value):
        """Used to flag any additional attributes to save

        A subclass may want to add additional attributes to the
        specific reports.  Anything added here will end up in the
        database on save.

        """
        self.__persist_attributes[key] = value

    def additional_save_attributes(self):
        """Generator to return any additional save attributes"""
        for k, v in self.__persist_attributes.items():
            yield k, v

    def delete(self):
        """Delete this report from the backing datastore"""
        try:
            self.request.fs.delete(ObjectId(self.filename))
            logging.info("Deleted report %s", self.filename)
            return self.filename
        except:
            logging.warning("Delete failed on report %s", self.filename)
            raise NotFound

    def __getitem__(self, key):
        """Traversal method

        Called during pyramid traversal, likely on the second segment
        of the request, after matching one of the BaseReport
        subclasses on the first request.  The segment 'key' refers to
        the filename or object identifier

        """
        # If this instance already has a filename, stop traversal
        if hasattr(self, 'filename'):
            logging.debug("stop traversal on key: %s", key)
            raise KeyError
        logging.debug("traversal to report: %s", key)
        self.filename = key
        return self


class EssenceReport(BaseReport):
    """Traversal context for essence reports"""
    report_type = 'essence'

    def __init__(self, request=None, key=None):
        """Initialize contenxt, typically invoked from the root factory.

        :param request: the request object, if available
        :param key: relevant portion of request - i.e. essence or essence_pcE

        """
        super(EssenceReport, self).__init__(request)
        if key == 'essence':
            return

        # Is there a valid ESSENCE patient class?
        pc_regex = re.compile('essence_pc([EIO])')
        pc = pc_regex.match(key)
        if pc:
            self.add_save_attribute('patient_class',
                                    pc.groups()[0])
        else:
            raise KeyError


class LongitudinalReport(BaseReport):
    """Traversal context for longitudinal database files"""
    report_type = 'longitudinal'

    def __init__(self, request=None):
        super(LongitudinalReport, self).__init__(request)


class Search(object):
    """Search context - look up existing documents"""
    def __init__(self, request=None):
        self.request = request

    def __getitem__(self, key):
        """Traversal method"""
        # Don't expect this to get called, a query string parameter
        # should define search terms
        raise KeyError

    def search(self, criteria, limit=0):
        """Search for documents matching criteria

        :param criteria: dictionary defining search terms
        :param limit: curtail lenght of result set

        Returns empty string on no match, document contents on
        a perfect match or with limit=1, and a list of document
        meta-data on multiple matches.

        """
        cursor = self.request.document_store.find(criteria).limit(limit)
        count = cursor.count(with_limit_and_skip=True)
        if count == 0:
            return ''
        elif count == 1:
            # with a single document, return contents
            document = cursor.next()
            content = self.request.fs.get(document.get('_id'))
            compression = document.get('compression')
            if compression:
                content = expand_file(fileobj=content,
                                      zip_protocol=compression)
            return content.read()

        return [doc for doc in cursor]
