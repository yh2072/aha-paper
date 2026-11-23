import json
import tempfile
import unittest
import wave
import zipfile
from pathlib import Path
from unittest.mock import patch
from PIL import Image
from pypdf import PdfWriter
from app.pipeline import explainer,interactive

class RealtimeWorkflowTests(unittest.TestCase):
    def test_live_build_never_creates_video_frames_and_exports_self_contained(self):
        with tempfile.TemporaryDirectory() as directory:
            root=Path(directory);(root/'figures').mkdir()
            Image.new('RGB',(400,300),'white').save(root/'figures/fig.png')
            writer=PdfWriter()
            for _ in range(2):writer.add_blank_page(width=200,height=300)
            with open(root/'paper.pdf','wb') as handle:writer.write(handle)
            def synth(sentences,path,log=print,profile=None):
                with wave.open(str(path),'wb') as audio:
                    audio.setnchannels(1);audio.setsampwidth(2);audio.setframerate(24000);audio.writeframes(b'\0\0'*24000)
                return path,[1/len(sentences)]*len(sentences)
            meta={'id':root.name,'engine':'pi-canvas','title':'实时讲解','doi':'10.1/test','figures':[{'file':'fig.png','page':2}],
                'script_profile':'deep-science-v1',
                'storyboard':{'scenes':[{'text':'先看这个概念。','source_pages':[1]},
                    {'text':'再看这张主图。','figure':'fig.png','figure_path':str(root/'figures/fig.png'),'source_pages':[2]}]}}
            # The planner is exercised by its own suite; here it must simply not
            # reach a provider, so the chapter falls back to the pages it cites.
            with patch.object(explainer.tts,'synthesize_sentences',side_effect=synth),\
                 patch.object(explainer.page_highlight,'prepare',lambda *a,**k:None),\
                 patch.object(explainer.figures,'map_sentences_to_regions',return_value=[[.1,.2,.3,.4]]):
                manifest=explainer.build(root,meta,log=lambda _:None)
            self.assertEqual(manifest['mode'],'explainer')
            self.assertAlmostEqual(manifest['duration'],2)
            self.assertTrue((root/'narration.mp3').exists())
            self.assertFalse(list(root.rglob('*.mp4')))
            # No plan was made, and the chapter still shows the paper rather than
            # falling through to something drawn for it.
            self.assertEqual([s['visual']['kind'] for s in manifest['segments']],['page','figure'])
            self.assertEqual(manifest['segments'][1]['cues'][0]['region'],[.1,.2,.3,.4])
            meta.update(experience_mode='explainer')
            self.assertEqual(interactive.build_manifest(root,meta)['mode'],'explainer')
            bundle=interactive.export_bundle(root,meta)
            with zipfile.ZipFile(bundle) as archive:
                names=archive.namelist()
                self.assertIn('media/narration.mp3',names)
                self.assertIn('figures/fig.png',names)
                self.assertIn('explainer-player.js',names)
                self.assertNotIn('media/video.mp4',names)
                # No model-authored page ships any more; the old engine put them here.
                self.assertFalse([n for n in names if n.startswith('code/')])
                embedded=archive.read('index.html').decode()
                self.assertNotIn('/assets/',embedded)
                self.assertIn('media/narration.mp3',embedded)

if __name__=='__main__':unittest.main()
