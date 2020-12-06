import json
import xbmc

from artworkprocessor import ArtworkProcessor
from libs import mediainfo as info, mediatypes, pykodi, quickjson
from libs.addonsettings import settings
from libs.pykodi import log

STATUS_IDLE = 'idle'
STATUS_SIGNALLED = 'signalled'
STATUS_PROCESSING = 'processing'

class ArtworkService(xbmc.Monitor):
    def __init__(self):
        super(ArtworkService, self).__init__()
        self.abort = False
        self.processor = ArtworkProcessor(self)
        self.recentvideos = {'movie': [], 'tvshow': [], 'episode': [], 'musicvideo': []}
        self.stoppeditems = set()
        self._signal = None
        self._status = None
        self.status = STATUS_IDLE

    def reset_recent(self):
        self.recentvideos = {'movie': [], 'tvshow': [], 'episode': [], 'musicvideo': []}

    def abortRequested(self):
        return self.waitForAbort(0.0001)

    def waitForAbort(self, timeout=0):
        return self.abort or super(ArtworkService, self).waitForAbort(timeout)

    def really_waitforabort(self, timeout=0):
        return super(ArtworkService, self).waitForAbort(timeout)

    @property
    def scanning(self):
        return pykodi.get_conditional('Library.IsScanningVideo | Library.IsScanningMusic')

    @property
    def status(self):
        return self._status

    @status.setter
    def status(self, value):
        self._status = value
        self.abort = False
        pykodi.execute_builtin('SetProperty(ArtworkDump.Status, {0}, Home)'.format(value))

    @property
    def signal(self):
        return self._signal

    @signal.setter
    def signal(self, value):
        self._signal = value
        self.status = STATUS_SIGNALLED if value else STATUS_IDLE

    def watchitem(self, data):
        can_use_data = 'item' in data and data['item'].get('id') and data['item'].get('id') != -1
        return can_use_data and 'playcount' not in data and data['item'].get('type') in self.recentvideos \
            and data.get('added')

    def notify_finished(self, content, success):
        if success:
            pykodi.execute_builtin('NotifyAll(script.artwork.dump, On{0}ProcessingFinished)'.format(content))
        else:
            self.processor.close_progress()

    def onNotification(self, sender, method, data):
        if method.startswith('Other.') and sender != 'script.artwork.dump:control':
            return
        if method == 'Other.CancelCurrent':
            if self.status == STATUS_PROCESSING:
                self.abort = True
            elif self.signal:
                self.signal = None
                self.processor.close_progress()
        elif method == 'Other.ProcessVideos':
            self.processor.create_progress()
            self.signal = 'videos'
        elif method == 'Other.ProcessMusic':
            self.processor.create_progress()
            self.signal = 'music'
        elif method == 'Player.OnStop':
            if settings.enableservice:
                data = json.loads(data)
                if self.watchitem(data):
                    self.stoppeditems.add((data['item']['type'], data['item']['id']))
        elif method == 'VideoLibrary.OnScanStarted':
            if settings.enableservice and self.status == STATUS_PROCESSING:
                self.abort = True
        elif method == 'VideoLibrary.OnScanFinished':
            if settings.enableservice:
                self.signal = 'videos'
                self.processor.create_progress()
        elif method == 'VideoLibrary.OnUpdate':
            if not settings.enableservice:
                return
            data = json.loads(data)
            if not self.watchitem(data):
                return
            if (data['item']['type'], data['item']['id']) in self.stoppeditems:
                self.stoppeditems.remove((data['item']['type'], data['item']['id']))
                return
            if not self.scanning:
                self.recentvideos[data['item']['type']].append(data['item']['id'])
                self.signal = 'recentvideos'
        elif method == 'AudioLibrary.OnScanFinished':
            if settings.enableservice_music:
                self.signal = 'music'

    def run(self):
        while not self.really_waitforabort(5):
            if self.scanning:
                continue
            if self.signal:
                signal = self.signal
                self._signal = None
                if signal == 'recentvideos':
                    # Add a delay to catch rapid fire VideoLibrary.OnUpdate
                    self.signal = 'recentvideos_really'
                    continue
                self.status = STATUS_PROCESSING
                if signal == 'videos':
                    successful = self.process_allvideos()
                    self.notify_finished('Video', successful)
                if signal == 'music':
                    successful = self.process_allmusic()
                    self.notify_finished('Music', successful)
                elif signal == 'recentvideos_really':
                    self.process_recentvideos()

            self.status = STATUS_IDLE

    def process_allvideos(self):
        log("Processing all video items")
        return self._process_mediatypes(mediatypes.videotypes)

    def process_allmusic(self):
        log("Processing all music items")
        return self._process_mediatypes(mediatypes.audiotypes)

    def _process_mediatypes(self, media_types):
        def chunk_filler():
            for mediatype in media_types:
                for chunk in quickjson.gen_chunked_item_list(mediatype):
                    if self.abortRequested():
                        yield False
                    golist = [info.MediaItem(item) for item in chunk]
                    yield golist

        result = self.processor.process_chunkedlist(chunk_filler())
        return result

    def process_recentvideos(self):
        log("Processing recently added videos")
        newitems = []
        added_seasons = []
        added_moviesets = []
        for mediatype in self.recentvideos:
            for mediaid in self.recentvideos[mediatype]:
                jsonitem = quickjson.get_item_details(mediaid, mediatype)
                newitems.append(info.MediaItem(jsonitem))

                if mediatype == mediatypes.EPISODE and \
                        jsonitem.get('seasonid') and \
                        jsonitem['seasonid'] not in added_seasons:
                    seasonitem = quickjson.get_item_details(jsonitem['seasonid'], mediatypes.SEASON)
                    newitems.append(info.MediaItem(seasonitem))
                    added_seasons.append(jsonitem['seasonid'])

                if mediatype == mediatypes.MOVIE and \
                        jsonitem.get('setid') and \
                        jsonitem['setid'] not in added_moviesets:
                    setitem = quickjson.get_item_details(jsonitem['setid'], mediatypes.MOVIESET)
                    newitems.append(info.MediaItem(setitem))
                    added_moviesets.append(jsonitem['setid'])

                if self.abortRequested():
                    return

        self.reset_recent()
        self.processor.process_chunkedlist([newitems])

    def onSettingsChanged(self):
        log("updating settings")
        settings.update_settings()
        mediatypes.update_settings()

if __name__ == '__main__':
    log('Service started')
    ArtworkService().run()
    log('Service stopped')
