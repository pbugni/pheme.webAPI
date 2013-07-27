import datetime
from bson.objectid import ObjectId

from pyramid.renderers import JSON


def datetime_adapter(obj, request):
    return obj.isoformat()


def bson_objectid_adapter(obj, request):
    return str(obj)

json_renderer = JSON()
json_renderer.add_adapter(datetime.datetime, datetime_adapter)
json_renderer.add_adapter(ObjectId, bson_objectid_adapter)

#class MongoEncoder(json.JSONEncoder):
#    def default(self, obj, **kwargs):
#        if isinstance(obj, ObjectId):
#            return str(obj)
#        elif isintance(obj, datetime):
#            return obj.isoformat()
#        else:
#            return json.JSONEncoder.default(obj, **kwargs)
#
#
#
#    # Pyramid >=1.4 can add adapters to json renderer, not released
#    # meanwhile, fix the types that can't be natively JSON encoded
#    for k, v in document.items():
#        if isinstance(v, datetime):
#            document[k] = v.isoformat()
#        if isinstance(v, ObjectId):
#            document[k] = str(v)
