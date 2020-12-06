import json
from itertools import chain

from libs import mediatypes, pykodi
from libs.pykodi import log

# [0] method part, [1] list: properties, [2] dict: extra params
typemap = {mediatypes.MOVIE: ('Movie', ['art', 'imdbnumber', 'file', 'premiered', 'uniqueid', 'setid'], None),
    mediatypes.MOVIESET: ('MovieSet', ['art'], {'movies': {'properties': ['art', 'file']}}),
    mediatypes.TVSHOW: ('TVShow', ['art', 'imdbnumber', 'season', 'file', 'premiered', 'uniqueid'], None),
    mediatypes.EPISODE: ('Episode', ['art', 'uniqueid', 'tvshowid', 'season', 'episode', 'file', 'showtitle', 'seasonid'], None),
    mediatypes.SEASON: ('Season', ['season', 'art', 'tvshowid', 'showtitle'], None),
    mediatypes.MUSICVIDEO: ('MusicVideo', ['art', 'file', 'title', 'artist'], None),
    mediatypes.ARTIST: ('Artist', ['art', 'musicbrainzartistid'], None),
    mediatypes.ALBUM: ('Album', ['art', 'musicbrainzalbumid', 'musicbrainzreleasegroupid',
        'musicbrainzalbumartistid', 'artist', 'artistid', 'title'], None),
    mediatypes.SONG: ('Song', ['art', 'musicbrainztrackid', 'musicbrainzalbumartistid', 'album',
        'albumartist', 'albumartistid', 'albumid', 'file', 'disc', 'artist', 'title'], None)}

def get_item_details(dbid, mediatype):
    assert mediatype in typemap

    mapped = typemap[mediatype]
    basestr = 'VideoLibrary.Get{0}Details' if mediatype not in mediatypes.audiotypes else 'AudioLibrary.Get{0}Details'
    json_request = get_base_json_request(basestr.format(mapped[0]))
    json_request['params'][mediatype + 'id'] = dbid
    json_request['params']['properties'] = mapped[1]
    if mapped[2]:
        json_request['params'].update(mapped[2])
    json_result = pykodi.execute_jsonrpc(json_request)

    result_key = mediatype + 'details'
    if check_json_result(json_result, result_key, json_request):
        result = json_result['result'][result_key]
        return result

def get_item_list(mediatype, extraparams=None, overrideprops=None):
    json_request, json_result = _inner_get_item_list(mediatype, extraparams, overrideprops)

    result_key = mediatype + 's'
    if not check_json_result(json_result, result_key, json_request):
        return []
    return _inner_get_result(json_result, mediatype)

def _inner_get_item_list(mediatype, extraparams=None, overrideprops=None):
    assert mediatype in typemap

    mapped = typemap[mediatype]
    basestr = 'VideoLibrary.Get{0}s' if mediatype not in mediatypes.audiotypes else 'AudioLibrary.Get{0}s'
    json_request = get_base_json_request(basestr.format(mapped[0]))
    json_request['params']['sort'] = {'method': 'sorttitle', 'order': 'ascending'}
    json_request['params']['properties'] = mapped[1] if overrideprops is None else overrideprops
    if extraparams:
        json_request['params'].update(extraparams)
    json_result = pykodi.execute_jsonrpc(json_request)
    return json_request, json_result

def _inner_get_result(json_result, mediatype):
    result = json_result['result'][mediatype + 's']
    return result

def gen_chunked_item_list(mediatype, extraparams=None, overrideprops=None, chunksize=1000):
    if mediatype == mediatypes.EPISODE:
        chunksize *= 4
    if extraparams is None:
        extraparams = {}
    result_key = mediatype + 's'

    source_exhausted = False
    lastend = 0
    while not source_exhausted:
        extraparams['limits'] = {'start': lastend, 'end': lastend + chunksize}

        json_request, json_result = _inner_get_item_list(mediatype, extraparams, overrideprops)
        if not check_json_result(json_result, result_key, json_request):
            break

        if lastend + chunksize >= json_result['result']['limits']['total']:
            source_exhausted = True
        lastend = json_result['result']['limits']['end']

        yield _inner_get_result(json_result, mediatype)

def get_albums(artistname=None, dbid=None):
    if artistname is None or dbid is None:
        return get_item_list(mediatypes.ALBUM)
    # filter artistid is slow for artists with many albums, much faster to filter based on
    # artist name and then filter the result for proper artistID. songs are good, though
    allalbums = get_item_list(mediatypes.ALBUM, {'filter':
        {'field': 'artist', 'operator': 'is', 'value': artistname}})
    return [album for album in allalbums if album['artistid'] and album['artistid'][0] == dbid]

def get_artists_byname(artistname):
    return get_item_list(mediatypes.ARTIST,
           {'filter': {"field": "artist", "operator": "is", "value": artistname}}, [])

def get_songs(mediatype=None, dbid=None, songfilter=None):
    if songfilter is None and (mediatype is None or dbid is None):
        return get_item_list(mediatypes.SONG)
    if not songfilter:
        songfilter = {mediatype + 'id': dbid}
    return get_item_list(mediatypes.SONG, {'filter': songfilter})

def set_item_details(dbid, mediatype, **details):
    assert mediatype in typemap

    mapped = typemap[mediatype]
    basestr = 'VideoLibrary.Set{0}Details' if mediatype not in mediatypes.audiotypes else 'AudioLibrary.Set{0}Details'
    json_request = get_base_json_request(basestr.format(mapped[0]))
    json_request['params'] = details
    json_request['params'][mediatype + 'id'] = dbid

    json_result = pykodi.execute_jsonrpc(json_request)
    if not check_json_result(json_result, 'OK', json_request):
        log(json_result)

def get_textures(url=None):
    json_request = get_base_json_request('Textures.GetTextures')
    json_request['params']['properties'] = ['url']
    if url is not None:
        json_request['params']['filter'] = {'field': 'url', 'operator': 'is', 'value': url}

    json_result = pykodi.execute_jsonrpc(json_request)
    if check_json_result(json_result, 'textures', json_request):
        return json_result['result']['textures']
    else:
        return []

def remove_texture(textureid):
    json_request = get_base_json_request('Textures.RemoveTexture')
    json_request['params']['textureid'] = textureid

    json_result = pykodi.execute_jsonrpc(json_request)
    if not check_json_result(json_result, 'OK', json_request):
        log(json_result)

def remove_texture_byurl(url):
    textures = get_textures(url)
    for texture in textures:
        remove_texture(texture['textureid'])

def get_base_json_request(method):
    return {'jsonrpc': '2.0', 'method': method, 'params': {}, 'id': 1}

def get_application_properties(properties):
    json_request = get_base_json_request('Application.GetProperties')
    json_request['params']['properties'] = properties
    json_result = pykodi.execute_jsonrpc(json_request)
    if check_json_result(json_result, None, json_request):
        return json_result['result']

def get_settingvalue(setting):
    json_request = get_base_json_request('Settings.GetSettingValue')
    json_request['params']['setting'] = setting
    json_result = pykodi.execute_jsonrpc(json_request)
    if check_json_result(json_result, None, json_request):
        return json_result['result']['value']

def check_json_result(json_result, result_key, json_request):
    if 'error' in json_result:
        raise JSONException(json_request, json_result)

    return 'result' in json_result and (not result_key or result_key in json_result['result'])

class JSONException(Exception):
    def __init__(self, json_request, json_result):
        self.json_request = json_request
        self.json_result = json_result

        message = "There was an error with a JSON-RPC request.\nRequest: "
        message += json.dumps(json_request, cls=pykodi.PrettyJSONEncoder)
        message += "\nResult: "
        message += json.dumps(json_result, cls=pykodi.PrettyJSONEncoder)
        self.message = message

        super(JSONException, self).__init__(message)
