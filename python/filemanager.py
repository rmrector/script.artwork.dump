import os
import re
import urllib.parse as urlparse
import xbmc
import xbmcvfs
from contextlib import closing

from libs import mediainfo as info, mediatypes, pykodi, quickjson
from libs.addonsettings import settings, EXISTING_FILE_IGNORE, EXISTING_FILE_OVERWRITE, EXISTING_FILE_USE_EXISTING
from libs.pykodi import localize as L, log
from libs.webhelper import Getter, GetterError

CANT_CONTACT_PROVIDER = 32034
HTTP_ERROR = 32035
CANT_WRITE_TO_FILE = 32037

FILEERROR_LIMIT = 3
PROVIDERERROR_LIMIT = 3

typemap = {'image/jpeg': 'jpg', 'image/png': 'png', 'image/gif': 'gif'}

class FileManager(object):
    def __init__(self, bigcache=False):
        self.getter = Getter()
        self.getter.session.headers['User-Agent'] = settings.useragent
        self.size = 0
        self.fileerror_count = 0
        self.provider_errors = {}
        self.alreadycached = None if not bigcache else set()
        self.can_precache_specialimages = pykodi.get_kodi_version() >= 21
        self.extract_video_thumb = (
            self.can_precache_specialimages and
            bool(quickjson.get_settingvalue('myvideos.extractthumb')))

    def downloadfor(self, mediaitem):
        if self.fileerror_count >= FILEERROR_LIMIT:
            return False, ''
        if not info.can_saveartwork(mediaitem):
            return False, ''
        to_download = get_downloadable_art(mediaitem)
        if not to_download:
            return False, ''
        services_hit = False
        error = ''
        for arttype, url in to_download.items():
            hostname = urlparse.urlparse(url).netloc
            if self.provider_errors.get(hostname, 0) >= PROVIDERERROR_LIMIT:
                continue
            full_basefilepath = info.build_artwork_basepath(mediaitem, arttype)
            if not full_basefilepath:
                continue
            test_basefilepath = full_basefilepath + '.' + get_test_extension(url)
            if xbmcvfs.exists(test_basefilepath):
                message = "Overwriting existing file '{0}' due to configuration" \
                        if settings.handle_existing_files == EXISTING_FILE_OVERWRITE \
                    else "Using existing file '{0}' due to configuration" \
                        if settings.handle_existing_files == EXISTING_FILE_USE_EXISTING \
                    else "Not overwriting existing file '{0}' due to configuration"
                log(message.format(test_basefilepath), xbmc.LOGINFO)
                if settings.handle_existing_files == EXISTING_FILE_IGNORE:
                    continue
                if settings.handle_existing_files == EXISTING_FILE_USE_EXISTING:
                    mediaitem.updatedart[arttype] = test_basefilepath
                    continue
            else:
                log("Kodi says this file does not exist\n" + test_basefilepath)

            result, err = self.doget(url)
            if err:
                error = err
                self.provider_errors[hostname] = self.provider_errors.get(hostname, 0) + 1
                continue
            else:
                self.provider_errors[hostname] = 0
            if not result:
                continue
            self.size += int(result.headers.get('content-length', 0))
            services_hit = True
            ext = get_file_extension(result.headers.get('content-type'), url)
            if not ext:
                log("Can't determine extension for '{0}'\nfor image type '{1}'".format(url, arttype))
                continue
            full_basefilepath += '.' + ext
            folder = os.path.dirname(full_basefilepath)
            if not xbmcvfs.exists(folder):
                xbmcvfs.mkdirs(folder)
            file_ = xbmcvfs.File(full_basefilepath, 'wb')
            with closing(file_):
                if not file_.write(bytearray(result.content)):
                    self.fileerror_count += 1
                    raise FileError(L(CANT_WRITE_TO_FILE).format(full_basefilepath))
                self.fileerror_count = 0
            mediaitem.updatedart[arttype] = full_basefilepath
            log("downloaded '{0}'\nto image file '{1}'".format(url, full_basefilepath))
        return services_hit, error

    def doget(self, url, **kwargs):
        try:
            result = self.getter(url, **kwargs)
            if not result and url.startswith('http://'):
                result, err = self.doget('https://' + url[7:])
                if err or not result:
                    result = None
            return result, None
        except GetterError as ex:
            if ex.response is not None and ex.response.status_code == 403:
                # TVDB returns Forbidden for certain images. Don't show an error message, replace it
                return None, None
            message = L(CANT_CONTACT_PROVIDER) if ex.connection_error \
                else L(HTTP_ERROR).format(ex.message) + '\n' + url
            return None, message

    def set_bigcache(self):
        if self.alreadycached is None:
            self.alreadycached = set()

    def cachefor(self, artmap):
        urls = [url for url in artmap.values() if url and self.can_cache_image(url)]
        if not urls:
            return 0
        if self.alreadycached is not None:
            if not self.alreadycached:
                self.alreadycached = set(pykodi.unquoteimage(texture['url']) for texture in quickjson.get_textures()
                    if not pykodi.unquoteimage(texture['url']).startswith('http'))
            alreadycached = self.alreadycached
        else:
            alreadycached = set(pykodi.unquoteimage(texture['url']) for texture in quickjson.get_textures(urls))
        count = [0]
        for path in urls:
            if path in alreadycached:
                continue
            self.vfs_worker(path, count)
        return count[0]

    def vfs_worker(self, path, count):
        with xbmcvfs.File(pykodi.quoteimage(path)) as f:
            count[0] += 1

    def can_cache_image(self, texture_url: str) -> bool:
        parsed = pykodi.parseimage(texture_url)
        if parsed.scheme != 'image' or parsed.file.startswith('http'):
            return False
        if parsed.specialtype == 'video':
            return self.extract_video_thumb
        if parsed.specialtype:
            return self.can_precache_specialimages
        return True

def get_test_extension(request_url, re_search=re.compile(r'\.\w*$')):
    if re.search(re_search, request_url):
        return request_url.rsplit('.', 1)[1]
    return 'jpg'

def get_file_extension(contenttype, request_url, re_search=re.compile(r'\.\w*$')):
    if contenttype in typemap:
        return typemap[contenttype]
    if re.search(re_search, request_url):
        return request_url.rsplit('.', 1)[1]
    return None

def get_downloadable_art(mediaitem):
    downloadable = dict(mediaitem.art)
    for arttype in list(downloadable):
        if not downloadable[arttype] or not downloadable[arttype].startswith('http') or \
                not mediatypes.downloadartwork(mediaitem.mediatype, arttype):
            del downloadable[arttype]
    return downloadable

class FileError(Exception):
    def __init__(self, message, cause=None):
        super(FileError, self).__init__()
        self.cause = cause
        self.message = message
