import json
import os
# from yt_dlp.third_api.youtube_rapidapi import YoutubeRapidApi


# ytb_api = YoutubeRapidApi()
# info = ytb_api.get_video_info('dQw4w9WgXcQ')
# print(json.dumps(info))


current_dir = os.path.dirname(os.path.realpath(__file__))
debug_dir = os.path.join(current_dir, 'debug')
os.makedirs(debug_dir, exist_ok=True)

# os.environ['hikerapi_key'] = ''
os.environ['rapidapi_key'] = ''
os.environ['webview_location'] = ''
# os.environ['webview_params'] = ''
os.environ['webview_downpage_params'] = ''
os.environ['mp4decrypt_location'] = os.path.join(debug_dir, 'mp4decrypt')


# import yt_dlp
# sys.argv = [
#   os.path.join(current_dir, "yt-dlp"),
#    "--ffmpeg-location", debug_dir,
#    "--mp4decrypt-location", os.path.join(debug_dir, "mp4decrypt"),
#    "--legacy-server-connect",
#    "--no-check-certificates",
#    "--no-colors",
#    "-J",
#    "--skip-download",
#    "--yes-playlist",
#    "--flat-playlist",
#    #"--allow-unplayable-formats",
#    #"--extractor-args",
#    'https://www.tvbanywherena.com/cantonese/videos/437-SuperTrioShow/6007674088001'
# ]
# yt_dlp.main()

from yt_dlp import YoutubeDL

ydl = YoutubeDL({
    # 'cookiefile': os.path.join(debug_dir, 'cookies.txt'),
    # 'ignoreerrors': True,
    # 'plain_entries': True,
    # 'skip_download_media_type': "",
    # "progress_template": {
    #     'download':r'{"status": "%(progress.status)s","n_entries": %(info.n_entries)s, "playlist_index": %(info.playlist_index)s}',
    # },
    # 'load_info_filename':"",
    # 'mp4decrypt_location': os.path.join(debug_dir, 'mp4decrypt'),
    'ffmpeg_location': debug_dir,
    # 'noplaylist':True,
    'outtmpl': f'{debug_dir}/downloads/%(id)s.%(ext)s',
    'extract_flat': 'in_playlist',
    'nopart': True,
    'http_headers': {
        # "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36",
        # "Accept": "*/*",
    },
    # "proxy": '',
    'no_check_certificate': True,
    # "ignoreerrors":True,
    'allow_unplayable_formats': True,
    'force_use_webview': False,
    'verbose': True,
    'restrictfilenames': True,
    'progress_with_newline': True,
    # "format": "audio-192p",
    'ignore_postproc_errors': True,
    'source_address': '',
    # 'proxy': '',
    'keepvideo': True,
    'extractor_args': {
        'onlyfans': {
            'external_ie': ['18209'],
        },
        'instagram': {
            'hikerapi_key': ['ZXMO9mnHA1MOSD56TSKzrWJPNrNnw23D'],
            # 'hikerapi_not_prefer_video': [True],
        },
        'generic': {
            'dumphtml': [True],
        },
        'youtube': {
            # "formats": ["missing_pot"],
            'player_client': [
                # "android_vr",
                # 'web_safari',
                # 'web',
                # 'web_creator',
                # 'web_embedded',
                # 'android',
                # 'android_creator',
                # 'ios',
                # 'ios_creator',
                # 'mweb',
                # 'tv',
            ],
            # 'player_skip': ['webpage'],
            'prefer_rapidapi': [True],
        },
    },
    # 'skip_download': True,
    # 'dumpjson':True,
},
)

# ydl.download_with_info_file(os.path.join(current_dir, 'debug', 'info.json'))


info = ydl.extract_info('h',
                        download=False,
                        force_generic_extractor=False)

s = json.dumps(ydl.sanitize_info(info))
print(s)
with open(os.path.join(current_dir, 'debug', 'info.json'), 'w') as f:
    f.write(s)
# ydl.download_with_info_file(os.path.join(current_dir, 'debug', 'info.json'))
