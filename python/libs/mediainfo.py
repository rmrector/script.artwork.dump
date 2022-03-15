import os
import re
import xbmc
import xbmcvfs
from functools import wraps
from urllib.parse import quote, unquote

from libs import mediatypes, pykodi, quickjson, utils
from libs.addonsettings import settings
from libs.mediatypes import _split_arttype as split_arttype
from libs.pykodi import log, unquoteimage, localize as L
from libs.quickjson import JSONException

# get_mediatype_id must evaluate these in order
idmap = (('episodeid', mediatypes.EPISODE),
    ('seasonid', mediatypes.SEASON),
    ('tvshowid', mediatypes.TVSHOW),
    ('movieid', mediatypes.MOVIE),
    ('setid', mediatypes.MOVIESET),
    ('musicvideoid', mediatypes.MUSICVIDEO),
    ('songid', mediatypes.SONG),
    ('albumid', mediatypes.ALBUM),
    ('artistid', mediatypes.ARTIST))

class MediaItem(object):
    def __init__(self, jsondata):
        self.label = jsondata['label']
        self.file = unquotearchive(jsondata.get('file'))
        self.mediatype, self.dbid = get_mediatype_id(jsondata)

        self.art = get_own_artwork(jsondata)
        self.uniqueids = _get_uniqueids(jsondata, self.mediatype)
        if self.mediatype in (mediatypes.EPISODE, mediatypes.SEASON):
            self.tvshowid = jsondata['tvshowid']
            self.showtitle = jsondata['showtitle']
            self.season = jsondata['season']
            self.label = self.showtitle + ' - ' + self.label
        if self.mediatype == mediatypes.EPISODE:
            self.episode = jsondata['episode']
        elif self.mediatype == mediatypes.TVSHOW:
            self.season = jsondata['season']
        elif self.mediatype == mediatypes.MOVIESET:
            if mediatypes.central_directories[mediatypes.MOVIESET]:
                self.file = mediatypes.central_directories[mediatypes.MOVIESET] \
                    + utils.path_component(self.label) + '.ext'
        elif self.mediatype == mediatypes.MUSICVIDEO:
            self.label = build_music_label(jsondata)
        elif self.mediatype in mediatypes.audiotypes:
            if self.mediatype in (mediatypes.ALBUM, mediatypes.SONG):
                self.albumid = jsondata['albumid']
                self.label = build_music_label(jsondata)
            self.artistid = None if self.mediatype == mediatypes.ARTIST \
                else jsondata['albumartistid'][0] if jsondata.get('albumartistid') \
                else jsondata['artistid'][0] if jsondata.get('artistid') \
                else None
            self.artist = jsondata['label'] if self.mediatype == mediatypes.ARTIST \
                else jsondata['albumartist'][0] if jsondata.get('albumartist') \
                else jsondata['artist'][0] if jsondata.get('artist') \
                else None
            self.album = jsondata['label'] if self.mediatype == mediatypes.ALBUM \
                else jsondata['album'] if self.mediatype == mediatypes.SONG \
                else None
            if self.mediatype == mediatypes.ALBUM:
                self.discfolders = {}

        self.updatedart = {}
        self.error = None
        self.missingid = False
        self.borked_filename = self.file and '\xef\xbf\xbd' in self.file

def unquotearchive(filepath):
    if not filepath or not filepath.startswith(('rar://', 'zip://')):
        return filepath
    result = filepath[6:].split('/', 1)[0]
    return unquote(result)

def build_music_label(jsondata):
    return jsondata['artist'][0] + ' - ' + jsondata['title'] if jsondata.get('artist') else jsondata['title']

def is_known_mediatype(jsondata):
    return any(x[0] in jsondata for x in idmap)

def get_mediatype_id(jsondata):
    return next((value, jsondata[key]) for key, value in idmap if key in jsondata)

def get_own_artwork(jsondata):
    result = dict((arttype.lower(), unquoteimage(url)) for arttype, url
        in jsondata['art'].items() if '.' not in arttype)

    _remove_bad_icon(result)
    return result

def _get_multiple_fanart(existingart, dbid, mediatype):
    if settings.max_multiple_fanart == 0:
        return existingart
    maxindex = _get_max_assigned_fanart(existingart)
    if maxindex >= 1 or maxindex >= settings.max_multiple_fanart:
        return existingart

    existing_fanarturls = set(url for arttype, url in existingart.items() if split_arttype(arttype)[0] == 'fanart')
    try:
        availableart = quickjson.get_available_art(dbid, mediatype, 'fanart')
        toadd_urls = []
        for art_option in availableart:
            url = unquoteimage(art_option['url'])
            if url not in existing_fanarturls and url not in toadd_urls:
                toadd_urls.append(url)

        counter = maxindex + 1
        for newurl in toadd_urls:
            if counter > settings.max_multiple_fanart:
                break
            key = 'fanart' + (str(counter) if counter else '')
            existingart[key] = newurl
            log("adding extra fanart: " + newurl + " as " + key)
            counter += 1
    except JSONException as ex:
        log("Can't get multiple fanart for item, Kodi 19.0 final version or later required\n" + str(ex))
        pass

    return existingart

def _get_max_assigned_fanart(existingart):
    maxindex = -1
    for arttype in existingart:
        basetype, idx = split_arttype(arttype)
        if basetype == "fanart":
            maxindex = max(idx, maxindex)

    return maxindex

def _remove_bad_icon(artwork_dict):
    if 'icon' not in artwork_dict:
        return
    url = artwork_dict['icon']
    if '/' not in url and '\\' not in url:
        del artwork_dict['icon']

def update_art_in_library(mediatype, dbid, updatedart):
    if updatedart:
        quickjson.set_item_details(dbid, mediatype, art=updatedart)

def remove_local_from_texturecache(urls, include_generated=False):
    exclude = pykodi.remoteimages if include_generated else pykodi.notimagefiles
    for url in urls:
        if url and not url.startswith(exclude):
            quickjson.remove_texture_byurl(url)

def build_video_thumbnail_path(videofile_path):
    if videofile_path.startswith('image://'):
        return videofile_path
    path = utils.get_movie_path_list(videofile_path)[0]
    if path.endswith('.iso'):
        return None
    # Kodi goes lowercase and doesn't encode some chars
    result = 'image://video@{0}/'.format(quote(path, '()!'))
    result = re.sub(r'%[0-9A-F]{2}', lambda mo: mo.group().lower(), result)
    return result

def add_additional_iteminfo(mediaitem):
    '''Get more data from the Kodi library.'''
    if mediaitem.mediatype == mediatypes.SEASON:
        tvshow = get_cached_tvshow(mediaitem.tvshowid)
        mediaitem.file = tvshow['file']
    elif mediaitem.mediatype == mediatypes.ALBUM:
        folders = _identify_album_folders(mediaitem)
        if folders:
            mediaitem.file, mediaitem.discfolders = folders

    if mediatypes.add_multipleart(mediaitem.mediatype):
        mediaitem.art = _get_multiple_fanart(mediaitem.art, mediaitem.dbid, mediaitem.mediatype)

def _identify_album_folders(mediaitem):
    songs = get_cached_songs(mediaitem.albumid)
    folders = set(os.path.dirname(song['file']) for song in songs)
    if len(folders) == 1: # all songs only in one folder
        folder = folders.pop()
        if not _shared_albumfolder(folder):
            return folder + utils.get_pathsep(folder), {}
    elif len(folders) > 1: # split to multiple folders
        discs = {}
        for folder in folders:
            if _shared_albumfolder(folder):
                return
            discnum = next(s['disc'] for s in songs if os.path.dirname(s['file']) == folder)
            if discnum:
                discs[discnum] = folder + utils.get_pathsep(folder)
        # `os.path.commonpath` clobbers some paths
        commonpath = os.path.dirname(os.path.commonprefix(list(folders)))
        if commonpath:
            commonpath += utils.get_pathsep(commonpath)
        if commonpath or discs:
            return commonpath, discs

def _shared_albumfolder(folder):
    songs = get_cached_songs_bypath(folder + utils.get_pathsep(folder))
    albums = set(song['albumid'] for song in songs)
    return len(albums) > 1

def _get_uniqueids(jsondata, mediatype):
    uniqueids = {}
    for uid in jsondata.get('uniqueid', {}):
        if jsondata['uniqueid'][uid]:
            uniqueids[uid] = jsondata['uniqueid'][uid]
    if '/' in uniqueids.get('tvdb', ''):
        # PlexKodiConnect sets these
        uniqueids['tvdbse'] = uniqueids['tvdb']
        del uniqueids['tvdb']
    if 'unknown' in uniqueids:
        uniqueid = uniqueids['unknown']
        if uniqueid.startswith('tt') and 'imdb' not in uniqueids:
            uniqueids['imdb'] = uniqueid
            del uniqueids['unknown']
    if jsondata.get('musicbrainzartistid'):
        uniqueids['mbartist'] = jsondata['musicbrainzartistid'][0]
    elif jsondata.get('musicbrainzalbumartistid'):
        uniqueids['mbartist'] = jsondata['musicbrainzalbumartistid'][0]
    if jsondata.get('musicbrainzalbumid'):
        uniqueids['mbalbum'] = jsondata['musicbrainzalbumid']
    if jsondata.get('musicbrainzreleasegroupid'):
        uniqueids['mbgroup'] = jsondata['musicbrainzreleasegroupid']
    if jsondata.get('musicbrainztrackid'):
        uniqueids['mbtrack'] = jsondata['musicbrainztrackid']
    return uniqueids

# REVIEW: there may be other protocols that just can't be written to
#  xbmcvfs.mkdirs only supports local drives, SMB, and NFS
blacklisted_protocols = ('plugin', 'http')
# whitelist startswith would be something like ['smb://', 'nfs://', '/', r'[A-Z]:\\']

def can_saveartwork(mediaitem):
    if not (mediaitem.file and mediaitem.mediatype in (mediatypes.ALBUM, mediatypes.SONG)):
        if find_central_infodir(mediaitem):
            return True
    if not mediaitem.file:
        return False
    path = utils.get_movie_path_list(mediaitem.file)[0] \
        if mediaitem.mediatype == mediatypes.MOVIE else mediaitem.file
    if path.startswith(blacklisted_protocols) or mediaitem.borked_filename:
        return False
    return True

def build_artwork_basepath(mediaitem, arttype):
    if mediaitem.file and mediaitem.mediatype in (mediatypes.ALBUM, mediatypes.SONG):
        path = os.path.splitext(mediaitem.file)[0]
    else:
        path = find_central_infodir(mediaitem)
    if not path:
        if not mediaitem.file:
            return ''
        path = utils.get_movie_path_list(mediaitem.file)[0] \
            if mediaitem.mediatype == mediatypes.MOVIE else mediaitem.file
        if path.startswith(blacklisted_protocols):
            return ''
        path = os.path.splitext(path)[0]

    sep = utils.get_pathsep(path)
    path, basename = os.path.split(path)
    path += sep
    use_basefilename = mediaitem.mediatype in (mediatypes.EPISODE, mediatypes.SONG) \
        or mediaitem.mediatype == mediatypes.MOVIE and settings.savewith_basefilename \
        or mediaitem.mediatype == mediatypes.MUSICVIDEO and settings.savewith_basefilename_mvids
    if use_basefilename:
        path += basename + '-'
    def snum(num):
        return '-specials' if num == 0 else '-all' if num == -1 else '{0:02d}'.format(num)
    if mediaitem.mediatype == mediatypes.SEASON:
        path += 'season{0}-{1}'.format(snum(mediaitem.season), arttype)
    else:
        path += arttype
    return path

def find_central_infodir(mediaitem):
    # WARN: Yikes, this code is gross
    fromtv = mediaitem.mediatype in (mediatypes.SEASON, mediatypes.EPISODE)
    fromartist = mediaitem.mediatype == mediatypes.ARTIST
    cdtype = mediatypes.TVSHOW if fromtv else mediaitem.mediatype
    basedir = mediatypes.central_directories.get(cdtype)
    if not basedir:
        return None
    slug1 = _get_uniqueslug(mediaitem, mediatypes.ARTIST) if fromartist else None
    title1 = mediaitem.showtitle if fromtv \
        else mediaitem.artist if fromartist else mediaitem.label
    title2 = mediaitem.label if mediaitem.mediatype == mediatypes.EPISODE \
        else None
    sep = utils.get_pathsep(basedir)
    mediayear = mediaitem.year if mediaitem.mediatype == mediatypes.MOVIE else None

    thisdir = _find_existing(basedir, title1, slug1, mediayear)
    if not thisdir:
        if mediaitem.mediatype == mediatypes.MOVIE:
            title1 = '{0} ({1})'.format(mediaitem.label, mediaitem.year)
        thisdir = utils.build_cleanest_name(title1, slug1)
    result = basedir + thisdir + sep
    if not title2:
        return result
    usefiles = mediaitem.mediatype == mediatypes.EPISODE
    thisdir = _find_existing(result, title2, files=usefiles)
    if not thisdir:
        thisdir = utils.build_cleanest_name(title2)
    result += thisdir
    if not usefiles:
        result += sep
    return result

def _find_existing(basedir, name, uniqueslug=None, mediayear=None, files=False):
    for item in get_cached_listdir(basedir)[1 if files else 0]:
        cleantitle, diryear = xbmc.getCleanMovieTitle(item) if mediayear else (item, '')
        if diryear and int(diryear) != mediayear:
            continue
        if files:
            item = item.rsplit('-', 1)[0]
        for title in utils.iter_possible_cleannames(name, uniqueslug):
            if title in (cleantitle, item):
                return item
    return None

def _get_uniqueslug(mediaitem, slug_mediatype):
    if slug_mediatype == mediatypes.ARTIST and mediaitem.artist is not None:
        if len(get_cached_artists(mediaitem.artist)) > 1:
            return mediaitem.uniqueids.get('mbartist', '')[:4]
    elif slug_mediatype == mediatypes.ALBUM and mediaitem.artistid is not None:
        foundone = False
        for album in get_cached_albums(mediaitem.artist, mediaitem.artistid):
            if album['label'] != mediaitem.album:
                continue
            if foundone:
                return mediaitem.uniqueids.get('mbalbum', '')[:4]
            foundone = True
    return None

# TODO: refactor to quickjson.JSONCache maybe

def cacheit(func):
    @wraps(func)
    def wrapper(*args):
        key = (func.__name__,) + args
        if key not in quickcache:
            quickcache[key] = func(*args)
        return quickcache[key]
    return wrapper

@cacheit
def get_cached_listdir(path):
    return xbmcvfs.listdir(path)

@cacheit
def get_cached_artists(artistname):
    return quickjson.get_artists_byname(artistname)

@cacheit
def get_cached_albums(artistname, dbid):
    return quickjson.get_albums(artistname, dbid)

@cacheit
def get_cached_songs(dbid):
    return quickjson.get_songs(mediatypes.ALBUM, dbid)

@cacheit
def get_cached_songs_bypath(path):
    return quickjson.get_songs(songfilter={'field': 'path', 'operator': 'is', 'value': path})

def get_cached_tvshow(dbid):
    tvshows = get_cached_tvshows()
    return next(show for show in tvshows if show['tvshowid'] == dbid)

@cacheit
def get_cached_tvshows():
    return quickjson.get_item_list(mediatypes.TVSHOW)

quickcache = {}
def clear_cache():
    quickcache.clear()
