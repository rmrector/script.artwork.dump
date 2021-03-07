import xbmc
import xbmcgui

from artworkprocessor import ArtworkProcessor
from filemanager import FileManager
from libs import mediainfo as info, mediatypes, pykodi, quickjson, utils
from libs.addonsettings import settings
from libs.pykodi import check_utf8, localize as L

class M(object):
    STOP = 32403
    FOR_NEW_VIDEOS = 32417
    FOR_ALL_VIDEOS = 32419
    FOR_NEW_AUDIO = 32420
    FOR_ALL_AUDIO = 32422
    CACHE_VIDEO_ARTWORK = 32424
    CACHE_MUSIC_ARTWORK = 32425
    CACHED_COUNT = 32038
    REMOTE_CONTROL_REQUIRED = 32039
    LISTING_ALL = 32028

    MOVIES = 36901
    SERIES = 36903
    SEASONS = 36905
    EPISODES = 36907
    MOVIESETS = 36911
    MUSICVIDEOS = 36909
    ARTISTS = 36917
    ALBUMS = 36919
    SONGS = 36921

def main():
    settings.update_settings()
    mediatypes.update_settings()

    processor = ArtworkProcessor()
    if processor.processor_busy:
        options = [(L(M.STOP), 'CancelCurrent')]
    else:
        options = [
            (L(M.FOR_NEW_VIDEOS), 'ProcessNewVideos'),
            (L(M.FOR_ALL_VIDEOS), 'ProcessAllVideos'),
            (L(M.FOR_NEW_AUDIO), 'ProcessNewMusic'),
            (L(M.FOR_ALL_AUDIO), 'ProcessAllMusic'),
            (L(M.CACHE_VIDEO_ARTWORK), cache_artwork),
            (L(M.CACHE_MUSIC_ARTWORK), lambda: cache_artwork('music'))
        ]

    selected = xbmcgui.Dialog().select("Artwork Dump", [option[0] for option in options])
    if selected >= 0 and selected < len(options):
        action = options[selected][1]
        if isinstance(action, str):
            pykodi.execute_builtin('NotifyAll(script.artwork.dump:control, {0})'.format(action))
        else:
            action()

def cache_artwork(librarytype='videos'):
    fileman = FileManager(True)
    if not fileman.imagecachebase:
        xbmcgui.Dialog().notification("Artwork Dump", L(M.REMOTE_CONTROL_REQUIRED),
            xbmcgui.NOTIFICATION_WARNING)
        return
    heading = L(M.CACHE_VIDEO_ARTWORK if librarytype == 'videos' else M.CACHE_MUSIC_ARTWORK)
    cached = runon_medialist(lambda mi: fileman.cachefor(mi.art, False), heading, librarytype, fg=False)
    xbmcgui.Dialog().ok("Artwork Dump", L(M.CACHED_COUNT).format(cached))

def runon_medialist(function, heading, medialist='videos', typelabel=None, fg=False):
    progress = xbmcgui.DialogProgress() if fg else xbmcgui.DialogProgressBG()
    progress.create(heading)
    monitor = xbmc.Monitor()

    if medialist == 'videos':
        steps_to_run = [(lambda: quickjson.get_item_list(mediatypes.MOVIE), L(M.MOVIES)),
            (info.get_cached_tvshows, L(M.SERIES)),
            (lambda: quickjson.get_item_list(mediatypes.SEASON), L(M.SEASONS)),
            (lambda: quickjson.get_item_list(mediatypes.MOVIESET), L(M.MOVIESETS)),
            (lambda: quickjson.get_item_list(mediatypes.EPISODE), L(M.EPISODES)),
            (lambda: quickjson.get_item_list(mediatypes.MUSICVIDEO), L(M.MUSICVIDEOS))]
    elif medialist == 'music':
        steps_to_run = [(lambda: quickjson.get_item_list(mediatypes.ARTIST), L(M.ARTISTS)),
            (lambda: quickjson.get_item_list(mediatypes.ALBUM), L(M.ALBUMS)),
            (lambda: quickjson.get_item_list(mediatypes.SONG), L(M.SONGS))]
    else: # medialist is already a list of items
        steps_to_run = ((lambda: medialist, typelabel),)
    stepsize = 100 // len(steps_to_run)

    def update_art_for_items(items, start):
        changedcount = 0
        for i, item in enumerate(items):
            progress_args = [start + i * stepsize // len(items)]
            if not fg:
                progress_args.append(heading)
            progress_args.append(item['label'] if check_utf8(item['label']) else None)
            progress.update(*progress_args)

            item = info.MediaItem(item)
            if item.mediatype == mediatypes.SEASON:
                item.file = info.get_cached_tvshow(item.tvshowid)['file']
            updates = function(item)
            if isinstance(updates, int):
                changedcount += updates
            else:
                processed = utils.get_simpledict_updates(item.art, updates)
                if processed:
                    info.update_art_in_library(item.mediatype, item.dbid, processed)
                    changedcount += len(processed)

            if monitor.abortRequested() or fg and progress.iscanceled():
                break
        return changedcount

    fixcount = 0
    for i, (list_fn, listtype) in enumerate(steps_to_run):
        start = i * stepsize
        progress.update(start, message=L(M.LISTING_ALL).format(listtype))
        fixcount += update_art_for_items(list_fn(), start)
        if monitor.abortRequested() or fg and progress.iscanceled():
            break

    info.clear_cache()
    progress.close()
    return fixcount

if __name__ == '__main__':
    main()
