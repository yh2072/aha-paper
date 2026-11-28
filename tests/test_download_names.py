"""Downloads are saved under the explainer's title, not as explainer.mp4."""
import json
import re
import subprocess
import unittest

from app import bin as binaries, config, jobs

TITLES = ['多个大模型智能体如何协作：一篇综述提出的五模块工作流框架', 'a/b: c?', '..hidden..', '', 'x' * 80]


class DownloadNameTests(unittest.TestCase):
    def test_the_title_names_the_file(self):
        self.assertEqual(jobs.download_name({'title': '大脑如何读算式'}, '.mp4'), '大脑如何读算式.mp4')
        self.assertEqual(jobs.download_name({'paper_title': 'A survey'}, '_封面.png'), 'A survey_封面.png')

    def test_characters_a_file_system_refuses_are_dropped(self):
        self.assertEqual(jobs.download_name({'title': 'a/b: c?'}, '.mp4'), 'ab c.mp4')
        self.assertEqual(jobs.download_name({}, '.mp4'), '未命名.mp4')

    def test_the_pages_use_the_same_rule(self):
        """web/studio.js and web/watch.js name the files they link to themselves."""
        for page in ('studio.js', 'watch.js'):
            source = (config.ROOT / 'web' / page).read_text()
            rule = re.search(r'const saveAs=.*?;\n', source).group(0)
            script = rule + f'process.stdout.write(JSON.stringify({json.dumps(TITLES)}.map(t=>saveAs(t,".mp4"))))'
            done = subprocess.run([binaries.node(), '-e', script], capture_output=True, text=True, check=True)
            with self.subTest(page):
                self.assertEqual(json.loads(done.stdout), [jobs.download_name({'title': t}, '.mp4') for t in TITLES])


if __name__ == '__main__':
    unittest.main()
