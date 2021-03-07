from libs import pykodi

TVSHOW = 'tvshow'
MOVIE = 'movie'
EPISODE = 'episode'
SEASON = 'season'
MOVIESET = 'set'
MUSICVIDEO = 'musicvideo'
ARTIST = 'artist'
ALBUM = 'album'
SONG = 'song'
audiotypes = (ARTIST, ALBUM, SONG)
videotypes = (TVSHOW, MOVIE, EPISODE, SEASON, MOVIESET, MUSICVIDEO)

SETTING_DOWNLOAD_ALL = 0
SETTING_DOWNLOAD_NONE = 1
SETTING_DOWNLOAD_CUSTOM = 2

addon = pykodi.get_main_addon()

_default_mediatypes = {
    TVSHOW: ['poster', 'keyart', 'fanart', 'banner', 'clearlogo', 'landscape', 'clearart', 'characterart'],
    MOVIE: ['poster', 'keyart', 'fanart', 'banner', 'clearlogo', 'landscape', 'clearart', 'discart', 'characterart', 'animatedposter', 'animatedkeyart', 'animatedfanart'],
    MOVIESET: ['poster', 'keyart', 'fanart', 'banner', 'clearlogo', 'landscape', 'clearart', 'discart'],
    SEASON: ['poster', 'fanart', 'banner', 'landscape'],
    EPISODE: ['fanart'],
    MUSICVIDEO: ['poster', 'discart', 'fanart', 'artistthumb', 'banner', 'clearlogo', 'clearart', 'landscape'],
    ARTIST: ['thumb', 'fanart', 'banner', 'clearlogo', 'clearart', 'landscape'],
    ALBUM: ['thumb', 'discart', 'back', 'spine'],
    SONG: ['thumb']
}
_mediatype_settings = {
    MOVIE: 'movieart_downloadlist',
    MOVIESET: 'movieart_downloadlist',
    TVSHOW: 'tvshowart_downloadlist',
    SEASON: 'tvshowart_downloadlist',
    EPISODE: 'episodeart_downloadlist',
    MUSICVIDEO: 'musicvideoart_downloadlist',
    ARTIST: 'artistart_downloadlist',
    ALBUM: 'albumart_downloadlist',
    SONG: 'songart_downloadlist'
}

central_directories = {MOVIESET: False, ARTIST: False}

_download_arttypes = dict(_default_mediatypes)
_togenerate = dict((mediatype, False) for mediatype in (MOVIE, EPISODE, MUSICVIDEO))

_download_all = list(_default_mediatypes.keys())
_managed_mediatypes = list(_default_mediatypes.keys())
_multiplefanart_mediatypes = list(_default_mediatypes.keys())

def disabled(mediatype):
    return mediatype not in _managed_mediatypes

def add_multipleart(mediatype):
    return mediatype in _multiplefanart_mediatypes

def downloadartwork(mediatype, arttype):
    if mediatype in _download_all:
        return True
    arttype, _ = _split_arttype(arttype)
    return arttype in _download_arttypes.get(mediatype, ())

def _split_arttype(arttype):
    basetype = arttype.rstrip('0123456789')
    idx = 0 if basetype == arttype else int(arttype.replace(basetype, ''))
    return basetype, idx

def generatethumb(mediatype):
    return _togenerate.get(mediatype, False)

def update_settings():
    global _managed_mediatypes
    _managed_mediatypes = _get_setting_list('managed_mediatypes')
    global _multiplefanart_mediatypes
    _multiplefanart_mediatypes = _get_setting_list('multiple_fanart_mediatypes')

    for mtype in _togenerate:
        _togenerate[mtype] = addon.getSettingBool(mtype + '.thumb_generate')

    videosetting = addon.getSettingInt('video_download_level')
    audiosetting = addon.getSettingInt('music_download_level')

    global _download_all
    _download_all = []
    if videosetting == SETTING_DOWNLOAD_ALL:
        _download_all.extend(videotypes)
    if audiosetting == SETTING_DOWNLOAD_ALL:
        _download_all.extend(audiotypes)

    download_none = []
    if videosetting == SETTING_DOWNLOAD_NONE:
        download_none.extend(videotypes)
    if audiosetting == SETTING_DOWNLOAD_NONE:
        download_none.extend(audiotypes)

    for mtype in _default_mediatypes:
        if mtype in _download_all or mtype in download_none:
            _download_arttypes[mtype] == []
        else:
            _download_arttypes[mtype] = _get_setting_list(_mediatype_settings[mtype])

def _get_setting_list(setting_name):
    result = addon.getSetting(setting_name).split(', ')
    if len(result) == 1 and result[0] == '':
       return []
    return result

update_settings()
