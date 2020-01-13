import socket
import ipaddress
import urllib.request
import urllib.parse

from .conf import settings
from datetime import datetime
from functools import wraps

APP_NAME = 'Jellyfin MPV Shim'

class Timer(object):
    def __init__(self):
        self.restart()

    def restart(self):
        self.started = datetime.now()

    def elapsedMs(self):
        return  self.elapsed() * 1e3

    def elapsed(self):
        return (datetime.now()-self.started).total_seconds()

def synchronous(tlockname):
    """
    A decorator to place an instance based lock around a method.
    From: http://code.activestate.com/recipes/577105-synchronization-decorator-for-class-methods/
    """

    def _synched(func):
        @wraps(func)
        def _synchronizer(self,*args, **kwargs):
            tlock = self.__getattribute__( tlockname)
            tlock.acquire()
            try:
                return func(self, *args, **kwargs)
            finally:
                tlock.release()
        return _synchronizer
    return _synched

def is_local_domain(client):
    # With Jellyfin, it is significantly more likely the user will be using
    # an address that is a hairpin NAT. We want to detect this and avoid
    # imposing limits in this case.
    url = client.config.data.get("auth.server", "")
    domain = urllib.parse.urlparse(url).hostname

    ip = socket.gethostbyname(domain)
    is_local = ipaddress.ip_address(ip).is_private

    if not is_local:
        wan_ip = (urllib.request.urlopen("https://checkip.amazonaws.com/")
                  .read().decode('ascii').replace('\n','').replace('\r',''))
        return ip == wan_ip
    return True

def mpv_color_to_plex(color):
    return '#'+color.lower()[3:]

def plex_color_to_mpv(color):
    return '#FF'+color.upper()[1:]

def get_profile(is_remote=False, video_bitrate=None, force_transcode=False, is_tv=False):
    if video_bitrate is None:
        if is_remote:
            video_bitrate = settings.remote_kbps
        else:
            video_bitrate = settings.local_kbps

    profile = {
        "Name": APP_NAME,
        "MaxStreamingBitrate": video_bitrate * 1000,
        "MusicStreamingTranscodingBitrate": 1280000,
        "TimelineOffsetSeconds": 5,
        "TranscodingProfiles": [
            {
                "Type": "Audio"
            },
            {
                "Container": "ts",
                "Type": "Video",
                "Protocol": "hls",
                "AudioCodec": "aac,mp3,ac3,opus,flac,vorbis",
                "VideoCodec": "h264,mpeg4,mpeg2video",
                "MaxAudioChannels": "6"
            },
            {
                "Container": "jpeg",
                "Type": "Photo"
            }
        ],
        "DirectPlayProfiles": [
            {
                "Type": "Video"
            },
            {
                "Type": "Audio"
            },
            {
                "Type": "Photo"
            }
        ],
        "ResponseProfiles": [],
        "ContainerProfiles": [],
        "CodecProfiles": [],
        "SubtitleProfiles": [
            {
                "Format": "srt",
                "Method": "External"
            },
            {
                "Format": "srt",
                "Method": "Embed"
            },
            {
                "Format": "ass",
                "Method": "External"
            },
            {
                "Format": "ass",
                "Method": "Embed"
            },
            {
                "Format": "sub",
                "Method": "Embed"
            },
            {
                "Format": "sub",
                "Method": "External"
            },
            {
                "Format": "ssa",
                "Method": "Embed"
            },
            {
                "Format": "ssa",
                "Method": "External"
            },
            {
                "Format": "smi",
                "Method": "Embed"
            },
            {
                "Format": "smi",
                "Method": "External"
            },
            # Jellyfin currently refuses to serve these subtitle types as external.
            {
                "Format": "pgssub",
                "Method": "Embed"
            },
            #{
            #    "Format": "pgssub",
            #    "Method": "External"
            #},
            {
                "Format": "dvdsub",
                "Method": "Embed"
            },
            #{
            #    "Format": "dvdsub",
            #    "Method": "External"
            #},
            {
                "Format": "pgs",
                "Method": "Embed"
            },
            #{
            #    "Format": "pgs",
            #    "Method": "External"
            #}
        ]
    }

    if settings.transcode_h265:
        profile['DirectPlayProfiles'][0]['VideoCodec'] = "h264,mpeg4,mpeg2video"
    else:
        profile['TranscodingProfiles'].insert(0, {
            "Container": "ts",
            "Type": "Video",
            "Protocol": "hls",
            "AudioCodec": "aac,mp3,ac3,opus,flac,vorbis",
            "VideoCodec": "h264,h265,hevc,mpeg4,mpeg2video",
            "MaxAudioChannels": "6"
        })

    if settings.transcode_hi10p:
        profile['CodecProfiles'].append(
            {
                'Type': 'Video',
                'codec': 'h264',
                'Conditions': [
                    {
                        'Condition': "LessThanEqual",
                        'Property': "VideoBitDepth",
                        'Value': "8"
                    }
                ]
            }
        )

    if settings.always_transcode or force_transcode:
        profile['DirectPlayProfiles'] = []

    if is_tv:
        profile['TranscodingProfiles'].insert(0, {
            "Container": "ts",
            "Type": "Video",
            "AudioCodec": "mp3,aac",
            "VideoCodec": "h264",
            "Context": "Streaming",
            "Protocol": "hls",
            "MaxAudioChannels": "2",
            "MinSegments": "1",
            "BreakOnNonKeyFrames": True
        })

    return profile

def get_sub_display_title(stream):
    return "{0}{1} ({2})".format(
        stream.get("Language").capitalize(),
        " Forced" if stream.get("IsForced") else "",
        stream.get("Codec")
    )