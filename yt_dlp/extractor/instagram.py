import hashlib
import itertools
import json
import re
import time

from .common import InfoExtractor
from ..networking.exceptions import HTTPError
from ..utils import (
    ExtractorError,
    decode_base_n,
    encode_base_n,
    filter_dict,
    float_or_none,
    format_field,
    get_element_by_attribute,
    int_or_none,
    lowercase_escape,
    str_or_none,
    str_to_int,
    traverse_obj,
    url_or_none,
    urlencode_postdata,
)

_ENCODING_CHARS = 'ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_'


def _pk_to_id(id):
    """Source: https://stackoverflow.com/questions/24437823/getting-instagram-post-url-from-media-id"""
    return encode_base_n(int(id.split('_')[0]), table=_ENCODING_CHARS)


def _id_to_pk(shortcode):
    """Covert a shortcode to a numeric value"""
    return decode_base_n(shortcode[:11], table=_ENCODING_CHARS)


class InstagramBaseIE(InfoExtractor):
    _NETRC_MACHINE = 'instagram'
    _IS_LOGGED_IN = False

    _API_BASE_URL = 'https://i.instagram.com/api/v1'
    _LOGIN_URL = 'https://www.instagram.com/accounts/login'
    _API_HEADERS = {
        'X-IG-App-ID': '936619743392459',
        'X-ASBD-ID': '198387',
        'X-IG-WWW-Claim': '0',
        'Origin': 'https://www.instagram.com',
        'Accept': '*/*',
        'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/104.0.0.0 Safari/537.36',
    }

    def _has_session_id(self):
        return self._get_cookies("https://www.instagram.com/").get('sessionid')

    def _perform_login(self, username, password):
        if self._IS_LOGGED_IN:
            return

        login_webpage = self._download_webpage(
            self._LOGIN_URL, None, note='Downloading login webpage', errnote='Failed to download login webpage')

        shared_data = self._parse_json(self._search_regex(
            r'window\._sharedData\s*=\s*({.+?});', login_webpage, 'shared data', default='{}'), None)

        login = self._download_json(
            f'{self._LOGIN_URL}/ajax/', None, note='Logging in', headers={
                **self._API_HEADERS,
                'X-Requested-With': 'XMLHttpRequest',
                'X-CSRFToken': shared_data['config']['csrf_token'],
                'X-Instagram-AJAX': shared_data['rollout_hash'],
                'Referer': 'https://www.instagram.com/',
            }, data=urlencode_postdata({
                'enc_password': f'#PWD_INSTAGRAM_BROWSER:0:{int(time.time())}:{password}',
                'username': username,
                'queryParams': '{}',
                'optIntoOneTap': 'false',
                'stopDeletionNonce': '',
                'trustedDeviceRecords': '{}',
            }))

        if not login.get('authenticated'):
            if login.get('message'):
                raise ExtractorError(f'Unable to login: {login["message"]}')
            elif login.get('user'):
                raise ExtractorError('Unable to login: Sorry, your password was incorrect. Please double-check your password.', expected=True)
            elif login.get('user') is False:
                raise ExtractorError('Unable to login: The username you entered doesn\'t belong to an account. Please check your username and try again.', expected=True)
            raise ExtractorError('Unable to login')
        InstagramBaseIE._IS_LOGGED_IN = True

    def _get_count(self, media, kind, *keys):
        return traverse_obj(
            media, (kind, 'count'), *((f'edge_media_{key}', 'count') for key in keys),
            expected_type=int_or_none)

    def _get_dimension(self, name, media, webpage=None):
        return (
            traverse_obj(media, ('dimensions', name), expected_type=int_or_none)
            or int_or_none(self._html_search_meta(
                (f'og:video:{name}', f'video:{name}'), webpage or '', default=None)))

    def _extract_nodes(self, nodes, is_direct=False):
        for idx, node in enumerate(nodes, start=1):
            if node.get('__typename') != 'GraphVideo' and node.get('is_video') is not True:
                continue

            video_id = node.get('shortcode')

            if is_direct and node.get('video_url'):
                info = {
                    'id': video_id or node['id'],
                    'url': node.get('video_url'),
                    'width': self._get_dimension('width', node),
                    'height': self._get_dimension('height', node),
                    'http_headers': {
                        'Referer': 'https://www.instagram.com/',
                    }
                }
            elif not video_id:
                continue
            else:
                info = {
                    '_type': 'url',
                    'ie_key': 'Instagram',
                    'id': video_id,
                    'url': f'https://instagram.com/p/{video_id}',
                }
            desc = traverse_obj(node, ('edge_media_to_caption', 'edges', 0, 'node', 'text'), expected_type=str)
            yield {
                **info,
                'title': node.get('title') or desc or (f'Video {idx}' if is_direct else None),
                'description': desc,
                'thumbnail': traverse_obj(
                    node, 'display_url', 'thumbnail_src', 'display_src', expected_type=url_or_none),
                'duration': float_or_none(node.get('video_duration')),
                'timestamp': int_or_none(node.get('taken_at_timestamp')),
                'view_count': int_or_none(node.get('video_view_count')),
                'comment_count': self._get_count(node, 'comments', 'preview_comment', 'to_comment', 'to_parent_comment'),
                'like_count': self._get_count(node, 'likes', 'preview_like'),
            }

    def _extract_product_media(self, product_media):
        media_type = product_media.get("media_type", 0)
        if media_type == 8:
            return {
                **self._extract_product(product_media),
                '_media_type': 'CAROUSEL',
            }

        media_id = product_media.get('code') or _pk_to_id(product_media.get('pk'))
        vcodec = product_media.get('video_codec')
        dash_manifest_raw = product_media.get('video_dash_manifest')
        videos_list = product_media.get('video_versions')
        images_list = traverse_obj(product_media, ('image_versions2', 'candidates'))
        if not (dash_manifest_raw or videos_list or images_list):
            return {}

        formats = [{
            'format_id': format.get('id'),
            'url': format.get('url'),
            'width': format.get('width'),
            'height': format.get('height'),
            'vcodec': vcodec,
        } for format in videos_list or []]
        if dash_manifest_raw:
            formats.extend(self._parse_mpd_formats(self._parse_xml(dash_manifest_raw, media_id), mpd_id='dash'))

        if media_type == 1:
            media_type = 'PHOTO'
            formats.extend([{
                'format_id': 'photo-' + str(item.get('width', '')) + "-" + str(item.get('height', '')),
                'url': item.get('url'),
                'width': item.get('width'),
                'height': item.get('height'),
                '_media_type': media_type,
            } for item in images_list or []])
        elif media_type == 2:
            media_type = 'VIDEO'
        else:
            self.report_warning(f'Unknown media type {media_type}')
            return {}
        thumbnails = [{
            'url': thumbnail.get('url'),
            'width': thumbnail.get('width'),
            'height': thumbnail.get('height')
        } for thumbnail in images_list or []]

        return {
            'id': media_id,
            'duration': float_or_none(product_media.get('video_duration')),
            'formats': formats,
            'thumbnails': thumbnails,
            '_media_type': media_type
        }

    def _extract_product(self, product_info):
        if isinstance(product_info, list):
            product_info = product_info[0]

        user_info = product_info.get('user') or {}
        info_dict = {
            'id': _pk_to_id(traverse_obj(product_info, 'pk', 'id', expected_type=str_or_none)[:19]),
            'title': product_info.get('title') or f'Post by {user_info.get("username")}',
            'description': traverse_obj(product_info, ('caption', 'text'), expected_type=str_or_none),
            'timestamp': int_or_none(product_info.get('taken_at')),
            'channel': user_info.get('username'),
            'uploader': user_info.get('full_name'),
            'uploader_id': str_or_none(user_info.get('pk')),
            'view_count': int_or_none(product_info.get('view_count')),
            'like_count': int_or_none(product_info.get('like_count')),
            'comment_count': int_or_none(product_info.get('comment_count')),
            '__post_extractor': self.extract_comments(_pk_to_id(product_info.get('pk'))),
            'http_headers': {
                'Referer': 'https://www.instagram.com/',
            }
        }
        carousel_media = product_info.get('carousel_media')
        if carousel_media:
            return {
                '_type': 'playlist',
                '_playlist_media_type': 'CAROUSEL',
                **info_dict,
                'title': f'Post by {user_info.get("username")}',
                'entries': [{
                    **info_dict,
                    **self._extract_product_media(product_media),
                } for product_media in carousel_media],
            }

        return {
            **info_dict,
            **self._extract_product_media(product_info)
        }

    def _get_comments(self, video_id):
        comments_info = self._download_json(
            f'{self._API_BASE_URL}/media/{_id_to_pk(video_id)}/comments/?can_support_threading=true&permalink_enabled=false', video_id,
            fatal=False, errnote='Comments extraction failed', note='Downloading comments info', headers=self._API_HEADERS) or {}

        comment_data = traverse_obj(comments_info, ('edge_media_to_parent_comment', 'edges'), 'comments')
        for comment_dict in comment_data or []:
            yield {
                'author': traverse_obj(comment_dict, ('node', 'owner', 'username'), ('user', 'username')),
                'author_id': traverse_obj(comment_dict, ('node', 'owner', 'id'), ('user', 'pk')),
                'author_thumbnail': traverse_obj(comment_dict, ('node', 'owner', 'profile_pic_url'), ('user', 'profile_pic_url'), expected_type=url_or_none),
                'id': traverse_obj(comment_dict, ('node', 'id'), 'pk'),
                'text': traverse_obj(comment_dict, ('node', 'text'), 'text'),
                'like_count': traverse_obj(comment_dict, ('node', 'edge_liked_by', 'count'), 'comment_like_count', expected_type=int_or_none),
                'timestamp': traverse_obj(comment_dict, ('node', 'created_at'), 'created_at', expected_type=int_or_none),
            }


class InstagramIOSIE(InfoExtractor):
    IE_DESC = 'IOS instagram:// URL'
    _VALID_URL = r'instagram://media\?id=(?P<id>[\d_]+)'
    _TESTS = [{
        'url': 'instagram://media?id=482584233761418119',
        'md5': '0d2da106a9d2631273e192b372806516',
        'info_dict': {
            'id': 'aye83DjauH',
            'ext': 'mp4',
            'title': 'Video by naomipq',
            'description': 'md5:1f17f0ab29bd6fe2bfad705f58de3cb8',
            'thumbnail': r're:^https?://.*\.jpg',
            'duration': 0,
            'timestamp': 1371748545,
            'upload_date': '20130620',
            'uploader_id': 'naomipq',
            'uploader': 'B E A U T Y  F O R  A S H E S',
            'like_count': int,
            'comment_count': int,
            'comments': list,
        },
        'add_ie': ['Instagram']
    }]

    def _real_extract(self, url):
        video_id = _pk_to_id(self._match_id(url))
        return self.url_result(f'http://instagram.com/tv/{video_id}', InstagramIE, video_id)


class InstagramIE(InstagramBaseIE):
    _VALID_URL = r'(?P<url>https?://(?:www\.)?instagram\.com(?:/[^/]+)?/(?:p|tv|reel)/(?P<id>[^/?#&]+))'
    _EMBED_REGEX = [r'<iframe[^>]+src=(["\'])(?P<url>(?:https?:)?//(?:www\.)?instagram\.com/p/[^/]+/embed.*?)\1']
    _TESTS = [{
        'url': 'https://instagram.com/p/aye83DjauH/?foo=bar#abc',
        'md5': '0d2da106a9d2631273e192b372806516',
        'info_dict': {
            'id': 'aye83DjauH',
            'ext': 'mp4',
            'title': 'Video by naomipq',
            'description': 'md5:1f17f0ab29bd6fe2bfad705f58de3cb8',
            'thumbnail': r're:^https?://.*\.jpg',
            'duration': 8.747,
            'timestamp': 1371748545,
            'upload_date': '20130620',
            'uploader_id': '2815873',
            'uploader': 'B E A U T Y  F O R  A S H E S',
            'channel': 'naomipq',
            'like_count': int,
            'comment_count': int,
            'comments': list,
        },
        'expected_warnings': [
            'General metadata extraction failed',
            'Main webpage is locked behind the login page',
        ],
    }, {
        # reel
        'url': 'https://www.instagram.com/reel/Chunk8-jurw/',
        'md5': 'f6d8277f74515fa3ff9f5791426e42b1',
        'info_dict': {
            'id': 'Chunk8-jurw',
            'ext': 'mp4',
            'title': 'Video by instagram',
            'description': 'md5:c9cde483606ed6f80fbe9283a6a2b290',
            'thumbnail': r're:^https?://.*\.jpg',
            'duration': 5.016,
            'timestamp': 1661529231,
            'upload_date': '20220826',
            'uploader_id': '25025320',
            'uploader': 'Instagram',
            'channel': 'instagram',
            'like_count': int,
            'comment_count': int,
            'comments': list,
        },
        'expected_warnings': [
            'General metadata extraction failed',
            'Main webpage is locked behind the login page',
        ],
    }, {
        # multi video post
        'url': 'https://www.instagram.com/p/BQ0eAlwhDrw/',
        'playlist': [{
            'info_dict': {
                'id': 'BQ0dSaohpPW',
                'ext': 'mp4',
                'title': 'Video 1',
                'thumbnail': r're:^https?://.*\.jpg',
                'view_count': int,
            },
        }, {
            'info_dict': {
                'id': 'BQ0dTpOhuHT',
                'ext': 'mp4',
                'title': 'Video 2',
                'thumbnail': r're:^https?://.*\.jpg',
                'view_count': int,
            },
        }, {
            'info_dict': {
                'id': 'BQ0dT7RBFeF',
                'ext': 'mp4',
                'title': 'Video 3',
                'thumbnail': r're:^https?://.*\.jpg',
                'view_count': int,
            },
        }],
        'info_dict': {
            'id': 'BQ0eAlwhDrw',
            'title': 'Post by instagram',
            'description': 'md5:0f9203fc6a2ce4d228da5754bcf54957',
        },
        'expected_warnings': [
            'General metadata extraction failed',
            'Main webpage is locked behind the login page',
        ],
    }, {
        # IGTV
        'url': 'https://www.instagram.com/tv/BkfuX9UB-eK/',
        'info_dict': {
            'id': 'BkfuX9UB-eK',
            'ext': 'mp4',
            'title': 'Fingerboarding Tricks with @cass.fb',
            'thumbnail': r're:^https?://.*\.jpg',
            'duration': 53.83,
            'timestamp': 1530032919,
            'upload_date': '20180626',
            'uploader_id': '25025320',
            'uploader': 'Instagram',
            'channel': 'instagram',
            'like_count': int,
            'comment_count': int,
            'comments': list,
            'description': 'Meet Cass Hirst (@cass.fb), a fingerboarding pro who can perform tiny ollies and kickflips while blindfolded.',
        },
        'expected_warnings': [
            'General metadata extraction failed',
            'Main webpage is locked behind the login page',
        ],
    }, {
        'url': 'https://instagram.com/p/-Cmh1cukG2/',
        'only_matching': True,
    }, {
        'url': 'http://instagram.com/p/9o6LshA7zy/embed/',
        'only_matching': True,
    }, {
        'url': 'https://www.instagram.com/tv/aye83DjauH/',
        'only_matching': True,
    }, {
        'url': 'https://www.instagram.com/reel/CDUMkliABpa/',
        'only_matching': True,
    }, {
        'url': 'https://www.instagram.com/marvelskies.fc/reel/CWqAgUZgCku/',
        'only_matching': True,
    }]

    @classmethod
    def _extract_embed_urls(cls, url, webpage):
        res = tuple(super()._extract_embed_urls(url, webpage))
        if res:
            return res

        mobj = re.search(r'<a[^>]+href=([\'"])(?P<link>[^\'"]+)\1',
                         get_element_by_attribute('class', 'instagram-media', webpage) or '')
        if mobj:
            return [mobj.group('link')]

    def _real_extract(self, url):
        video_id, url = self._match_valid_url(url).group('id', 'url')
        media, webpage = {}, ''
        if self._get_cookies(url).get('sessionid'):
            info = traverse_obj(self._download_json(
                f'{self._API_BASE_URL}/media/{_id_to_pk(video_id)}/info/', video_id,
                fatal=False, errnote='Video info extraction failed',
                note='Downloading video info', headers=self._API_HEADERS), ('items', 0))
            if info:
                media.update(info)
                return self._extract_product(media)

        api_check = self._download_json(
            f'{self._API_BASE_URL}/web/get_ruling_for_content/?content_type=MEDIA&target_id={_id_to_pk(video_id)}',
            video_id, headers=self._API_HEADERS, fatal=False, note='Setting up session', errnote=False) or {}
        csrf_token = self._get_cookies('https://www.instagram.com').get('csrftoken')

        if not csrf_token:
            self.report_warning('No csrf token set by Instagram API', video_id)
        else:
            csrf_token = csrf_token.value if api_check.get('status') == 'ok' else None
            if not csrf_token:
                self.report_warning('Instagram API is not granting access', video_id)

        variables = {
            'shortcode': video_id,
            'child_comment_count': 3,
            'fetch_comment_count': 40,
            'parent_comment_count': 24,
            'has_threaded_comments': True,
        }
        general_info = self._download_json(
            'https://www.instagram.com/graphql/query/', video_id, fatal=False, errnote=False,
            headers={
                **self._API_HEADERS,
                'X-CSRFToken': csrf_token or '',
                'X-Requested-With': 'XMLHttpRequest',
                'Referer': url,
            }, query={
                'query_hash': '9f8827793ef34641b2fb195d4d41151c',
                'variables': json.dumps(variables, separators=(',', ':')),
            })
        media.update(traverse_obj(general_info, ('data', 'shortcode_media')) or {})

        if not general_info:
            self.report_warning('General metadata extraction failed (some metadata might be missing).', video_id)
            webpage, urlh = self._download_webpage_handle(url, video_id)
            shared_data = self._search_json(
                r'window\._sharedData\s*=', webpage, 'shared data', video_id, fatal=False) or {}

            if shared_data and self._LOGIN_URL not in urlh.url:
                media.update(traverse_obj(
                    shared_data, ('entry_data', 'PostPage', 0, 'graphql', 'shortcode_media'),
                    ('entry_data', 'PostPage', 0, 'media'), expected_type=dict) or {})
            else:
                self.report_warning('Main webpage is locked behind the login page. Retrying with embed webpage (some metadata might be missing).')
                webpage = self._download_webpage(
                    f'{url}/embed/', video_id, note='Downloading embed webpage', fatal=False)
                additional_data = self._search_json(
                    r'window\.__additionalDataLoaded\s*\(\s*[^,]+,', webpage, 'additional data', video_id, fatal=False)
                if not additional_data and not media:
                    self.raise_login_required('Requested content is not available, rate-limit reached or login required')

                product_item = traverse_obj(additional_data, ('items', 0), expected_type=dict)
                if product_item:
                    media.update(product_item)
                    return self._extract_product(media)

                media.update(traverse_obj(
                    additional_data, ('graphql', 'shortcode_media'), 'shortcode_media', expected_type=dict) or {})

        username = traverse_obj(media, ('owner', 'username')) or self._search_regex(
            r'"owner"\s*:\s*{\s*"username"\s*:\s*"(.+?)"', webpage, 'username', fatal=False)

        description = (
            traverse_obj(media, ('edge_media_to_caption', 'edges', 0, 'node', 'text'), expected_type=str)
            or media.get('caption'))
        if not description:
            description = self._search_regex(
                r'"caption"\s*:\s*"(.+?)"', webpage, 'description', default=None)
            if description is not None:
                description = lowercase_escape(description)

        video_url = media.get('video_url')
        if not video_url:
            nodes = traverse_obj(media, ('edge_sidecar_to_children', 'edges', ..., 'node'), expected_type=dict) or []
            if nodes:
                entries = []
                for entry in self._extract_nodes(nodes, True):
                    entries.append(entry)
                if not entries and not self._has_session_id():
                    self.raise_login_required()
                return self.playlist_result(entries, video_id,
                                            format_field(username, None, 'Post by %s'), description)
            try:
                video_url = self._og_search_video_url(webpage, secure=False)
            except ExtractorError as e:
                if not self._has_session_id():
                    self.raise_login_required()
                else:
                    raise e

        formats = [{
            'url': video_url,
            'width': self._get_dimension('width', media, webpage),
            'height': self._get_dimension('height', media, webpage),
        }]
        dash = traverse_obj(media, ('dash_info', 'video_dash_manifest'))
        if dash:
            formats.extend(self._parse_mpd_formats(self._parse_xml(dash, video_id), mpd_id='dash'))

        comment_data = traverse_obj(media, ('edge_media_to_parent_comment', 'edges'))
        comments = [{
            'author': traverse_obj(comment_dict, ('node', 'owner', 'username')),
            'author_id': traverse_obj(comment_dict, ('node', 'owner', 'id')),
            'id': traverse_obj(comment_dict, ('node', 'id')),
            'text': traverse_obj(comment_dict, ('node', 'text')),
            'timestamp': traverse_obj(comment_dict, ('node', 'created_at'), expected_type=int_or_none),
        } for comment_dict in comment_data] if comment_data else None

        display_resources = (
            media.get('display_resources')
            or [{'src': media.get(key)} for key in ('display_src', 'display_url')]
            or [{'src': self._og_search_thumbnail(webpage)}])
        thumbnails = [{
            'url': thumbnail['src'],
            'width': thumbnail.get('config_width'),
            'height': thumbnail.get('config_height'),
        } for thumbnail in display_resources if thumbnail.get('src')]

        return {
            'id': video_id,
            'formats': formats,
            'title': media.get('title') or 'Video by %s' % username,
            'description': description,
            'duration': float_or_none(media.get('video_duration')),
            'timestamp': traverse_obj(media, 'taken_at_timestamp', 'date', expected_type=int_or_none),
            'uploader_id': traverse_obj(media, ('owner', 'id')),
            'uploader': traverse_obj(media, ('owner', 'full_name')),
            'channel': username,
            'like_count': self._get_count(media, 'likes', 'preview_like') or str_to_int(self._search_regex(
                r'data-log-event="likeCountClick"[^>]*>[^\d]*([\d,\.]+)', webpage, 'like count', fatal=False)),
            'comment_count': self._get_count(media, 'comments', 'preview_comment', 'to_comment', 'to_parent_comment'),
            'comments': comments,
            'thumbnails': thumbnails,
            'http_headers': {
                'Referer': 'https://www.instagram.com/',
            }
        }


class InstagramPlaylistBaseIE(InstagramBaseIE):
    _gis_tmpl = None  # used to cache GIS request type

    def _parse_graphql(self, webpage, item_id):
        # Reads a webpage and returns its GraphQL data.
        try:
            return self._parse_json(
                self._search_regex(
                    r'sharedData\s*=\s*({.+?})\s*;\s*[<\n]', webpage, 'data'),
                item_id)
        except ExtractorError as e:
            if not self._has_session_id():
                self.raise_login_required()
            else:
                raise e

    def _extract_graphql(self, data, url):
        # Parses GraphQL queries containing videos and generates a playlist.
        uploader_id = self._match_id(url)
        csrf_token = data['config']['csrf_token']
        rhx_gis = data.get('rhx_gis') or '3c7ca9dcefcf966d11dacf1f151335e8'

        cursor = ''
        for page_num in itertools.count(1):
            variables = {
                'first': 12,
                'after': cursor,
            }
            variables.update(self._query_vars_for(data))
            variables = json.dumps(variables)

            if self._gis_tmpl:
                gis_tmpls = [self._gis_tmpl]
            else:
                gis_tmpls = [
                    '%s' % rhx_gis,
                    '',
                    '%s:%s' % (rhx_gis, csrf_token),
                    '%s:%s:%s' % (rhx_gis, csrf_token, self.get_param('http_headers')['User-Agent']),
                ]

            # try all of the ways to generate a GIS query, and not only use the
            # first one that works, but cache it for future requests
            for gis_tmpl in gis_tmpls:
                try:
                    json_data = self._download_json(
                        'https://www.instagram.com/graphql/query/', uploader_id,
                        'Downloading JSON page %d' % page_num, headers={
                            'X-Requested-With': 'XMLHttpRequest',
                            'X-Instagram-GIS': hashlib.md5(
                                ('%s:%s' % (gis_tmpl, variables)).encode('utf-8')).hexdigest(),
                        }, query={
                            'query_hash': self._QUERY_HASH,
                            'variables': variables,
                        })
                    media = self._parse_timeline_from(json_data)
                    self._gis_tmpl = gis_tmpl
                    break
                except ExtractorError as e:
                    # if it's an error caused by a bad query, and there are
                    # more GIS templates to try, ignore it and keep trying
                    if isinstance(e.cause, HTTPError) and e.cause.status == 403:
                        if gis_tmpl != gis_tmpls[-1]:
                            continue
                    raise

            nodes = traverse_obj(media, ('edges', ..., 'node'), expected_type=dict) or []
            if not nodes:
                break
            yield from self._extract_nodes(nodes)

            has_next_page = traverse_obj(media, ('page_info', 'has_next_page'))
            cursor = traverse_obj(media, ('page_info', 'end_cursor'), expected_type=str)
            if not has_next_page or not cursor:
                break

    def _real_extract(self, url):
        user_or_tag = self._match_id(url)
        webpage = self._download_webpage(url, user_or_tag)
        data = self._parse_graphql(webpage, user_or_tag)

        self._set_cookie('instagram.com', 'ig_pr', '1')

        return self.playlist_result(
            self._extract_graphql(data, url), user_or_tag, user_or_tag)


class InstagramUserIE(InstagramPlaylistBaseIE):
    _WORKING = True
    _VALID_URL = r'https?://(?:www\.)?instagram\.com/(?P<id>[^/]{2,})/?(?:$|[?#])'
    IE_DESC = 'Instagram user profile'
    IE_NAME = 'instagram:user'
    _TESTS = [{
        'url': 'https://instagram.com/porsche',
        'info_dict': {
            'id': 'porsche',
            'title': 'porsche',
        },
        'playlist_count': 5,
        'params': {
            'extract_flat': True,
            'skip_download': True,
            'playlistend': 5,
        }
    }]

    _QUERY_HASH = '42323d64886122307be10013ad2dcc44',

    @staticmethod
    def _parse_timeline_from(data):
        # extracts the media timeline data from a GraphQL result
        return data['data']['user']['edge_owner_to_timeline_media']

    @staticmethod
    def _query_vars_for(data):
        # returns a dictionary of variables to add to the timeline query based
        # on the GraphQL of the original page
        return {
            'id': data['entry_data']['ProfilePage'][0]['graphql']['user']['id']
        }

    def _real_extract(self, url):
        username = self._match_id(url)
        action = self._configuration_arg(
            'custom_action', default=[''], ie_key=InstagramUserIE)[0]
        userdata = self._download_json(
            f'{self._API_BASE_URL}/users/web_profile_info/?username={username}&count=100',
            username, errnote=False, fatal=False, headers=self._API_HEADERS)
        if not userdata:
            self.report_warning('userdata extraction failed', username)
            if not self._has_session_id():
                self.raise_login_required()
        userdata = userdata['data']
        if action == 'get_post_count':
            return {
                '_type': 'custom_action',
                'id': username,
                'title': userdata.get('user', {}).get('full_name', username),
                'action_info': {
                    'action': action,
                    'count': traverse_obj(userdata, ('user', 'edge_owner_to_timeline_media', 'count'), expected_type=int),
                }
            }

        videos = []
        cursor = ''
        while True:
            feed_json = self._download_json(
                f'{self._API_BASE_URL}/feed/user/{username}/username/?count=100&max_id={cursor}',
                username, errnote=False, fatal=False, headers=self._API_HEADERS)
            if not feed_json:
                break
            videos += traverse_obj(feed_json, 'items', expected_type=list) or []
            has_next_page = traverse_obj(feed_json, 'more_available')
            cursor = traverse_obj(feed_json, 'next_max_id', expected_type=str)
            if not has_next_page or not cursor:
                break

        info_data = []
        for video in videos:
            highlight_data = self._extract_product(video)
            if highlight_data.get('formats'):
                info_data.append({
                    **highlight_data,
                    'uploader': userdata.get('user', {}).get('full_name', username),
                    'uploader_id': userdata.get('user', {}).get('id', username),
                })
        if not info_data and not self._has_session_id():
            self.raise_login_required()

        return self.playlist_result(info_data, playlist_id=username, playlist_title=format_field(username, None, 'Posts by %s'))


class InstagramTagIE(InstagramPlaylistBaseIE):
    _VALID_URL = r'https?://(?:www\.)?instagram\.com/explore/tags/(?P<id>[^/]+)'
    IE_DESC = 'Instagram hashtag search URLs'
    IE_NAME = 'instagram:tag'
    _TESTS = [{
        'url': 'https://instagram.com/explore/tags/lolcats',
        'info_dict': {
            'id': 'lolcats',
            'title': 'lolcats',
        },
        'playlist_count': 50,
        'params': {
            'extract_flat': True,
            'skip_download': True,
            'playlistend': 50,
        }
    }]

    _QUERY_HASH = 'f92f56d47dc7a55b606908374b43a314',

    @staticmethod
    def _parse_timeline_from(data):
        # extracts the media timeline data from a GraphQL result
        return data['data']['hashtag']['edge_hashtag_to_media']

    @staticmethod
    def _query_vars_for(data):
        # returns a dictionary of variables to add to the timeline query based
        # on the GraphQL of the original page
        return {
            'tag_name':
                data['entry_data']['TagPage'][0]['graphql']['hashtag']['name']
        }


class InstagramStoryIE(InstagramBaseIE):
    _VALID_URL = r'https?://(?:www\.)?instagram\.com/stories/(?P<user>[^/]+)/(?P<id>\d+)'
    IE_NAME = 'instagram:story'

    _TESTS = [{
        'url': 'https://www.instagram.com/stories/highlights/18090946048123978/',
        'info_dict': {
            'id': '18090946048123978',
            'title': 'Rare',
        },
        'playlist_mincount': 50
    }]

    def _real_extract(self, url):
        username, story_id = self._match_valid_url(url).groups()
        story_info = self._download_webpage(url, story_id)
        user_info = self._search_json(r'"user":', story_info, 'user info', story_id, fatal=False)
        if not user_info:
            self.raise_login_required('This content is unreachable')

        user_id = traverse_obj(user_info, 'pk', 'id', expected_type=str)
        story_info_url = user_id if username != 'highlights' else f'highlight:{story_id}'
        if not story_info_url:  # user id is only mandatory for non-highlights
            raise ExtractorError('Unable to extract user id')

        videos = traverse_obj(self._download_json(
            f'{self._API_BASE_URL}/feed/reels_media/?reel_ids={story_info_url}',
            story_id, errnote=False, fatal=False, headers=self._API_HEADERS), 'reels')
        if not videos:
            self.raise_login_required('You need to log in to access this content')

        full_name = traverse_obj(videos, (f'highlight:{story_id}', 'user', 'full_name'), (user_id, 'user', 'full_name'))
        story_title = traverse_obj(videos, (f'highlight:{story_id}', 'title'))
        if not story_title:
            story_title = f'Story by {username}'

        highlights = traverse_obj(videos, (f'highlight:{story_id}', 'items'), (user_id, 'items'))
        info_data = []
        for highlight in highlights:
            highlight_data = self._extract_product(highlight)
            if highlight_data.get('formats'):
                info_data.append({
                    'uploader': full_name,
                    'uploader_id': user_id,
                    **filter_dict(highlight_data),
                })
        return self.playlist_result(info_data, playlist_id=story_id, playlist_title=story_title)
