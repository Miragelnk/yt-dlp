import re

from .common import InfoExtractor
from ..utils import (
    js_to_json,
)


class MegaTubeIE(InfoExtractor):
    _VALID_URL = r'https?://(?:www\.)?megatube\.xxx/videos/(?P<id>\d+)/(?P<slug>[^/]+)'

    _TESTS = [{
        'url': 'https://www.megatube.xxx/videos/104245/brunette-abbie-cat-with-big-fake-tits-gets-the-fuck-she-wants/',
        'only_matching': True,
    }, {
        'url': 'https://www.megatube.xxx/videos/104245/brunette-abbie-cat-with-big-fake-tits-gets-the-fuck-she-wants/',
        'only_matching': True,
    }]

    def _real_extract(self, url):
        video_id = self._match_id(url)

        webpage = self._download_webpage(url, video_id)

        data_json = self._search_json(
            r'var\s?flashvars\s?=\s?', webpage, 'data', video_id,
            transform_source=js_to_json)

        video_url = data_json.get('video_url')
        thumbnail = data_json.get('preview_url')

        title = (self._og_search_title(
            webpage, default=None) or re.sub(r'(.*)\(.*\)', '\\1',
                                             self._html_extract_title(webpage)).strip()
        ).strip()

        return {
            'id': video_id,
            'url': video_url,
            'title': title,
            'thumbnail': thumbnail,
            'age_limit': 18,
            'ext': 'mp4',
        }
