from pyramid.config import Configurator
from pyramid.events import subscriber
from pyramid.events import NewRequest
import pymongo
from gridfs import GridFS

from pheme.webAPI.resources import Root
from pheme.webAPI.renderers import json_renderer

@subscriber(NewRequest)
def add_mongo_db(event):
    settings = event.request.registry.settings
    db = settings['db_conn'][settings['db_name']]
    event.request.db = db

    # GridFS uses two collections, under the default 'fs' namespace.
    # One for metadata ('fs.files') and another for the chunked
    # data ('fs.chunks').
    # Provide quick aliases for both

    event.request.fs = GridFS(db)
    event.request.document_store = db['fs.files']

def main(global_config, **settings):
    """ This function returns a Pyramid WSGI application.
    """
    config = Configurator(root_factory=Root, settings=settings)
    config.add_renderer('json', json_renderer)

    # mongodb addition
    config.registry.settings['db_conn'] =\
        pymongo.Connection(settings['db_uri'])

    config.add_static_view('static', 'pheme.webAPI:static', cache_max_age=3600)
    #config.add_route('home', '/')
    config.scan()
    return config.make_wsgi_app()
