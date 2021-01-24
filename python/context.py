import sys
import xbmc

from artworkprocessor import ArtworkProcessor
from libs import mediainfo as info, quickjson

def main():
    listitem = sys.listitem
    mediatype = get_mediatype(listitem)
    dbid = get_dbid(listitem)

    if dbid and mediatype:
        processor = ArtworkProcessor()
        item = quickjson.get_item_details(dbid, mediatype)
        processor.process_list((info.MediaItem(item),), True)

def get_mediatype(listitem):
    mediatype = listitem.getVideoInfoTag().getMediaType()
    if not mediatype:
        mediatype = listitem.getMusicInfoTag().getMediaType()
    return mediatype

def get_dbid(listitem):
    dbid = listitem.getVideoInfoTag().getDbId()
    if dbid == -1:
        dbid = listitem.getMusicInfoTag().getDbId()
    return dbid

if __name__ == '__main__':
    main()
