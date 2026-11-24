"""The segment manifest and the offline bundle.

The games that used to live beside these are gone, so what is left is the part
that has to stay exact: a seek position is a real rendered duration or it is
nothing at all, and the bundle a reader downloads reaches no network and carries
no credential.
"""
import re
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch
from app.pipeline import interactive


class ManifestTests(unittest.TestCase):
    def test_timestamps_follow_actual_rendered_clip_durations(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'tts_work').mkdir()
            for i in range(2):(root/'tts_work'/f'seg_{i:02d}.mp4').touch()
            meta={'tts_output':'slideshow.mp4','storyboard':{'scenes':[{'text':'一','segment_title':'开场'},{'text':'二'}]}}
            with patch.object(interactive.tts,'duration_of',side_effect=[2.35,4.81]):
                manifest=interactive.build_manifest(root,meta)
            self.assertAlmostEqual(manifest['segments'][1]['start'],2.35)
            self.assertAlmostEqual(manifest['duration'],7.16)

    def test_a_segment_carries_no_game(self):
        """Nothing downstream may start expecting one again."""
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'tts_work').mkdir();(root/'tts_work/seg_00.mp4').touch()
            meta={'tts_output':'slideshow.mp4','storyboard':{'scenes':[{'text':'一'}]},
                  'games':[{'scene_index':0,'kind':'predict'}]}   # stale meta from an old run
            with patch.object(interactive.tts,'duration_of',return_value=3):
                manifest=interactive.build_manifest(root,meta)
            self.assertNotIn('game',manifest['segments'][0])

    def test_missing_clip_does_not_produce_fictional_seek_positions(self):
        with tempfile.TemporaryDirectory() as directory:
            self.assertIsNone(interactive.build_manifest(Path(directory),{'tts_output':'v.mp4','storyboard':{'scenes':[{'text':'test'}]}}))

    def test_export_is_offline_and_has_no_credentials(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'tts_work').mkdir();(root/'tts_work/seg_00.mp4').touch();(root/'slideshow.mp4').write_bytes(b'test-video')
            meta={'title':'</script><script>bad()</script>','tts_output':'slideshow.mp4','storyboard':{'scenes':[{'text':'source'}]}}
            with patch.object(interactive.tts,'duration_of',return_value=3):
                bundle=interactive.export_bundle(root,meta)
            with zipfile.ZipFile(bundle) as archive:
                html=archive.read('index.html').decode()
                self.assertIn('id="experienceData"',html)
                self.assertNotIn('/assets/',html)
                self.assertNotIn('<script>bad()',html)
                self.assertIn('media/video.mp4',archive.namelist())
                self.assertFalse(any('.env' in name for name in archive.namelist()))
                # The flat emoji must travel with the bundle; a reader opening it
                # from disk has no network to fetch /assets/ from.
                self.assertIn('emoji/1f5a5.svg', archive.namelist())
                self.assertIn('emoji/LICENSE.txt', archive.namelist())
                # Every stylesheet the page names has to be in the archive, or
                # the bundle opens unstyled. paint.css was added to the page and
                # not to the list, and this is what caught it.
                for sheet in re.findall(r'<link[^>]+href="([^"]+\.css[^"]*)"', html):
                    self.assertFalse(sheet.startswith(('http', '/')), sheet)
                    self.assertIn(sheet.split('?')[0], archive.namelist())
                # README promises the bundle plays offline with no server. A
                # single external reference makes that false -- and costs a DNS
                # timeout before the page paints.
                self.assertNotIn('http://', html)
                self.assertNotIn('https://', html)

if __name__=='__main__':unittest.main()
