"""Spotify actions use fake lookup, AppleScript, and accessibility layers only."""
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import time
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import tests  # noqa: F401 -- first: scratch RABIK_DIR, no telemetry, host guard
import brain.cli, brain.hands, brain.instant, brain.labels, brain.macos, brain.paths, brain.prefs, brain.prompts, brain.skills
import brain.spotify, brain.web, brain.windows


class SpotifyTests(unittest.TestCase):
    def test_playlist_cache_recovers_from_bad_json_and_replaces_atomically(self):
        with tempfile.TemporaryDirectory() as root, tests.patches(patch.multiple(brain.paths, DIR=root),
                                                                  patch.multiple(brain.spotify, PLAYLISTS=os.path.join(root, 'playlists.json'))), \
             patch.object(os, 'walk', return_value=[]):
            cache = Path(brain.spotify.PLAYLISTS)
            cache.write_text('{cut off')
            self.assertIsNone(brain.spotify.playlist('missing'))
            self.assertEqual(json.loads(cache.read_text()), {})

            cache.write_text(json.dumps({'old': 'Old playlist'}))
            os.utime(cache, (time.time() - 4000,) * 2)
            with patch.object(json, 'dump', side_effect=RuntimeError('interrupted')):
                with self.assertRaises(RuntimeError):
                    brain.spotify.playlist('missing')
            self.assertEqual(json.loads(cache.read_text()), {'old': 'Old playlist'})

    def test_playlist_retries_a_cached_blank_title(self):
        playlist_id = 'H' * 22
        with tempfile.TemporaryDirectory() as root:
            spotify = Path(root) / 'Library/Application Support/Spotify'
            spotify.mkdir(parents=True)
            (spotify / 'cache').write_bytes(f'spotify:playlist:{playlist_id}'.encode())
            cache = Path(root) / 'playlists.json'
            cache.write_text(json.dumps({playlist_id: ''}))
            os.utime(cache, (time.time() - 4000,) * 2)
            with tests.patches(patch.multiple(brain.paths, HOME=root, DIR=root),
                               patch.multiple(brain.spotify, PLAYLISTS=str(cache))), \
                 patch.object(brain.web, 'get', return_value=json.dumps({'title': 'Recovered playlist'})) as get:
                self.assertEqual(brain.spotify.playlist('recovered playlist'),
                                 (f'spotify:playlist:{playlist_id}', 'Recovered playlist'))
            get.assert_called_once()

    def test_lookup_prefers_cached_playlist_and_falls_back_to_web(self):
        cached = ('spotify:playlist:cached', 'Road trip')
        with patch.object(brain.spotify, 'playlist', return_value=cached), patch.object(brain.web, 'get') as get:
            self.assertEqual(brain.spotify.spotify_item('road trip'), cached)
            get.assert_not_called()

        track = 'A' * 22
        page = f'https://open.spotify.com/track/{track}'
        with patch.object(brain.spotify, 'playlist', return_value=None), \
             patch.object(brain.web, 'get', side_effect=[page, json.dumps({'title': 'Fixture song'})]):
            self.assertEqual(brain.spotify.spotify_item('fixture song'), (f'spotify:track:{track}', 'Fixture song'))

    def test_web_lookup_rejects_a_weak_title_before_playing(self):
        track = 'W' * 22
        page = f'https://open.spotify.com/track/{track}'
        with patch.object(brain.spotify, 'playlist', return_value=None), \
             patch.object(brain.web, 'get', side_effect=[page, json.dumps({'title': 'Unrelated public playlist'})]), \
             patch.object(subprocess, 'run') as run:
            self.assertIsNone(brain.spotify.play('fixture playlist'))
        run.assert_not_called()

    def test_play_uses_shared_lookup_and_keeps_spotify_behind(self):
        item = ('spotify:track:' + 'B' * 22, 'Fixture song')
        with patch.object(brain.spotify, 'spotify_item', return_value=item) as lookup, \
             patch.object(brain.macos, 'osa', return_value='Editor'), \
             patch.object(subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, 'playing', '')) as run, \
             patch.object(brain.macos, 'preview_app') as preview, patch.object(brain.macos, 'wants_focus', return_value=False), \
             patch.object(brain.windows, 'keep_behind') as behind:
            self.assertEqual(brain.spotify.play('fixture'), 'Playing Fixture song on Spotify.')
        lookup.assert_called_once_with('fixture', True)
        self.assertEqual(run.call_args.args[0][-1], item[0])
        preview.assert_called_once_with('Spotify', 'play')
        behind.assert_called_once_with('Editor', 'Spotify')

    def test_play_reply_names_spotify_once(self):
        item = ('spotify:playlist:' + 'C' * 22, 'Top 100 Pop Tracks on Spotify')
        with patch.object(brain.spotify, 'spotify_item', return_value=item), patch.object(brain.macos, 'osa', return_value='Editor'), \
             patch.object(subprocess, 'run', return_value=subprocess.CompletedProcess([], 0, 'playing', '')), \
             patch.object(brain.macos, 'preview_app'), patch.object(brain.windows, 'keep_behind'):
            self.assertEqual(brain.spotify.play('my playlist'), 'Playing Top 100 Pop Tracks on Spotify.')
        self.assertEqual(brain.labels.label('Bash', {'command': f'{brain.paths.PLAY} "hits on spotify"'}), 'Playing hits on spotify')

    def test_play_reports_rejected_or_unverified_spotify_commands(self):
        item = ('spotify:track:' + 'G' * 22, 'Fixture song')
        for result in (subprocess.CompletedProcess([], 1, '', 'denied'),
                       subprocess.CompletedProcess([], 0, 'paused', '')):
            with self.subTest(result=result), patch.object(brain.spotify, 'spotify_item', return_value=item), \
                 patch.object(brain.macos, 'osa', return_value='Editor'), patch.object(subprocess, 'run', return_value=result), \
                 patch.object(brain.macos, 'preview_app') as preview, patch.object(brain.windows, 'keep_behind') as behind:
                reply = brain.spotify.play('fixture')
            self.assertIn('Could not start Fixture song', reply)
            preview.assert_not_called()
            behind.assert_not_called()

    def test_queue_uses_discovered_ax_labels_and_verifies_the_toast(self):
        item = ('spotify:track:' + 'C' * 22, 'Fixture song')
        page = {'texts': ['Fixture song'], 'nodes': [{'role': 'AXButton', 'label': 'More options for Fixture song'}]}
        menu = {'texts': [], 'nodes': [{'role': 'AXMenuItem', 'label': 'Add to queue'}]}
        toast = {'texts': ['Fixture song', 'Added to queue'], 'nodes': []}
        actions = [('Clicked More options', True), ('Clicked Add to queue\nAdded to queue', True)]
        with patch.object(brain.spotify, 'spotify_item', return_value=item), \
             patch.object(brain.macos, 'osa', return_value='Editor'), \
             patch.object(subprocess, 'run', return_value=subprocess.CompletedProcess([], 0)) as run, \
             patch.object(brain.macos, 'preview_app'), patch.object(brain.hands, 'hands_map', return_value=page), \
             patch.object(brain.macos, 'cached_hands', side_effect=[menu, toast]), \
             patch.object(brain.hands, 'hands', side_effect=actions) as hands, \
             patch.object(brain.windows, 'keep_behind') as behind:
            self.assertEqual(brain.spotify.queue('fixture'), 'Added Fixture song to your Spotify queue.')
        run.assert_called_once_with(['open', '-g', item[0]], capture_output=True)
        self.assertEqual(hands.call_args_list[0].args, ('click', 'More options for Fixture song', 'near', 'Fixture song'))
        self.assertEqual(hands.call_args_list[1].args, ('click', 'Add to queue'))
        self.assertEqual(behind.call_count, 3)

    def test_queue_waits_for_the_requested_track_before_opening_its_menu(self):
        item = ('spotify:track:' + 'F' * 22, 'Requested fixture')
        old_page = {'texts': ['Different track'], 'nodes': [{'role': 'AXButton', 'label': 'More options'}]}
        with patch.object(brain.spotify, 'spotify_item', return_value=item), patch.object(brain.macos, 'osa', return_value='Editor'), \
             patch.object(subprocess, 'run', return_value=subprocess.CompletedProcess([], 0)), \
             patch.object(brain.macos, 'preview_app'), patch.object(brain.hands, 'hands_map', return_value=old_page), \
             patch.object(brain.hands, 'hands') as hands, patch.object(brain.windows, 'keep_behind'), patch.object(time, 'sleep'):
            reply = brain.spotify.queue('requested')
        self.assertIn('could not find its More options control', reply)
        hands.assert_not_called()

    def test_queue_identity_requires_an_exact_title_and_matching_control(self):
        wrong = {'texts': ['Homecoming'], 'nodes': [{'label': 'More options for Homecoming'}]}
        with patch.object(brain.hands, 'hands_map', return_value=wrong), patch.object(time, 'sleep'):
            self.assertEqual(brain.spotify._spotify_wait_control(('more', 'option'), 'Home'), (None, None))
        self.assertIsNone(brain.spotify._spotify_control({**wrong, 'texts': ['Home']}, ('more', 'option'), 'Home'))
        self.assertFalse(brain.spotify._spotify_verified('Added to queue', wrong, 'Home', action=True))
        self.assertFalse(brain.spotify._spotify_verified('Added to queue', {'texts': ['Home']}, 'Homecoming', action=True))
        self.assertTrue(brain.spotify._spotify_verified('Added to queue', {'texts': ['Up']}, 'Up', action=True))

    def test_queue_can_verify_the_track_in_the_queue_view(self):
        item = ('spotify:track:' + 'D' * 22, 'Another fixture')
        page = {'texts': ['Another fixture'], 'nodes': [{'role': 'AXButton', 'label': 'More options'}]}
        menu = {'texts': [], 'nodes': [{'role': 'AXMenuItem', 'label': 'Add to queue'}]}
        queue_button = {'texts': [], 'nodes': [{'role': 'AXButton', 'label': 'Queue'}]}
        queue_view = {'texts': ['Another fixture'], 'nodes': []}
        with patch.object(brain.spotify, 'spotify_item', return_value=item), patch.object(brain.macos, 'osa', return_value='Editor'), \
             patch.object(subprocess, 'run', return_value=subprocess.CompletedProcess([], 0)), \
             patch.object(brain.macos, 'preview_app'), patch.object(brain.hands, 'hands_map', return_value=page), \
             patch.object(brain.macos, 'cached_hands', side_effect=[menu, queue_button, queue_view]), \
             patch.object(brain.hands, 'hands', side_effect=[('More', True), ('Added', True), ('Queue opened', True)]) as hands, \
             patch.object(brain.windows, 'keep_behind'):
            self.assertEqual(brain.spotify.queue('another'), 'Added Another fixture to your Spotify queue.')
        self.assertEqual(hands.call_args_list[-1].args, ('click', 'Queue'))

    def test_queue_does_not_claim_success_when_spotify_exposes_no_verification(self):
        item = ('spotify:track:' + 'E' * 22, 'Unverified fixture')
        page = {'texts': ['Unverified fixture'], 'nodes': [{'role': 'AXButton', 'label': 'More options'}]}
        menu = {'texts': [], 'nodes': [{'role': 'AXMenuItem', 'label': 'Add to queue'}]}
        with patch.object(brain.spotify, 'spotify_item', return_value=item), patch.object(brain.macos, 'osa', return_value='Editor'), \
             patch.object(subprocess, 'run', return_value=subprocess.CompletedProcess([], 0)), \
             patch.object(brain.macos, 'preview_app'), patch.object(brain.hands, 'hands_map', return_value=page), \
             patch.object(brain.macos, 'cached_hands', side_effect=[menu, {'texts': ['Unverified fixture'], 'nodes': []}]), \
             patch.object(brain.hands, 'hands', side_effect=[('More', True), ('Added', True)]) as hands, \
             patch.object(brain.windows, 'keep_behind'), patch.object(time, 'sleep'):
            reply = brain.spotify.queue('unverified')
        self.assertIn('could not verify it', reply)
        self.assertIn('do not retry blindly', reply)
        self.assertEqual(hands.call_count, 2)

    def test_queue_explains_the_album_and_playlist_limit_without_opening_spotify(self):
        for kind in ('album', 'playlist', 'artist'):
            with self.subTest(kind=kind), patch.object(brain.spotify, 'spotify_item', return_value=(f'spotify:{kind}:id', 'Fixture')), \
                 patch.object(subprocess, 'run') as run, patch.object(brain.hands, 'hands') as hands:
                reply = brain.spotify.queue('fixture')
            self.assertIn(f'tracks in that {kind}', reply)
            self.assertIn('Name one song', reply)
            run.assert_not_called()
            hands.assert_not_called()

    def test_unambiguous_queue_requests_run_without_ai(self):
        with patch.object(brain.prefs, 'pref', side_effect=lambda _, default: default), \
             patch.object(brain.skills, 'skills', return_value={}), patch.object(brain.hands, 'fast_hands', return_value=None), \
             patch.object(brain.spotify, 'queue', return_value='Added Fixture song to your Spotify queue.') as queue, \
             patch.dict(os.environ, {'RABIK_LIVE': '1'}):
            for request in ('add Fixture song to my queue', 'queue Fixture song next'):
                with self.subTest(request=request):
                    self.assertEqual(brain.instant.fast(request).reply, 'Added Fixture song to your Spotify queue.')
                    queue.assert_called_with('fixture song')
            queue.reset_mock()
            self.assertIsNone(brain.instant.fast('add it to my queue').reply)
            queue.assert_not_called()

    def test_queue_cli_and_step_label(self):
        with patch.object(brain.spotify, 'queue', return_value='Added Fixture song to your Spotify queue.') as queue, \
             patch('sys.argv', ['rabik.py', '--queue', 'Fixture', 'song']), \
             patch('sys.stdout', new_callable=io.StringIO) as out:
            brain.cli.main()
        queue.assert_called_once_with('Fixture song')
        self.assertEqual(out.getvalue().strip(), 'Added Fixture song to your Spotify queue.')
        self.assertEqual(brain.labels.label('Bash', {'command': f'{brain.paths.QUEUE} "Fixture song"'}),
                         'Adding Fixture song to the queue')
        self.assertIn(brain.paths.QUEUE, brain.prompts.SYSTEM)


if __name__ == '__main__':
    unittest.main()
