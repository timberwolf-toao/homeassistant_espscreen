"""A media player's library on a screen (app 0.4.42, firmware 0.24.0): its folders, a page of covers and a tap that plays.

- The library is what Home Assistant's `media_player.browse_media` action answers, at most 48 items a folder (what
  the Spotify integration gives); a screen gets a folder page by page under the 4096-byte limit, each item with a
  number of its own, a title, what it can do and the icon of its class, and never a content id.
- A tap plays through the app: a speaker first where one is chosen or the player plays nowhere (`select_source`
  wakes a Spotify account at rest), then `play_media` once the player reports PLAY_MEDIA.
- A player's state carries its speaker, the speakers it may play on, shuffle, repeat, its cover's two colours and
  whether its library opens, to a screen whose hello names `media_library`.
- A player at rest keeps the features it reported while it played (GitHub #88): the editor offers its keys and the
  screen draws them faded.
The shapes below are what the Spotify integration of Home Assistant 2026.9 answers.
"""
from manager_fixtures import with_screen_grid, seed_layout
import asyncio
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / 'screen_manager/app'))
import media_library  # noqa: E402
from core import encode, validate_layout  # noqa: E402

HAS_PIL = importlib.util.find_spec('PIL') is not None
HAS_AIOHTTP = importlib.util.find_spec('aiohttp') is not None
if HAS_AIOHTTP:
    import camera_feed
    from server import Manager

PLAYER = 'media_player.spotify'
PLAYING = 444983   # SUPPORT_SPOTIFY: what the integration reports while it plays
AT_REST = 2048     # SELECT_SOURCE alone: what it reports while it plays nowhere

TOP = {'title': 'Media Library', 'media_class': 'directory', 'media_content_type': 'spotify://library', 'media_content_id': 'library',
       'can_play': False, 'can_expand': True, 'children': [
           {'title': name, 'media_class': 'directory', 'children_media_class': kind, 'media_content_type': f'spotify://{key}',
            'media_content_id': key, 'can_play': False, 'can_expand': True, 'thumbnail': None}
           for name, kind, key in (('Playlists', 'playlist', 'current_user_playlists'), ('Artists', 'artist', 'current_user_followed_artists'),
                                   ('Albums', 'album', 'current_user_saved_albums'), ('Liked songs', 'track', 'current_user_saved_tracks'),
                                   ('Podcasts', 'podcast', 'current_user_saved_shows'), ('Recently played', 'track', 'current_user_recently_played'),
                                   ('Top Artists', 'artist', 'current_user_top_artists'), ('Top Tracks', 'track', 'current_user_top_tracks'))]}


def albums(count=48, title='An album with a long title that goes on'):
    return {'title': 'Albums', 'media_class': 'directory', 'children': [
        {'title': f'{title} {n}', 'media_class': 'album', 'media_content_type': 'spotify://album',
         'media_content_id': f'spotify:album:{n:022d}', 'can_play': True, 'can_expand': True,
         'thumbnail': f'https://i.scdn.co/image/ab67616d00001e02{n:024x}'} for n in range(count)]}


def png(colour, size=(64, 64)):
    from PIL import Image
    out = io.BytesIO()
    Image.new('RGB', size, colour).save(out, 'PNG')
    return out.getvalue()


class TheLibrary(unittest.TestCase):
    def test_folders_take_the_class_of_what_they_hold(self):
        folder = media_library.folder_of(TOP)
        self.assertEqual(folder['title'], 'Media Library')
        self.assertEqual([i['title'] for i in folder['items']][:3], ['Playlists', 'Artists', 'Albums'])
        self.assertEqual([i['icon'] for i in folder['items']][:4], ['F0CB8', 'F0803', 'F0025', 'F0387'])
        self.assertTrue(all(i['expand'] and not i['play'] and not i['thumb'] for i in folder['items']))

    def test_a_folder_holds_at_most_48_and_only_what_a_screen_can_use(self):
        answer = albums(60)
        answer['children'][0]['can_play'] = answer['children'][0]['can_expand'] = False  # neither plays nor opens
        answer['children'][1]['title'] = ''
        answer['children'][2].pop('media_content_id')
        folder = media_library.folder_of(answer)
        self.assertEqual(len(folder['items']), media_library.LIMIT)
        self.assertEqual(folder['items'][0]['title'], 'An album with a long title that goes on 3')
        with self.assertRaises(ValueError):
            media_library.folder_of(None)

    def test_items_keep_their_number(self):
        shelf = media_library.Shelf()
        first = media_library.entries(media_library.folder_of(albums(5)), shelf, PLAYER)
        again = media_library.entries(media_library.folder_of(albums(5)), shelf, PLAYER)
        self.assertEqual([e[0] for e in first], [e[0] for e in again])
        self.assertEqual(first[0][2], media_library.CAN_PLAY | media_library.CAN_EXPAND | media_library.PICTURED)
        item = shelf.get(PLAYER, first[0][0])
        self.assertEqual(item['id'], 'spotify:album:' + '0' * 22)
        self.assertIsNone(shelf.get('media_player.other', first[0][0]), 'a number belongs to its player')
        small = media_library.Shelf(limit=3)
        tokens = [e[0] for e in media_library.entries(media_library.folder_of(albums(5)), small, PLAYER)]
        self.assertIsNone(small.get(PLAYER, tokens[0]))
        self.assertIsNotNone(small.get(PLAYER, tokens[-1]))

    def test_what_plays_now_is_marked(self):
        folder = media_library.folder_of(albums(3))
        attrs = {'media_album_name': 'An album with a long title that goes on 1'}
        flags = [e[2] & media_library.PLAYING for e in media_library.entries(folder, media_library.Shelf(), PLAYER, attrs)]
        self.assertEqual(flags, [0, media_library.PLAYING, 0])
        started = ('spotify://album', 'spotify:album:' + '2'.zfill(22))
        flags = [e[2] & media_library.PLAYING for e in media_library.entries(folder, media_library.Shelf(), PLAYER, {}, started)]
        self.assertEqual(flags, [0, 0, media_library.PLAYING])

    def test_pages_stay_under_the_message_limit(self):
        # The longest titles a folder can bring, in letters of two bytes.
        folder = media_library.folder_of(albums(48, 'Ünïcödé ' * 10))
        items = media_library.entries(folder, media_library.Shelf(), PLAYER)
        pages = media_library.pages(items)
        self.assertGreater(len(pages), 1)
        self.assertEqual(sum(len(p) for p in pages), 48)
        for n in range(len(pages)):
            message = media_library.message(PLAYER, 12, folder['title'], n, pages, len(items))
            self.assertLessEqual(len(encode({**message, 'v': 2, 'session': 'a' * 16, 'seq': 99999, 'rev': 'b' * 16, 'view': 99999})), 4096)
        self.assertTrue(all(len(item[1].encode()) <= 48 for page in pages for item in page))
        empty = media_library.message(PLAYER, 0, '', 0, media_library.pages([]), 0, failed=True)
        self.assertEqual((empty['k'], empty['x'], empty['n']), ([], 1, 1))

    def test_the_answer_is_what_the_firmware_parses(self):
        source = (ROOT / 'components/smart_display/page_receiver.cpp').read_text()
        message = media_library.message(PLAYER, 3, 'Albums', 0, [[[9, 'Blue', 7, 'F0025']]], 1)
        for key in message:
            if key not in ('v', 'op'):
                self.assertIn(f'root["{key}"]', source)
        self.assertIn('op == "browse"', source)
        self.assertIn('"esphome.screen_browse"', (ROOT / 'components/smart_display/runtime_tiles.h').read_text())
        self.assertIn('"esphome.screen_play"', (ROOT / 'components/smart_display/runtime_tiles.h').read_text())
        self.assertIn('features.add("media_library")', (ROOT / 'packages/core.yaml').read_text())


class AStart(unittest.IsolatedAsyncioTestCase):
    def player(self, features, source=None, state='idle'):
        attributes = {'supported_features': features, 'source_list': ['Bedroom', 'Kitchen']}
        if source:
            attributes['source'] = source
        return {'state': state, 'attributes': attributes}

    async def test_from_rest_the_speaker_wakes_it_and_then_it_plays(self):
        states = {PLAYER: self.player(AT_REST)}
        calls = []
        item = media_library.item_of(albums(1)['children'][0])

        async def call(domain, service, data):
            calls.append((f'{domain}.{service}', data))
            if service == 'select_source':
                async def woken():
                    await asyncio.sleep(0.05)
                    states[PLAYER] = self.player(PLAYING, data['source'], 'paused')
                asyncio.ensure_future(woken())
        outcome = await media_library.start(states, call, PLAYER, item, 'Kitchen', sleep=asyncio.sleep)
        self.assertEqual(outcome, 'playing')
        self.assertEqual(calls, [('media_player.select_source', {'entity_id': PLAYER, 'source': 'Kitchen'}),
                                 ('media_player.play_media', {'entity_id': PLAYER, 'media_content_type': 'spotify://album',
                                                              'media_content_id': 'spotify:album:' + '0' * 22})])

    async def test_a_player_that_plays_plays_it_at_once(self):
        states = {PLAYER: self.player(PLAYING, 'Kitchen', 'playing')}
        calls = []

        async def call(domain, service, data):
            calls.append(service)
        item = media_library.item_of(albums(1)['children'][0])
        self.assertEqual(await media_library.start(states, call, PLAYER, item), 'playing')
        self.assertEqual(calls, ['play_media'])
        calls.clear()
        self.assertEqual(await media_library.start(states, call, PLAYER, item, 'Kitchen'), 'playing')
        self.assertEqual(calls, ['play_media'], 'the speaker it plays on is no change')

    async def test_at_rest_without_a_speaker_or_without_waking_nothing_plays(self):
        item = media_library.item_of(albums(1)['children'][0])
        calls = []

        async def call(domain, service, data):
            calls.append(service)
        self.assertEqual(await media_library.start({PLAYER: self.player(AT_REST)}, call, PLAYER, item), 'no speaker')
        clock = iter(range(0, 100, 1))
        self.assertEqual(await media_library.start({PLAYER: self.player(AT_REST)}, call, PLAYER, item, 'Kitchen', wait=3,
                                                   sleep=lambda s: asyncio.sleep(0), clock=lambda: next(clock)), 'not woken')
        self.assertEqual(calls, ['select_source'])


class ThePlayersState(unittest.TestCase):
    def test_the_extras_of_a_player(self):
        attrs = {'source': 'Kitchen', 'source_list': [f'Speaker {n}' for n in range(20)], 'shuffle': False, 'repeat': 'one',
                 'supported_features': AT_REST}
        extras = media_library.player_extras(attrs, PLAYING, '2B484F,121E20', True)
        self.assertEqual(extras['so'], 'Kitchen')
        self.assertEqual(len(extras['sl']), media_library.SOURCES)
        self.assertEqual((extras['sh'], extras['rp'], extras['mf'], extras['g'], extras['lb']), (0, 'one', PLAYING, '2B484F,121E20', 1))
        self.assertEqual(media_library.player_extras({'supported_features': PLAYING}, PLAYING), {}, 'nothing to say, nothing sent')
        self.assertNotIn('rp', media_library.player_extras({'repeat': 'sometimes'}))

    @unittest.skipUnless(HAS_PIL, 'Pillow')
    def test_a_covers_colours_are_dark_and_its_own(self):
        from PIL import Image, ImageDraw
        image = Image.new('RGB', (64, 64), (200, 40, 30))
        ImageDraw.Draw(image).rectangle((0, 40, 64, 64), fill=(30, 90, 200))
        out = io.BytesIO()
        image.save(out, 'PNG')
        ground = media_library.ground_colours(out.getvalue())
        top, bottom = (tuple(int(c[i:i + 2], 16) for i in (0, 2, 4)) for c in ground.split(','))
        # One colour at both ends, so the screen draws a flat ground: a 16-bit gradient between two dark colours
        # showed as bands (GitHub #135). It is the cover's leading colour, dark enough for white words.
        self.assertEqual(top, bottom)
        self.assertIn(max(range(3), key=lambda i: top[i]), (0, 2))
        self.assertLess(max(top), 100)
        self.assertIsNone(media_library.ground_colours(png((128, 128, 128))), 'a grey cover keeps the neutral ground')

    def test_a_player_at_rest_keeps_what_it_had(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / 'media-features.json'
            memory = media_library.FeatureMemory(path)
            playing = {'state': 'playing', 'attributes': {'supported_features': PLAYING}}
            resting = {'state': 'idle', 'attributes': {'supported_features': AT_REST}}
            self.assertIs(memory.widened(PLAYER, playing), playing)
            widened = memory.widened(PLAYER, resting)
            self.assertEqual(widened['attributes']['supported_features'], PLAYING | AT_REST)
            self.assertEqual(resting['attributes']['supported_features'], AT_REST, 'Home Assistant\'s own state stays as it is')
            memory.save()
            self.assertEqual(media_library.FeatureMemory(path).widest(PLAYER, {'supported_features': 0}), PLAYING | AT_REST)
            self.assertIs(memory.widened('light.hall', resting), resting, 'only media players')
            # Spotify says in Home Assistant's source what it reports while it plays: a player never seen playing has it.
            fresh = media_library.FeatureMemory(None, platform_of=lambda entity: 'spotify')
            self.assertEqual(fresh.widened('media_player.other', resting)['attributes']['supported_features'], PLAYING)
            other = media_library.FeatureMemory(None, platform_of=lambda entity: 'sonos')
            self.assertIs(other.widened('media_player.other', resting), resting)


@unittest.skipUnless(HAS_AIOHTTP and HAS_PIL, 'Run using .venv-portal/bin/python for server tests')
class TheApp(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        camera_feed.base_url.__defaults__[0].clear()

    def ha(self):
        class HA:
            online = True

            def __init__(self):
                self.registry = [{'entity_id': 'text.d1_tiles', 'platform': 'esphome', 'original_name': 'Tile settings', 'device_id': 'd1'},
                                 {'entity_id': 'sensor.d1_node', 'platform': 'esphome', 'original_name': 'Device name', 'device_id': 'd1'},
                                 {'entity_id': 'sensor.d1_fw', 'platform': 'esphome', 'original_name': 'Screen firmware', 'device_id': 'd1'},
                                 {'entity_id': 'select.d1_type', 'platform': 'esphome', 'original_name': 'Guition screen type', 'device_id': 'd1'}]
                self.devices, self.areas = [{'id': 'd1', 'name': 'Hall'}], []
                self.states = {'text.d1_tiles': {'state': 'Synced'}, 'sensor.d1_node': {'state': 'hall'}, 'sensor.d1_fw': {'state': '0.24.0'},
                               PLAYER: {'state': 'idle', 'attributes': {'supported_features': AT_REST, 'source_list': ['Kitchen']}}}
                self.changed, self.dirty, self.log, self.responses = asyncio.Event(), set(), [], set()

            async def send(self, inbox, message, action=None, respond=False):
                self.log.append(('send', inbox, dict(message)))

            async def call_answer(self, domain, service, data):
                self.log.append(('answer', service, data))
                return {PLAYER: albums(48) if data.get('media_content_id') == 'current_user_saved_albums' else TOP}

            async def call_service(self, domain, service, data):
                self.log.append(('call', service, data))
                if service == 'select_source':
                    self.states[PLAYER] = {'state': 'paused', 'attributes': {'supported_features': PLAYING, 'source': data['source'], 'source_list': ['Kitchen']}}

            async def browse_image(self, entity, url):
                self.log.append(('thumbnail', url))
                return png((40, 120, 200))

            async def request(self, kind, **data):
                if kind == 'network':
                    return {'adapters': [{'name': 'end0', 'default': True, 'ipv4': [{'address': '192.168.1.57'}]}]}
                raise ConnectionError(kind)
        return HA()

    async def test_a_screen_opens_a_folder_and_plays_what_it_taps(self):
        with tempfile.TemporaryDirectory() as tmp:
            ha = self.ha()
            m = Manager(with_screen_grid(ha), Path(tmp) / 'screens.json')
            seed_layout(m, 'text.d1_tiles', validate_layout({'title': 'Music', 'tiles': [{'entity': PLAYER, 'name': 'Spotify'}]}))
            await m.answer_browse({'inbox': 'text.d1_tiles', 'entity': PLAYER, 'folder': '0', 'page': '0'})
            (message,) = [e[2] for e in ha.log if e[0] == 'send']
            self.assertEqual((message['op'], message['f'], message['t'], message['c']), ('browse', 0, 'Media Library', 8))
            albums_token = message['k'][2][0]
            ha.log.clear()
            await m.answer_browse({'inbox': 'text.d1_tiles', 'entity': PLAYER, 'folder': str(albums_token), 'page': '0'})
            (message,) = [e[2] for e in ha.log if e[0] == 'send']
            self.assertEqual((message['t'], message['c']), ('Albums', 48))
            (asked,) = [e[2] for e in ha.log if e[0] == 'answer']
            self.assertEqual(asked['media_content_id'], 'current_user_saved_albums')
            first = message['k'][0][0]
            # The covers of its page: one picture of the frames the screen names.
            ha.log.clear()
            atlas = json.dumps([[0, 0, 100, 100, 8, 0], [110, 0, 100, 100, 8, 0]])
            with self.assertLogs('screen_manager', 'INFO'):
                await m.answer_camera({'inbox': 'text.d1_tiles', 'entity': PLAYER, 'lib': f'{first},{first + 1}', 'atlas': atlas, 'bg': 'E7E7E7'})
            (cover,) = [e[2] for e in ha.log if e[0] == 'send']
            self.assertEqual((cover['op'], cover['t'], cover['e']), ('camera', 'lib', PLAYER))
            status, raw, _ = await m.camera.serve(cover['u'].rsplit('/', 1)[1][:-4])
            self.assertEqual(status, 200)
            from PIL import Image
            with Image.open(io.BytesIO(raw)) as image:
                self.assertEqual(image.size, (210, 100))
            self.assertEqual(len([e for e in ha.log if e[0] == 'thumbnail']), 2)
            # A tap at rest, on the speaker chosen: the speaker, then the album.
            ha.log.clear()
            await m.answer_play({'inbox': 'text.d1_tiles', 'entity': PLAYER, 'item': str(first), 'source': 'Kitchen'})
            self.assertEqual([e[1] for e in ha.log if e[0] == 'call'], ['select_source', 'play_media'])
            self.assertEqual(m.started[PLAYER], ('spotify://album', 'spotify:album:' + '0' * 22))

    async def test_only_a_player_on_the_screens_layout_and_its_own_numbers(self):
        with tempfile.TemporaryDirectory() as tmp:
            ha = self.ha()
            m = Manager(with_screen_grid(ha), Path(tmp) / 'screens.json')
            seed_layout(m, 'text.d1_tiles', validate_layout({'title': 'Music', 'tiles': [{'entity': 'media_player.tv', 'name': 'TV'}]}))
            await m.answer_browse({'inbox': 'text.d1_tiles', 'entity': PLAYER, 'folder': '0', 'page': '0'})
            await m.answer_play({'inbox': 'text.d1_tiles', 'entity': PLAYER, 'item': '1'})
            self.assertEqual(ha.log, [])
            seed_layout(m, 'text.d1_tiles', validate_layout({'title': 'Music', 'tiles': [{'entity': PLAYER, 'name': 'Spotify'}]}))
            # A number this app never gave: the folder did not answer, nothing plays.
            await m.answer_browse({'inbox': 'text.d1_tiles', 'entity': PLAYER, 'folder': '999', 'page': '0'})
            (message,) = [e[2] for e in ha.log if e[0] == 'send']
            self.assertEqual((message['k'], message.get('x')), ([], 1))
            await m.answer_play({'inbox': 'text.d1_tiles', 'entity': PLAYER, 'item': '999'})
            await m.answer_play({'inbox': 'text.d1_tiles', 'entity': PLAYER, 'item': 'x'})
            self.assertEqual([e for e in ha.log if e[0] == 'call'], [])

    async def test_a_screen_that_draws_it_gets_the_players_extras(self):
        with tempfile.TemporaryDirectory() as tmp:
            ha = self.ha()
            m = Manager(with_screen_grid(ha), Path(tmp) / 'screens.json')
            tile = {'entity': PLAYER, 'name': 'Spotify', 'options': {}}
            m.players.note(PLAYER, {'supported_features': PLAYING})
            old = await m.tile_message(0, tile, features=frozenset())
            self.assertNotIn('sl', old.get('x', {}), 'an older screen gets what it got before')
            new = await m.tile_message(0, tile, features=frozenset({media_library.FEATURE}))
            self.assertEqual((new['x']['sl'], new['x']['mf']), (['Kitchen'], PLAYING | AT_REST))
            await asyncio.sleep(0.05)  # the library is asked once whether it opens
            new = await m.tile_message(0, tile, features=frozenset({media_library.FEATURE}))
            self.assertEqual(new['x'].get('lb'), 1)


if __name__ == '__main__':
    unittest.main()
