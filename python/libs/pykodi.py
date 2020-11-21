import collections
import json
import os
import re
import sys
import time
import urllib
import xbmc
import xbmcaddon
import xbmcvfs
from datetime import datetime

try:
    datetime.strptime('2112-04-01', '%Y-%m-%d')
except TypeError:
    pass

_log_level_tag_lookup = {
    xbmc.LOGDEBUG: 'D',
    xbmc.LOGINFO: 'I'
}

_log_scrub_strings = {}

ADDONID = 'script.artwork.dump'

thumbnailimages = ('image://video@',)
remoteimages = ('http',)
embeddedimages = ('image://video_', 'image://music')
notimagefiles = remoteimages + thumbnailimages + embeddedimages

_main_addon = None
def get_main_addon():
    global _main_addon
    if not _main_addon:
        _main_addon = xbmcaddon.Addon()
    return _main_addon

def localize(messageid):
    if isinstance(messageid, str):
        result = messageid
    elif messageid >= 32000 and messageid < 33000:
        result = get_main_addon().getLocalizedString(messageid)
    else:
        result = xbmc.getLocalizedString(messageid)
    return result

def get_conditional(conditional):
    return xbmc.getCondVisibility(conditional)

def get_infolabel(infolabel):
    return xbmc.getInfoLabel(infolabel)

def execute_builtin(builtin_command):
    xbmc.executebuiltin(builtin_command)

def datetime_now():
    try:
        return datetime.now()
    except ImportError:
        xbmc.sleep(50)
        return datetime_now()

def datetime_strptime(date_string, format_string):
    try:
        return datetime.strptime(date_string, format_string)
    except TypeError:
        try:
            return datetime(*(time.strptime(date_string, format_string)[0:6]))
        except ImportError:
            xbmc.sleep(50)
            return datetime_strptime(date_string, format_string)

def execute_jsonrpc(jsonrpc_command):
    if isinstance(jsonrpc_command, dict):
        try:
            jsonrpc_command = json.dumps(jsonrpc_command)
        except UnicodeDecodeError:
            jsonrpc_command = json.dumps(jsonrpc_command, ensure_ascii=False)

    json_result = xbmc.executeJSONRPC(jsonrpc_command)
    return json.loads(json_result)

def log(message, level=xbmc.LOGDEBUG, tag=None):
    level_tag = ''

    if isinstance(message, (dict, list)) and len(message) > 300:
        message = str(message)
    elif not isinstance(message, str):
        message = json.dumps(message, cls=PrettyJSONEncoder)

    addontag = ADDONID if not tag else ADDONID + ':' + tag
    file_message = '%s[%s] %s' % (level_tag, addontag, message)
    xbmc.log(file_message, level)

def unquoteimage(imagestring):
    # extracted thumbnail images need to keep their 'image://' encoding
    if imagestring.startswith('image://') and not imagestring.startswith(('image://video', 'image://music')):
        return urllib.parse.unquote(imagestring[8:-1])
    return imagestring

def quoteimage(imagestring):
    if imagestring.startswith('image://'):
        return imagestring
    # Kodi goes lowercase and doesn't encode some chars
    result = 'image://{0}/'.format(urllib.parse.quote(imagestring, '()!'))
    result = re.sub(r'%[0-9A-F]{2}', lambda mo: mo.group().lower(), result)
    return result

def get_command(*first_arg_keys):
    command = {}
    start = len(first_arg_keys) if first_arg_keys else 1
    for x in range(start, len(sys.argv)):
        arg = sys.argv[x].split("=")
        command[arg[0].strip().lower()] = arg[1].strip() if len(arg) > 1 else True

    if first_arg_keys:
        for i, argkey in enumerate(first_arg_keys, 1):
            if len(sys.argv) <= i:
                break
            command[argkey] = sys.argv[i]
    return command

class ObjectJSONEncoder(json.JSONEncoder):
    # Will still flop on circular objects
    def __init__(self, *args, **kwargs):
        kwargs['skipkeys'] = True
        super(ObjectJSONEncoder, self).__init__(*args, **kwargs)

    def default(self, obj):
        # Called for objects that aren't directly JSON serializable
        if isinstance(obj, collections.Mapping):
            return dict((key, obj[key]) for key in obj.keys())
        if isinstance(obj, collections.Sequence):
            return list(obj)
        if callable(obj):
            return str(obj)
        try:
            result = dict(obj.__dict__)
            result['* objecttype'] = str(type(obj))
            return result
        except AttributeError:
            pass # obj has no __dict__ attribute
        result = {'* dir': dir(obj)}
        result['* objecttype'] = str(type(obj))
        return result

class PrettyJSONEncoder(ObjectJSONEncoder):
    def __init__(self, *args, **kwargs):
        kwargs['ensure_ascii'] = False
        kwargs['indent'] = 2
        kwargs['separators'] = (',', ': ')
        super(PrettyJSONEncoder, self).__init__(*args, **kwargs)

class DialogBusy(object):
    def __init__(self):
        self.visible = False
        window = 'busydialognocancel'
        self._activate = 'ActivateWindow({0})'.format(window)
        self._close = 'Dialog.Close({0})'.format(window)

    def create(self):
        xbmc.executebuiltin(self._activate)
        self.visible = True

    def close(self):
        xbmc.executebuiltin(self._close)
        self.visible = False

    def __del__(self):
        if self.visible:
            try:
                xbmc.executebuiltin(self._close)
            except AttributeError:
                pass
