import sys
import xbmc
import xbmcgui
from itertools import chain

from artworkprocessor import ArtworkProcessor
from filemanager import FileManager, FileError
from libs import mediainfo as info, mediatypes, pykodi, quickjson, utils
from libs.addonsettings import settings
from libs.pykodi import localize as L, log

class M(object):
    STOP = 32403
    FOR_ALL_VIDEOS = 32419
    FOR_ALL_AUDIO = 32422

def main():
    settings.update_settings()
    mediatypes.update_settings()

    processor = ArtworkProcessor()
    if processor.processor_busy:
        options = [(L(M.STOP), 'CancelCurrent')]
    else:
        options = [(L(M.FOR_ALL_VIDEOS), 'ProcessVideos'), (L(M.FOR_ALL_AUDIO), 'ProcessMusic')]

    selected = xbmcgui.Dialog().select("Artwork Beef", [option[0] for option in options])
    if selected >= 0 and selected < len(options):
        pykodi.execute_builtin('NotifyAll(script.artwork.dump:control, {0})'.format(options[selected][1]))

if __name__ == '__main__':
    main()
