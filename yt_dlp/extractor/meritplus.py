from .common import InfoExtractor
from ..utils import (
    determine_ext,
    float_or_none,
    int_or_none,
    join_nonempty,
    traverse_obj,
    url_or_none,
)


class MeritPlusIE(InfoExtractor):
    _VALID_URL = r'https?://(?:[\w-]+\.)?meritplus\.com/(?:c/)?(?P<type>[a-z]+)/(?P<ep>[^/]+\?episodeId=)?(?P<id>[^/&\?]+)'
    _TESTS = [{
        'url': 'https://www.meritplus.com/c/s/VQ2aB6Sp?episodeId=uNLp2Rgg&play=1',
        'info_dict': {
            'id': 'uNLp2Rgg',
            'ext': 'mp4',
            'title': 'Right to Stand Your Ground | Dr. Phil Primetime',
            'description': r're:^Employees who fought back against robbers, unruly customers, and',
            'thumbnail': 'https://cdn.jwplayer.com/v2/media/uNLp2Rgg/poster.jpg?width=1920',
            'duration': 2519.0,
            'tags': 'count:14',
            'timestamp': 1724716800,
            'upload_date': '20240827',
            'series': 'Dr. Phil Primetime',
        },
    }, {
        'url': 'https://www.meritplus.com/m/XeoP00kQ/marching-cobras-somebodys-gotta-do-it-with-mike-rowe?r=8SrBMsCA&play=1',
        'info_dict': {
            'id': 'XeoP00kQ',
            'ext': 'mp4',
            'title': 'Marching Cobras | Somebody\'s Gotta Do It with Mike Rowe',
            'description': r're:^Don Daughtry teaches his young students to reach for a brighter future',
            'thumbnail': 'https://cdn.jwplayer.com/v2/media/XeoP00kQ/poster.jpg?width=1920',
            'duration': 1471.0,
            'tags': 'count:14',
            'timestamp': 1714233600,
            'upload_date': '20240427',
            'series': 'Somebody\'s Gotta Do It With Mike Rowe',
            'episode': 'Episode 13',
            'episode_number': 13,
            'season': 'Season 1',
            'season_number': 1,
        },
    }, {
        'url': 'https://www.meritplus.com/c/sns/jryHEWXj',
        'info_dict': {
            'id': 'jryHEWXj',
            'title': 'Morning On Merit Street',
            'description': r're:^Award winning journalist Dominique Sachse and co-host Fanchon Stinger',
            'thumbnail': r're:^https://assets.mediabackstage.com/merit_prod.*\.png',
        },
        'playlist_mincount': 5,
    }, {
        'url': 'https://www.meritplus.com/c/s/eAzd5bqW',
        'info_dict': {
            'id': 'eAzd5bqW',
            'title': 'Crime Stories with Nancy Grace',
            'description': r're:^Nancy Grace explores the inside story of true crimes and cold cases',
            'thumbnail': r're:^https://assets.mediabackstage.com/merit_prod.*\.jpg',
        },
        'playlist_mincount': 10,
    }]

    def _real_extract(self, url):
        video_id, c_type, is_episode = self._match_valid_url(url).group('id', 'type', 'ep')
        if is_episode or c_type == 'm':
            json = self._download_json(f'https://cdn.jwplayer.com/v2/media/{video_id}', video_id)
        else:
            json = self._download_json(f'https://cdn.jwplayer.com/v2/playlists/{video_id}?format=json&page_limit=500', video_id)

        def extract_video(video):
            thumbnails, formats, subtitles = [], [], {}
            for image in video.get('images', []):
                thumbnails.append({
                    'url': url_or_none(image.get('src')),
                    'width': image.get('width'),
                })
            for caption in video.get('tracks', []):
                if caption.get('kind') == 'captions':
                    subtitles.setdefault(caption.get('label', 'und'), []).append({
                        'url': caption.get('file'),
                        'name': caption.get('label'),
                    })
            is_live = bool(video.get('is_live'))
            for source in video.get('sources', []):
                if media_url := url_or_none(source.get('file')):
                    if determine_ext(media_url) == 'm3u8':
                        hls_fmts, hls_subs = self._extract_m3u8_formats_and_subtitles(
                            media_url, video['mediaid'], fatal=None)
                        if is_live:
                            for f in hls_fmts:
                                f['downloader_options'] = {'ffmpeg_args_out': ['-http_persistent', '0']}
                        formats.extend(hls_fmts)
                        self._merge_subtitles(hls_subs, target=subtitles)
                    else:
                        formats.append(traverse_obj(source, {
                            'format_id': ('label', {lambda v: 'audio' if 'Audio' in v else v}),
                            'url': ('file', {str}),
                            'height': ('height', {int_or_none}),
                            'width': ('width', {int_or_none}),
                            'filesize': ('filesize', {int}),
                            'fps': ('framerate', {float_or_none}),
                            'tbr': ('bitrate', {lambda v: int_or_none(v, 1000)}),
                            'acodec': ('label', {lambda v: 'aac' if 'AAC' in v else None}),
                            'vcodec': ('type', {lambda v: 'none' if 'audio' in v else None}),
                        }))

            return {**traverse_obj(video, {
                'id': ('mediaid', {str}),
                'title': ('title', {str}),
                'description': ('description', {str}),
                'timestamp': ('pubdate', {int}),
                'tags': ('tags', {lambda v: v.split(',') if v else None}),
                'series': ('programName', {lambda v: v or None}),
                'season_number': ('seasonNumber', {int_or_none}),
                'episode_number': ('episodeNumber', {int_or_none}),
                'cast': ('cast', {lambda v: v.split(',') if v else None}),
                'duration': ('duration', {float_or_none}),
                'webpage_url': ('mediaid', {lambda v: url + (f'?episodeId={v}' if v not in url else '')}),
                'thumbnail': ('image', {lambda v: url_or_none(v) if not thumbnails else None}),
            }),
                'is_live': is_live,
                'thumbnails': thumbnails,
                'formats': formats,
                'subtitles': subtitles,
            }

        playlist = json.get('playlist', [])
        if len(playlist) == 1:
            return extract_video(playlist[0])
        elif len(playlist) > 1:
            description = join_nonempty('shortDescription', 'description', delim=' ', from_dict=json)
            thumbnail = traverse_obj(json, (('imgHomeRailThumb16x9', 'imgFeaturedTvBanner16x9'),
                                            {url_or_none}), get_all=False)
            return self.playlist_result((extract_video(video) for video in playlist),
                                        id=json['seriesId'], title=json['title'],
                                        description=description, thumbnail=thumbnail)
        else:
            self.raise_no_formats('No video formats found!')
