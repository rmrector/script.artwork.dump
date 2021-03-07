import xbmc
import xbmcaddon

from libs import pykodi

PROGRESS_DISPLAY_FULLPROGRESS = 0
PROGRESS_DISPLAY_WARNINGSERRORS = 1
PROGRESS_DISPLAY_NONE = 2 # Only add-on crashes

EXCLUSION_PATH_TYPE_FOLDER = 0
EXCLUSION_PATH_TYPE_PREFIX = 1
EXCLUSION_PATH_TYPE_REGEX = 2

class Settings(object):
    def __init__(self):
        self.update_settings()
        self.update_useragent()

    def update_useragent(self):
        addonversion = xbmcaddon.Addon().getAddonInfo('version')
        self.useragent = 'ArtworkDump/{0} '.format(addonversion) + xbmc.getUserAgent()

    def update_settings(self):
        addon = xbmcaddon.Addon()
        self.datapath = addon.getAddonInfo('profile')
        self.enableservice = addon.getSettingBool('enableservice')
        self.enableservice_music = addon.getSettingBool('enableservice_music')
        self.progressdisplay = addon.getSettingInt('progress_display')
        self.final_notification = addon.getSettingBool('final_notification')
        self.overwrite_existing = addon.getSettingBool('overwrite_existing')
        self.savewith_basefilename = addon.getSettingBool('savewith_basefilename')
        self.savewith_basefilename_mvids = addon.getSettingBool('savewith_basefilename_mvids')
        self.cache_local_video_artwork = addon.getSettingBool('cache_local_video_artwork')
        self.cache_local_music_artwork = addon.getSettingBool('cache_local_music_artwork')
        self.max_multiple_fanart = addon.getSettingInt('max_multiple_fanart')

        self.pathexclusion = []
        for index in range(10):
            index_append = str(index+1)
            option = addon.getSettingBool('exclude.path.option_' + index_append)
            if option:
                exclusiontype = addon.getSettingInt('exclude.path.type_' + index_append)
                folder = addon.getSettingString('exclude.path.folder_' + index_append)
                prefix = addon.getSettingString('exclude.path.prefix_' + index_append)
                regex = addon.getSettingString('exclude.path.regex_' + index_append)
                self.pathexclusion.append({"type": exclusiontype, "folder": folder, "prefix": prefix, "regex": regex})

settings = Settings()
