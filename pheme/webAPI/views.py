from bson.errors import InvalidId
from bson.objectid import ObjectId
from gridfs.errors import NoFile
import json
from pyramid.exceptions import NotFound
from pyramid.httpexceptions import HTTPBadRequest
from pyramid.view import view_config
import logging
import os

from pheme.util.compression import expand_file, zip_file
from pheme.util.format import decode_isofomat_datetime
from pheme.webAPI.resources import BaseReport
from pheme.webAPI.resources import Search
from pheme.webAPI.resources import TransferAgent


@view_config(context=BaseReport, request_method='GET',
             name='metadata', renderer='json')
def display_meta_data(context, request):
    """Present metadata for request document in json format"""
    try:
        oid = ObjectId(context.filename)
    except InvalidId:
        raise NotFound
    return request.document_store.find_one(oid)


@view_config(context=BaseReport, request_method='GET',
             renderer='pheme.webAPI:templates/display.pt')
def display_reports(context, request):
    """View callable method for displaying one or more reports

    If the request included a filename or object id, display the
    contents of the file.  This is picked up in the traversal process,
    set to context.filename.  NB - it may define either the filename
    used when persisting a report, or the document (Object) ID.

    Otherwise, display table of metadata about persisted reports.  If
    the context is a subclass of BaseReport, the list will be limited
    to those reports of like type.

    """
    # If traversal included a filename, display file contents
    if hasattr(context, 'filename'):
        try:
            # Attempt to access 'filename' as the document ID
            try:
                oid = ObjectId(context.filename)
            except InvalidId:
                raise NoFile
            content = request.fs.get(oid)
            document = request.document_store.find_one(oid)
            compression = document.get('compression')

        except NoFile:
            # If the oid was not found, query filename of this type,
            # if the context provided adequate data
            try:
                document = request.document_store.\
                    find_one({'filename': context.filename,
                              'report_type': context.report_type})
            except AttributeError:
                document = None
            if not document:
                raise NotFound
            content = request.fs.get(document['_id'])
            compression = document.get('compression')

        if compression:
            content = expand_file(fileobj=content,
                                  zip_protocol=compression)
        return {'document': content.read()}

    # Otherwise, query for all reports of this type
    documents = ({'filename': doc['filename'],
                  'uploadDate': doc['uploadDate'],
                  'length': doc['length'],
                  'id': doc['_id']}
                 for doc in request.document_store.
                 find({'report_type': context.report_type})
                 if 'filename' in doc)
    return {'documents': documents, 'report_type': context.report_type}


@view_config(context=Search, request_method='GET', renderer='json')
def find_documents(context, request):
    """Present contents or metadata for multiple matching document(s)

    :query param query: JSONified dictionary defining search criteria
    :query param limit: optional restriction to size of result set

    If only a single document is found to match search criteria, the
    document contents will be returned.

    If multiple matches are found, a list of metadata will be
    returned.

    No match results in an empty result.

    """
    query = request.params.get('query')
    criteria = decode_isofomat_datetime(json.loads(query))
    limit = int(request.params.get('limit', 0))  # limit of 0 == no limit
    return context.search(criteria, limit)


# Named @@delete view for browsers which can't send method=DELETE
@view_config(context=BaseReport, request_method='DELETE',
             renderer='pheme.webAPI:templates/deleted.pt')
@view_config(context=BaseReport, request_method='GET',
             name='delete', renderer='pheme.webAPI:templates/deleted.pt')
def delete_report(context, request):
    """View callable method to delete reports

    Remove the requested document / report from the database.

    """
    return {'doc_id': context.delete()}


@view_config(context=BaseReport, request_method='PUT',
             renderer='json')
def upload_report(context, request):
    """View callable method for uploading reports

    Persist the provided content in the database.  If query args
    include the following, take action:

    :query param compress_with: Can be 'gzip' or 'zip' (or None)
      to invoke compression before persisting.

    :query param allow_duplicate_filename: Set true to override
      default of not allowing duplicate filename inserts.

    :query param metadata: Optional dictionary defining additional
      metadata to store with the document.  It is suggested to include
      criteria used in report creation (i.e. 'reportable_region',
      'patient_class', 'include_updates')

    """
    if not hasattr(context, 'filename'):
        raise HTTPBadRequest("Missing upload filename")

    if not hasattr(context, 'file'):
        context.file = request.params[context.filename].file

    def content_type_lookup(compression):
        content_type_map = {None: 'text/plain',
                            'gzip': 'application/x-gzip',
                            'zip': 'application/zip'}
        return content_type_map[compression]

    compression = request.params.get('compress_with', None)
    content_type = content_type_lookup(compression)

    if compression:
        zipfile = zip_file(request.params[context.filename].filename,
                           request.params[context.filename].file,
                           compression)
        context.filename = os.path.basename(zipfile)
        context.file = open(zipfile, 'rb')

    allow_duplicate = request.params.get('allow_duplicate_filename', None)
    if not allow_duplicate:
        # Confirm a matching report wasn't already created.
        criteria = {'filename': context.filename,
                    'report_type': context.report_type}
        metadata = json.loads(request.params.get('metadata', "{}"))
        for k in 'reportable_region', 'patient_class',\
                'include_updates':
            if k in metadata:
                criteria[k] = metadata[k]
        match = request.document_store.find_one(criteria)
        if match:
            err = "duplicate filename '%s' exists for '%s'" %\
                (context.filename, context.report_type)
            logging.error(err)
            raise HTTPBadRequest(err)

    # gridfs automatically includes uploadDate of utcnow()
    # content_type is the Mime-type
    kwargs = {'filename': context.filename,
              'report_type': context.report_type,
              'compression': compression,
              'content_type': content_type}

    for k, v in context.additional_save_attributes():
        kwargs[k] = v

    for k, v in json.loads(request.params.get('metadata', '{}')).items():
        kwargs[k] = v

    oid = request.fs.put(context.file, **kwargs)
    context.file.close()
    logging.info("New report uploaded: http://localhost:6543/%s/%s",
                 context.report_type, oid)
    return {'document_id': str(oid)}


@view_config(context=TransferAgent, request_method='POST',
             renderer='json')
def transfer_report(context, request):
    """View callable method to transfer reports

    Transfer the requested document as requested.

    :query param compress_with: Can be 'gzip' or 'zip' (or None)
      to invoke compression before transfering.  If document was
      orignially persisted in a compressed state, a second compression
      request will be effectively ignored

    """
    # Delegate to transfer agent (i.e. context, determined during traversal)
    logging.info("initiate transfer of %s", context.document['filename'])
    context.transfer_file(request.params.get('compress_with'))
    logging.info("completed transfer of %s", context.document['filename'])

    return {'doc_id': context.document_id}
