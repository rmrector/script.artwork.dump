import json
import xbmc
from datetime import datetime, timedelta, timezone

from artworkprocessor import ArtworkProcessor
from libs import mediainfo as info, mediatypes, pykodi, quickjson
from libs.addonsettings import settings, SCAN_NEW_DATABASE, SCAN_NEW_DAYS
from libs.processeditems import ProcessedItems
from libs.pykodi import log

STATUS_IDLE = 'idle'
STATUS_SIGNALLED = 'signalled'
STATUS_PROCESSING = 'processing'

class ArtworkService(xbmc.Monitor):
    def __init__(self):
        super(ArtworkService, self).__init__()
        self.abort = False
        self.processor = ArtworkProcessor(self)
        self.processed = ProcessedItems(settings.determine_new_algo != SCAN_NEW_DATABASE)
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
        elif method == 'Other.ProcessNewVideos':
            self.processor.create_progress()
            self.signal = 'newvideos'
        elif method == 'Other.ProcessAllVideos':
            self.processor.create_progress()
            self.signal = 'allvideos'
        elif method == 'Other.ProcessNewMusic':
            self.processor.create_progress()
            self.signal = 'newmusic'
        elif method == 'Other.ProcessAllMusic':
            self.processor.create_progress()
            self.signal = 'allmusic'
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
                self.signal = 'newvideos'
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
                self.signal = 'newmusic'

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
                if signal == 'allvideos':
                    successful = self.process_allvideos()
                    self.notify_finished('Video', successful)
                    settings.set_last_video_run(str(_get_date_numeric()))
                if signal == 'newvideos':
                    if settings.determine_new_algo == SCAN_NEW_DAYS:
                        do_new = settings.last_video_run and float(settings.last_video_run) > _get_date_numeric(45)
                        successful = self.process_newvideos() if do_new else self.process_allvideos()
                    else:
                        successful = self.process_allvideos(self.processed.does_not_exist)
                    self.notify_finished('Video', successful)
                    settings.set_last_video_run(str(_get_date_numeric()))
                if signal == 'allmusic':
                    successful = self.process_allmusic()
                    self.notify_finished('Music', successful)
                    settings.set_last_music_run(str(_get_date_numeric()))
                if signal == 'newmusic':
                    do_new = settings.last_music_run and float(settings.last_music_run) > _get_date_numeric(45)
                    successful = self.process_newmusic() if do_new else self.process_allmusic()
                    self.notify_finished('Music', successful)
                    settings.set_last_music_run(str(_get_date_numeric()))
                elif signal == 'recentvideos_really':
                    self.process_recentvideos()

            self.status = STATUS_IDLE

    def process_allvideos(self, shouldinclude_fn=None):
        log("Processing all video items")
        return self._process_mediatypes(mediatypes.videotypes, shouldinclude_fn)

    def process_allmusic(self, shouldinclude_fn=None):
        log("Processing all music items")
        return self._process_mediatypes(mediatypes.audiotypes, shouldinclude_fn)

    def _process_mediatypes(self, media_types, shouldinclude_fn):
        media_lists = [quickjson.iter_item_list(mediatype) for mediatype in media_types]
        totalcount = sum(media_list[1] for media_list in media_lists)

        def flatten_to_mediaitems():
            count = 0
            for medialist in media_lists:
                for mediaitem in medialist[0]:
                    item = info.MediaItem(mediaitem)
                    yielditem = not shouldinclude_fn or shouldinclude_fn(item.dbid, item.mediatype, item.label)
                    if count > 1000 or yielditem and count > 0:
                        yield count
                        count = 0
                    if yielditem:
                        yield item
                    else:
                        count += 1

        result = self.processor.process_list_with_total(flatten_to_mediaitems(), totalcount)
        return result

    def process_newvideos(self):
        media_lists = [quickjson.iter_new_item_list(mediatype)
            for mediatype in (mediatypes.EPISODE, mediatypes.MOVIE, mediatypes.MUSICVIDEO)]
        # doesn't count seasons, tvshows, or movie sets
        totalcount = sum(media_list[1] for media_list in media_lists)

        parent_items = []
        added_seasons = set()
        added_tvshows = set()
        added_sets = set()

        def flatten_to_mediaitems():
            for medialist in media_lists:
                for mediaitem in medialist[0]:
                    jsonitem = info.MediaItem(mediaitem)
                    yield jsonitem
                    if jsonitem.mediatype == mediatypes.EPISODE:
                        if mediaitem['seasonid'] not in added_seasons:
                            season = quickjson.get_item_details(mediaitem['seasonid'], mediatypes.SEASON)
                            parent_items.append(info.MediaItem(season))
                            added_seasons.add(mediaitem['seasonid'])
                        if mediaitem['tvshowid'] not in added_tvshows:
                            tvshow = quickjson.get_item_details(mediaitem['tvshowid'], mediatypes.TVSHOW)
                            parent_items.append(info.MediaItem(tvshow))
                            added_tvshows.add(mediaitem['tvshowid'])
                    if jsonitem.mediatype == mediatypes.MOVIE and mediaitem.get('setid'):
                        if mediaitem['setid'] not in added_sets:
                            movieset = quickjson.get_item_details(mediaitem['setid'], mediatypes.MOVIESET)
                            parent_items.append(info.MediaItem(movieset))
                            added_sets.add(mediaitem['setid'])

            for item in parent_items:
                yield item

        result = self.processor.process_list_with_total(flatten_to_mediaitems(), totalcount)
        return result

    def process_newmusic(self):
        start_date = datetime.fromtimestamp(float(settings.last_music_run), timezone.utc)
        media_lists = [quickjson.iter_new_music_list(mediatype, start_date)
            for mediatype in (mediatypes.ARTIST, mediatypes.ALBUM, mediatypes.SONG)]
        totalcount = sum(media_list[1] for media_list in media_lists)

        def flatten_to_mediaitems():
            for medialist in media_lists:
                for mediaitem in medialist[0]:
                    jsonitem = info.MediaItem(mediaitem)
                    yield jsonitem

        result = self.processor.process_list_with_total(flatten_to_mediaitems(), totalcount)
        return result

    def process_recentvideos(self):
        log("Processing recently added videos")
        totalcount = sum(len(self.recentvideos[mediatype]) for mediatype in self.recentvideos)
        if self.processor.process_list_with_total(self.iter_recentvideos(), totalcount):
            self.reset_recent()

    def iter_recentvideos(self):
        added_seasons = []
        added_moviesets = []
        for mediatype in self.recentvideos:
            for mediaid in self.recentvideos[mediatype]:
                jsonitem = quickjson.get_item_details(mediaid, mediatype)
                yield info.MediaItem(jsonitem)

                if mediatype == mediatypes.EPISODE and \
                        jsonitem.get('seasonid') and \
                        jsonitem['seasonid'] not in added_seasons:
                    seasonitem = quickjson.get_item_details(jsonitem['seasonid'], mediatypes.SEASON)
                    yield info.MediaItem(seasonitem)
                    added_seasons.append(jsonitem['seasonid'])

                if mediatype == mediatypes.MOVIE and \
                        jsonitem.get('setid') and \
                        jsonitem['setid'] not in added_moviesets:
                    setitem = quickjson.get_item_details(jsonitem['setid'], mediatypes.MOVIESET)
                    yield info.MediaItem(setitem)
                    added_moviesets.append(jsonitem['setid'])

    def onSettingsChanged(self):
        log("updating settings")
        settings.update_settings()
        mediatypes.update_settings()

def _get_date_numeric(past_days=0):
    '''Get the unix timestamp of the date `past_days` in the the past.'''
    date = pykodi.datetime_now(timezone.utc)
    if past_days:
        date -= timedelta(days=past_days)
    return (date - datetime(1970, 1, 1, tzinfo=timezone.utc)).total_seconds()

if __name__ == '__main__':
    log('Service started')
    ArtworkService().run()
    log('Service stopped')
