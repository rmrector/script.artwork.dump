import os
import re
from typing import Iterable, Union
import xbmc
import xbmcgui

from filemanager import FileManager, FileError
from libs import mediainfo as info, mediatypes, quickjson
from libs.addonsettings import settings, PROGRESS_DISPLAY_FULLPROGRESS, PROGRESS_DISPLAY_NONE, EXCLUSION_PATH_TYPE_FOLDER, EXCLUSION_PATH_TYPE_PREFIX, EXCLUSION_PATH_TYPE_REGEX
from libs.processeditems import ProcessedItems
from libs.pykodi import localize as L, log, get_conditional, thumbnailimages, check_utf8
from libs.quickjson import JSONException

ADDING_ARTWORK_MESSAGE = 32020
ARTWORK_UPDATED_MESSAGE = 32022
NO_ARTWORK_UPDATED_MESSAGE = 32023
PROVIDER_ERROR_MESSAGE = 32024
FILENAME_ENCODING_ERROR = 32040

THROTTLE_TIME = 0.15
MESSAGE_CLEAR_COUNT = 200

class ArtworkProcessor(object):
    def __init__(self, monitor=None):
        self.monitor = monitor or xbmc.Monitor()
        self.downloader = None
        self.processed = ProcessedItems()
        self.progressdisplay = ProgressDisplay(
            self.monitor,
            settings.progressdisplay == PROGRESS_DISPLAY_FULLPROGRESS,
            settings.final_notification)
        settings.update_settings()
        mediatypes.update_settings()

    @property
    def processor_busy(self):
        return get_conditional('![String.IsEqual(Window(Home).Property(ArtworkDump.Status),idle)]')

    def create_progress(self, totalcount: int=0):
        self.progressdisplay.update_settings(
            settings.progressdisplay == PROGRESS_DISPLAY_FULLPROGRESS,
            settings.final_notification)
        self.progressdisplay.create_progress(totalcount)

    def close_progress(self):
        self.progressdisplay.close_progress()

    def notify_warning(self, message, header=None, error=False):
        if settings.progressdisplay != PROGRESS_DISPLAY_NONE:
            header = "Artwork Dump: " + header if header else "Artwork Dump"
            xbmcgui.Dialog().notification(header, message,
                xbmcgui.NOTIFICATION_ERROR if error else xbmcgui.NOTIFICATION_WARNING)

    def init_run(self, show_progress, big_list, totalcount):
        self.downloader = FileManager(big_list)

        populate_centraldirs()
        if show_progress:
            self.create_progress(totalcount)

    def finish_run(self):
        info.clear_cache()
        self.downloader = None
        self.progressdisplay.close_progress()

    def process_list(self, in_list, alwaysnotify=False):
        return self.process_list_with_total(in_list, len(in_list), alwaysnotify)

    def process_list_with_total(self, medialist, totalcount, alwaysnotify=False):
        self.init_run(True, totalcount > 100, totalcount)

        aborted, artcount = self._process_list(medialist)
        if artcount or alwaysnotify:
            self.progressdisplay.finalupdate(finalmessage(artcount))
        self.finish_run()

        return not aborted

    def _process_list(self, medialist: Iterable[Union[info.MediaItem, int]]):
        log("Start processing list")
        artcount = 0
        aborted = False
        for mediaitem in medialist:
            self.progressdisplay.update_progress(mediaitem if isinstance(mediaitem, int) else mediaitem.label)
            if is_excluded(mediaitem):
                if self.monitor.abortRequested():
                    aborted = True
                    break
                continue
            info.add_additional_iteminfo(mediaitem)
            try:
                services_hit = self._process_item(mediaitem)
            except JSONException as ex:
                mediaitem.error = "Kodi threw a non-descript JSON error."
                log(mediaitem.error, xbmc.LOGERROR)
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

        log("Finished processing list")
        return aborted, artcount

    def _process_item(self, mediaitem):
        log("Processing {0} '{1}' automatically.".format(mediaitem.mediatype, mediaitem.label))
        mediatype = mediaitem.mediatype

        if mediatypes.generatethumb(mediaitem.mediatype) and \
                not mediaitem.art.get('thumb', '').startswith(thumbnailimages):
            newthumb = info.build_video_thumbnail_path(mediaitem.file)
            if newthumb:
                log("Setting thumbnail to 'kodi generated'")
                mediaitem.updatedart['thumb'] = newthumb
                if 'thumb' in mediaitem.art:
                    del mediaitem.art['thumb']

        services_hit, error = self.downloader.downloadfor(mediaitem)
        if mediaitem.updatedart:
            add_art_to_library(mediatype, mediaitem.dbid, mediaitem.updatedart)
        else:
            log("No updates to artwork")
        self.cachelocal(mediaitem, mediaitem.updatedart)

        if error:
            if isinstance(error, dict):
                header = L(PROVIDER_ERROR_MESSAGE).format(error['providername'])
                error = '{0}: {1}'.format(header, error['message'])
            mediaitem.error = error
            log(error, xbmc.LOGWARNING)
            self.notify_warning(error)
        else:
            self.processed.set_data(mediaitem.dbid, mediatype, mediaitem.label, None)
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

class ProgressDisplay(object):
    def __init__(self, monitor, display_full_progress: bool, display_final_notification: bool):
        self.monitor = monitor
        self.display_full_progress = display_full_progress
        self.display_final_notification = display_final_notification
        self.progress = xbmcgui.DialogProgressBG()
        self.visible = False
        self.totalcount = 0
        self.currentcount = 0
        self.lastmessagecount = 0

    def update_settings(self, display_full_progress: bool, display_final_notification: bool):
        self.display_full_progress = display_full_progress
        self.display_final_notification = display_final_notification

    def create_progress(self, totalcount: int):
        self.totalcount = totalcount
        self.currentcount = 0
        if not self.visible and self.display_full_progress:
            self.progress.create("Artwork Dump: " + L(ADDING_ARTWORK_MESSAGE), "")
            self.visible = True

    def update_progress(self, message: Union[str, int], heading: str=None, final_update=False):
        if isinstance(message, int):
            self.currentcount += message - 1
            message = None
        if not check_utf8(message):
            message = None
        if self.visible and self.display_full_progress:
            percent = 100 if final_update or not self.totalcount else \
                self.currentcount * 100 // self.totalcount
            self.currentcount += 1
            if message:
                self.lastmessagecount = self.currentcount
            elif self.currentcount > self.lastmessagecount + MESSAGE_CLEAR_COUNT:
                message = " "
            self.progress.update(percent, heading, message)

    def finalupdate(self, message: str):
        if self.display_final_notification:
            xbmcgui.Dialog().notification("Artwork Dump", message, '-', 8000)
        elif self.display_full_progress:
            self.update_progress(message, final_update=True)
            try:
                self.monitor.really_waitforabort(8)
            except AttributeError:
                self.monitor.waitForAbort(8)

    def close_progress(self):
        if self.visible and self.display_full_progress:
            self.progress.close()
            self.visible = False

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
    # INFO: out here because there is no callback to detect changes for Kodi settings like there is for add-on settings
    path = quickjson.get_settingvalue('musiclibrary.artistsfolder')
    mediatypes.central_directories[mediatypes.ARTIST] = path

    path = quickjson.get_settingvalue('videolibrary.moviesetsfolder')
    mediatypes.central_directories[mediatypes.MOVIESET] = path

def finalmessage(count):
    return L(ARTWORK_UPDATED_MESSAGE).format(count) if count else L(NO_ARTWORK_UPDATED_MESSAGE)

def is_excluded(mediaitem):
    if isinstance(mediaitem, int):
        return True
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
