import os
import re
import xbmc
import xbmcgui

from filemanager import FileManager, FileError
from libs import mediainfo as info, mediatypes, quickjson
from libs.addonsettings import settings, PROGRESS_DISPLAY_FULLPROGRESS, PROGRESS_DISPLAY_NONE, EXCLUSION_PATH_TYPE_FOLDER, EXCLUSION_PATH_TYPE_PREFIX, EXCLUSION_PATH_TYPE_REGEX
from libs.pykodi import localize as L, log, get_conditional
from libs.quickjson import JSONException

ADDING_ARTWORK_MESSAGE = 32020
ARTWORK_UPDATED_MESSAGE = 32022
NO_ARTWORK_UPDATED_MESSAGE = 32023
PROVIDER_ERROR_MESSAGE = 32024
FILENAME_ENCODING_ERROR = 32040

THROTTLE_TIME = 0.15

class ArtworkProcessor(object):
    def __init__(self, monitor=None):
        self.monitor = monitor or xbmc.Monitor()
        self.progress = xbmcgui.DialogProgressBG()
        self.visible = False
        self.downloader = None
        settings.update_settings()
        mediatypes.update_settings()

    @property
    def processor_busy(self):
        return get_conditional('![String.IsEqual(Window(Home).Property(ArtworkDump.Status),idle)]')

    def create_progress(self):
        if not self.visible and settings.progressdisplay == PROGRESS_DISPLAY_FULLPROGRESS:
            self.progress.create("Artwork Dump: " + L(ADDING_ARTWORK_MESSAGE), "")
            self.visible = True

    def update_progress(self, percent, message, heading=None):
        if self.visible and settings.progressdisplay == PROGRESS_DISPLAY_FULLPROGRESS:
            self.progress.update(percent, heading, message)

    def finalupdate(self, message):
        if settings.final_notification:
            xbmcgui.Dialog().notification("Artwork Dump", message, '-', 8000)
        elif settings.progressdisplay == PROGRESS_DISPLAY_FULLPROGRESS:
            self.update_progress(100, message)
            try:
                self.monitor.really_waitforabort(8)
            except AttributeError:
                self.monitor.waitForAbort(8)

    def close_progress(self):
        if self.visible and settings.progressdisplay == PROGRESS_DISPLAY_FULLPROGRESS:
            self.progress.close()
            self.visible = False

    def notify_warning(self, message, header=None, error=False):
        if settings.progressdisplay != PROGRESS_DISPLAY_NONE:
            header = "Artwork Dump: " + header if header else "Artwork Dump"
            xbmcgui.Dialog().notification(header, message,
                xbmcgui.NOTIFICATION_ERROR if error else xbmcgui.NOTIFICATION_WARNING)

    def init_run(self, show_progress=False, big_list=False):
        self.downloader = FileManager(big_list)
        populate_centraldirs()
        if show_progress:
            self.create_progress()

    def finish_run(self):
        info.clear_cache()
        self.downloader = None
        self.close_progress()

    def process_chunkedlist(self, chunkedlist, alwaysnotify=False):
        self.init_run(True, True)
        aborted = False
        artcount = 0
        for medialist in chunkedlist:
            if self.monitor.abortRequested() or medialist == False:
                aborted = True
                break
            this_aborted, this_artcount = self._process_list(medialist)
            artcount += this_artcount
            if this_aborted:
                aborted = True
                break
        if artcount or alwaysnotify:
            self.finalupdate(finalmessage(artcount))
        self.finish_run()
        return not aborted

    def _process_list(self, medialist):
        artcount = 0
        currentitem = 0
        aborted = False
        for mediaitem in medialist:
            if is_excluded(mediaitem):
                continue
            self.update_progress(currentitem * 100 // len(medialist), mediaitem.label)
            info.add_additional_iteminfo(mediaitem)
            currentitem += 1
            try:
                services_hit = self._process_item(mediaitem)
            except JSONException as ex:
                mediaitem.error = "Kodi threw a non-descript JSON error."
                log("Kodi threw a non-descript JSON error.", xbmc.LOGERROR)
                log(ex.message, xbmc.LOGERROR)
                services_hit = True
            except FileError as ex:
                services_hit = True
                mediaitem.error = ex.message
                log(ex.message, xbmc.LOGERROR)
                self.notify_warning(ex.message, None, True)
            artcount += len(mediaitem.updatedart)

            if not services_hit:
                if self.monitor.abortRequested():
                    aborted = True
                    break
            elif self.monitor.waitForAbort(THROTTLE_TIME):
                aborted = True
                break
        return aborted, artcount

    def _process_item(self, mediaitem, auto=True):
        log("Processing {0} '{1}' automatically.".format(mediaitem.mediatype, mediaitem.label))
        mediatype = mediaitem.mediatype

        services_hit, error = self.downloader.downloadfor(mediaitem)
        if mediaitem.updatedart:
            add_art_to_library(mediatype, mediaitem.dbid, mediaitem.updatedart)
        self.cachelocal(mediaitem, mediaitem.updatedart)

        if error:
            if isinstance(error, dict):
                header = L(PROVIDER_ERROR_MESSAGE).format(error['providername'])
                error = '{0}: {1}'.format(header, error['message'])
            mediaitem.error = error
            log(error, xbmc.LOGWARNING)
            self.notify_warning(error)
        if mediaitem.borked_filename:
            msg = L(FILENAME_ENCODING_ERROR).format(mediaitem.file)
            if not mediaitem.error:
                mediaitem.error = msg
            log(msg, xbmc.LOGWARNING)
        return services_hit

    def cachelocal(self, mediaitem, toset):
        ismusic = mediaitem.mediatype in mediatypes.audiotypes
        if settings.cache_local_video_artwork and not ismusic or \
                settings.cache_local_music_artwork and ismusic:
            artmap = dict(mediaitem.art)
            artmap.update(toset)
            self.downloader.cachefor(artmap)

def add_art_to_library(mediatype, dbid, selectedart):
    if not selectedart:
        return
    for arttype, url in selectedart.items():
        # Kodi doesn't cache gifs, so force download in `downloader` and
        #   don't leave any HTTP URLs if they can't be saved
        if arttype.startswith('animated') and url and url.startswith('http'):
            selectedart[arttype] = None

    info.update_art_in_library(mediatype, dbid, selectedart)
    info.remove_local_from_texturecache(selectedart.values())

def populate_centraldirs():
    # INFO: out here because there is no callback to detect changes like there is for add-on settings
    path = quickjson.get_settingvalue('musiclibrary.artistsfolder')
    mediatypes.central_directories[mediatypes.ARTIST] = path

    path = quickjson.get_settingvalue('videolibrary.moviesetsfolder')
    mediatypes.central_directories[mediatypes.MOVIESET] = path

def finalmessage(count):
    return L(ARTWORK_UPDATED_MESSAGE).format(count) if count else L(NO_ARTWORK_UPDATED_MESSAGE)

def is_excluded(mediaitem):
    if mediaitem.file is None:
        return False
    for exclusion in settings.pathexclusion:
        if exclusion["type"] == EXCLUSION_PATH_TYPE_FOLDER:
            path_file = os.path.realpath(os.path.join(mediaitem.file, ''))
            path_excl = os.path.realpath(os.path.join(exclusion["folder"], ''))
            if os.path.commonprefix([path_file, path_excl]) == path_excl:
                return True
        if exclusion["type"] == EXCLUSION_PATH_TYPE_PREFIX:
            if mediaitem.file.startswith(exclusion["prefix"]):
                return True
        if exclusion["type"] == EXCLUSION_PATH_TYPE_REGEX:
            if re.match(exclusion["regex"], mediaitem.file):
                return True
    return False
